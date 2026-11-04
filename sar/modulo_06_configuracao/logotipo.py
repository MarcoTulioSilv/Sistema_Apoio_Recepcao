"""Logotipo da clínica (RF-1202, DD-50): o único arquivo de configuração, tratado como não confiável.

O pai confere o tamanho e a assinatura; a decodificação e o reencode rodam no processo filho do núcleo
(`python -m sar.modulo_06_configuracao.logotipo`), com tempo e memória limitados. Sai sempre um PNG novo, sem
nenhum metadado do arquivo enviado.
"""

from __future__ import annotations

import io
import sys
import warnings

from PIL import Image

from sar.nucleo.erros import RegraViolada
from sar.nucleo.subprocesso import FalhaDoFilho, TempoEsgotado, escrever_quadro, ler_quadro, rodar

BYTES_MAXIMO = 2 * 1024 * 1024
PIXELS_MAXIMO = 4_000_000
TEMPO_MAXIMO = 20.0
MEMORIA_MB = 512
ASSINATURAS = {"png": b"\x89PNG\r\n\x1a\n", "jpeg": b"\xff\xd8\xff"}
# Marcas de outro formato dentro do arquivo: poliglota ou contêiner disfarçado (mesmo critério do SEG-04).
OUTROS_FORMATOS = (b"PK\x03\x04", b"%PDF-", b"<svg", b"<SVG", b"MZ\x90\x00", b"Rar!\x1a\x07", b"7z\xbc\xaf\x27\x1c")


def conferir(arquivo: bytes) -> str:
    """O tipo pela assinatura, antes de qualquer decodificação; RegraViolada("logotipo.<motivo>")."""
    if not arquivo:
        raise RegraViolada("logotipo.vazio")
    if len(arquivo) > BYTES_MAXIMO:
        raise RegraViolada("logotipo.tamanho")
    for tipo, marca in ASSINATURAS.items():
        if arquivo.startswith(marca):
            if any(m in arquivo[len(marca) :] for m in OUTROS_FORMATOS):
                raise RegraViolada("logotipo.tipo")
            return tipo
    raise RegraViolada("logotipo.tipo")


def reencodar(arquivo: bytes) -> bytes:
    """Decodifica com limite de pixels e grava um PNG novo, com transparência, sem metadados. Roda no filho."""
    Image.MAX_IMAGE_PIXELS = PIXELS_MAXIMO
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        imagem = Image.open(io.BytesIO(arquivo), formats=["PNG", "JPEG"])  # nenhum outro decodificador
        largura, altura = imagem.size
        if largura * altura > PIXELS_MAXIMO:
            raise ValueError("pixels")
        imagem.load()
    limpa = Image.new("RGBA", imagem.size)
    limpa.paste(imagem.convert("RGBA"))
    saida = io.BytesIO()
    limpa.save(saida, format="PNG", optimize=True)
    return saida.getvalue()


def processar(arquivo: bytes) -> bytes:
    """Confere e reencoda no filho. RegraViolada("logotipo.<motivo>"): tipo, tamanho, invalido ou tempo."""
    conferir(arquivo)
    try:
        cabecalho, partes = rodar(
            "sar.modulo_06_configuracao.logotipo", {}, [arquivo], TEMPO_MAXIMO, MEMORIA_MB, BYTES_MAXIMO * 8
        )
    except TempoEsgotado:
        raise RegraViolada("logotipo.tempo") from None
    except FalhaDoFilho:
        raise RegraViolada("logotipo.invalido") from None
    if cabecalho.get("ok") is not True or len(partes) != 1 or not partes[0].startswith(ASSINATURAS["png"]):
        raise RegraViolada("logotipo.invalido")
    return partes[0]


def principal() -> int:
    """O filho: lê o arquivo, devolve o PNG ou só `ok: false`, sem detalhe (a mensagem poderia trazer conteúdo)."""
    saida = sys.stdout.buffer
    try:
        _, partes = ler_quadro(sys.stdin.buffer)
        escrever_quadro(saida, {"ok": True}, [reencodar(partes[0])])
    except Exception:
        escrever_quadro(saida, {"ok": False}, [])
    return 0


if __name__ == "__main__":
    sys.exit(principal())
