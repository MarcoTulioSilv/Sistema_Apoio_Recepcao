"""Isolamento do processamento (DD-35, SEG-30): a validação, a reconstrução e a extração rodam no processo filho do
núcleo (`sar.nucleo.subprocesso`), com tempo máximo e, no Linux, teto de memória e de CPU; se a decodificação
travar, estourar ou for explorada, o estrago fica no filho, que morre sem levar o worker. Aqui fica só o pedido do
processamento e a conferência da resposta, tratada como entrada não confiável.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sar.modulo_04_documentos.processamento import Campo, Limites, Recusa
from sar.nucleo.subprocesso import AMBIENTE_BASICO, FalhaDoFilho, TempoEsgotado, rodar

VALOR_MAXIMO = 60
MEMORIA_MAXIMA_MB = 1536
# Além do básico, o filho precisa achar o Tesseract (DD-40).
AMBIENTE_PERMITIDO = AMBIENTE_BASICO | {"SAR_TESSERACT", "TESSDATA_PREFIX"}


@dataclass(frozen=True, slots=True)
class Resultado:
    conteudo: bytes
    formato: str
    paginas: int
    campos: tuple[Campo, ...]


def _interpretar(cabecalho: dict[str, Any], partes: list[bytes], campos_pedidos: Sequence[str]) -> Resultado:
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
    pedido = {"origem": origem, "campos": list(campos), "pixels": limites.pixels_por_pagina,
              "paginas": limites.paginas, "extrair": extrair}  # fmt: skip
    try:
        cabecalho, partes = rodar(
            "sar.modulo_04_documentos.processo", pedido, arquivos, tempo_maximo, memoria_mb,
            maximo_resposta=sum(len(a) for a in arquivos) * 4 + 50 * 1024 * 1024, permitidos=AMBIENTE_PERMITIDO,
        )  # fmt: skip
        return _interpretar(cabecalho, partes, campos)
    except TempoEsgotado:
        raise Recusa("processamento.tempo") from None
    except Recusa:
        raise
    except FalhaDoFilho, ValueError, KeyError, TypeError:
        raise Recusa("processamento.falhou") from None
