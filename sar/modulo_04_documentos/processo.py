"""O processo filho do processamento (DD-35): `python -m sar.modulo_04_documentos.processo`.

Lê o pedido da entrada padrão e escreve a resposta na saída padrão, no enquadramento de `isolamento`; não abre
banco, rede nem arquivo de documento. Qualquer falha inesperada vira a recusa `processamento.falhou`, sem detalhe:
a mensagem de uma biblioteca poderia trazer conteúdo do arquivo (SEG-12).
"""

from __future__ import annotations

import sys

from sar.modulo_04_documentos.isolamento import escrever_quadro, ler_quadro
from sar.modulo_04_documentos.processamento import Limites, Recusa, processar


def principal() -> int:
    entrada, saida = sys.stdin.buffer, sys.stdout.buffer
    try:
        pedido, arquivos = ler_quadro(entrada)
        limites = Limites(pixels_por_pagina=int(pedido["pixels"]), paginas=int(pedido["paginas"]))
        feito = processar(arquivos, str(pedido["origem"]), list(pedido["campos"]), limites, bool(pedido["extrair"]))
    except Recusa as recusa:
        escrever_quadro(saida, {"ok": False, "codigo": recusa.codigo}, [])
        return 0
    except Exception:  # o pai só precisa saber que falhou
        escrever_quadro(saida, {"ok": False, "codigo": "processamento.falhou"}, [])
        return 0
    campos = [{"nome": c.nome, "valor": c.valor, "confianca": c.confianca} for c in feito.campos]
    escrever_quadro(saida, {"ok": True, "formato": feito.formato, "paginas": feito.paginas, "campos": campos},
                    [feito.conteudo])  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(principal())
