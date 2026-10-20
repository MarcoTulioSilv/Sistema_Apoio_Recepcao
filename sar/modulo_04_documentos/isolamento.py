"""Isolamento do processamento (DD-35, SEG-30): a validação, a reconstrução e a extração rodam num processo filho
com tempo máximo e, no Linux, com teto de memória e de CPU; se a decodificação travar, estourar ou for explorada, o
estrago fica no filho, que morre sem levar o worker.

Comunicação só por pipe, nada em claro no disco (SEG-08). O quadro é: 4 bytes com o tamanho do cabeçalho, o
cabeçalho em JSON (com o tamanho de cada parte) e as partes em sequência. Nunca pickle: o pai trata a resposta do
filho como entrada não confiável e confere formato, campos e tamanhos.
"""

from __future__ import annotations

import io
import json
import os

# Só o próprio interpretador, com módulo e argumentos fixos, sem shell.
import subprocess  # nosec B404
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, BinaryIO

from sar.modulo_04_documentos.processamento import Campo, Limites, Recusa

CABECALHO_MAXIMO = 64 * 1024
VALOR_MAXIMO = 60
MEMORIA_MAXIMA_MB = 1536
# O filho herda só o necessário para achar o Python e o Tesseract; nada de credencial de banco ou chave (SEG-30).
AMBIENTE_PERMITIDO = {"PATH", "SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP", "LANG", "LC_ALL", "SAR_TESSERACT",
                      "TESSDATA_PREFIX", "VIRTUAL_ENV", "PYTHONPATH"}  # fmt: skip


def escrever_quadro(fluxo: BinaryIO, cabecalho: dict[str, Any], partes: Sequence[bytes]) -> None:
    corpo = json.dumps({**cabecalho, "tamanhos": [len(p) for p in partes]}).encode()
    fluxo.write(len(corpo).to_bytes(4, "big") + corpo)
    for parte in partes:
        fluxo.write(parte)
    fluxo.flush()


def _ler_exato(fluxo: BinaryIO, tamanho: int) -> bytes:
    dados = fluxo.read(tamanho)
    if len(dados) != tamanho:
        raise ValueError("quadro incompleto")
    return dados


def ler_quadro(fluxo: BinaryIO, maximo: int | None = None) -> tuple[dict[str, Any], list[bytes]]:
    """Lê um quadro; `maximo` limita a soma das partes (o pai lê o filho sempre com limite)."""
    tamanho = int.from_bytes(_ler_exato(fluxo, 4), "big")
    if tamanho > CABECALHO_MAXIMO:
        raise ValueError("cabeçalho grande demais")
    cabecalho = json.loads(_ler_exato(fluxo, tamanho))
    tamanhos = cabecalho.pop("tamanhos")
    if not isinstance(cabecalho, dict) or not all(isinstance(t, int) and t >= 0 for t in tamanhos):
        raise ValueError("cabeçalho inválido")
    if maximo is not None and sum(tamanhos) > maximo:
        raise ValueError("resposta grande demais")
    return cabecalho, [_ler_exato(fluxo, t) for t in tamanhos]


@dataclass(frozen=True, slots=True)
class Resultado:
    conteudo: bytes
    formato: str
    paginas: int
    campos: tuple[Campo, ...]


def _ambiente() -> dict[str, str]:
    return {chave: valor for chave, valor in os.environ.items() if chave.upper() in AMBIENTE_PERMITIDO}


def _limitar(memoria_mb: int, cpu_segundos: int) -> Any:
    """Teto de memória e de CPU do filho (só POSIX; no Windows vale o tempo máximo de parede)."""
    if sys.platform == "win32":
        return None

    def aplicar() -> None:
        import resource  # só existe no POSIX

        resource.setrlimit(resource.RLIMIT_AS, (memoria_mb * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_segundos, cpu_segundos))

    return aplicar


def _interpretar(saida: bytes, campos_pedidos: Sequence[str], maximo: int) -> Resultado:
    cabecalho, partes = ler_quadro(io.BytesIO(saida), maximo)
    if cabecalho.get("ok") is not True:
        codigo = cabecalho.get("codigo")
        raise Recusa(codigo if isinstance(codigo, str) and len(codigo) <= VALOR_MAXIMO else "processamento.falhou")
    formato, paginas, campos = cabecalho["formato"], cabecalho["paginas"], cabecalho["campos"]
    if formato not in ("pdf", "jpeg") or not isinstance(paginas, int) or paginas < 1 or len(partes) != 1:
        raise ValueError("resposta inválida")
    achados = []
    for campo in campos:
        nome, valor, confianca = campo["nome"], campo["valor"], campo["confianca"]
        if nome not in campos_pedidos or not isinstance(valor, str) or len(valor) > VALOR_MAXIMO:
            raise ValueError("campo inválido")
        achados.append(Campo(nome, valor, "alta" if confianca == "alta" else "baixa"))
    return Resultado(partes[0], formato, paginas, tuple(achados))


def executar(
    arquivos: Sequence[bytes],
    origem: str,
    campos: Sequence[str],
    limites: Limites,
    extrair: bool,
    tempo_maximo: float,
    memoria_mb: int = MEMORIA_MAXIMA_MB,
) -> Resultado:
    """Roda o processamento no filho. `Recusa` com o motivo, inclusive `processamento.tempo` se passar do tempo e
    `processamento.falhou` se o filho morrer ou responder fora do protocolo."""
    pedido = io.BytesIO()
    escrever_quadro(pedido, {"origem": origem, "campos": list(campos), "pixels": limites.pixels_por_pagina,
                             "paginas": limites.paginas, "extrair": extrair}, arquivos)  # fmt: skip
    try:
        concluido = subprocess.run(  # nosec B603
            [sys.executable, "-m", "sar.modulo_04_documentos.processo"],
            input=pedido.getvalue(), capture_output=True, timeout=tempo_maximo, check=False, env=_ambiente(),
            preexec_fn=_limitar(memoria_mb, int(tempo_maximo) + 1),  # só setrlimit, antes do exec
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        raise Recusa("processamento.tempo") from None
    if concluido.returncode != 0:
        raise Recusa("processamento.falhou")
    try:
        return _interpretar(concluido.stdout, campos, maximo=sum(len(a) for a in arquivos) * 4 + 50 * 1024 * 1024)
    except Recusa:
        raise
    except Exception:
        raise Recusa("processamento.falhou") from None
