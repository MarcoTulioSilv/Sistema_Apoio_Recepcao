"""Processo filho isolado (DD-35, DD-50, SEG-30): o que decodifica arquivo não confiável roda num processo filho com
tempo máximo e, no Linux, com teto de memória e de CPU; se a decodificação travar, estourar ou for explorada, o
estrago fica no filho. Usado pelo processamento das ingestões (MOD-04) e pelo logotipo (MOD-06).

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
from collections.abc import Collection, Sequence
from typing import Any, BinaryIO

CABECALHO_MAXIMO = 64 * 1024
# O filho herda só o necessário para achar o Python; nada de credencial de banco ou chave (SEG-30).
AMBIENTE_BASICO = frozenset({"PATH", "SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP", "LANG", "LC_ALL", "VIRTUAL_ENV",
                             "PYTHONPATH"})  # fmt: skip


class FalhaDoFilho(Exception):
    """O filho morreu, terminou com erro ou não respondeu no protocolo; sem detalhe, que poderia trazer conteúdo."""


class TempoEsgotado(FalhaDoFilho):
    """O filho passou do tempo máximo e foi encerrado."""


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


def ambiente(permitidos: Collection[str] = AMBIENTE_BASICO) -> dict[str, str]:
    return {chave: valor for chave, valor in os.environ.items() if chave.upper() in permitidos}


def _limitar(memoria_mb: int, cpu_segundos: int) -> Any:
    """Teto de memória e de CPU do filho (só POSIX; no Windows vale o tempo máximo de parede)."""
    if sys.platform == "win32":
        return None

    def aplicar() -> None:
        import resource  # só existe no POSIX

        resource.setrlimit(resource.RLIMIT_AS, (memoria_mb * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_segundos, cpu_segundos))

    return aplicar


def rodar(
    modulo: str,
    cabecalho: dict[str, Any],
    partes: Sequence[bytes],
    tempo_maximo: float,
    memoria_mb: int,
    maximo_resposta: int,
    permitidos: Collection[str] = AMBIENTE_BASICO,
) -> tuple[dict[str, Any], list[bytes]]:
    """Roda `python -m <modulo>` com o pedido na entrada padrão e lê o quadro da resposta. `TempoEsgotado` se passar
    do tempo; `FalhaDoFilho` se o filho terminar com erro ou responder fora do enquadramento."""
    pedido = io.BytesIO()
    escrever_quadro(pedido, cabecalho, partes)
    try:
        # O módulo é fixo no código de quem chama; nunca vem de entrada.
        concluido = subprocess.run(  # noqa: S603 # nosec B603
            [sys.executable, "-m", modulo],
            input=pedido.getvalue(), capture_output=True, timeout=tempo_maximo, check=False,
            env=ambiente(permitidos), preexec_fn=_limitar(memoria_mb, int(tempo_maximo) + 1),
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        raise TempoEsgotado() from None
    if concluido.returncode != 0:
        raise FalhaDoFilho()
    try:
        return ler_quadro(io.BytesIO(concluido.stdout), maximo_resposta)
    except Exception:
        raise FalhaDoFilho() from None
