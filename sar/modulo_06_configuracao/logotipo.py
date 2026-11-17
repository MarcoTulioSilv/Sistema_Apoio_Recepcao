"""Logotipo da clínica (RF-1202, DD-50): o único arquivo de configuração, tratado como não confiável.

O pai confere o tamanho e a assinatura; a decodificação e o reencode rodam no processo filho do núcleo
(`python -m sar.modulo_06_configuracao.logotipo`), com tempo e memória limitados. Sai sempre um PNG novo, sem
nenhum metadado do arquivo enviado.
"""

from __future__ import annotations

import io
import sys
import warnings

from PIL import Image, ImageFile

from sar.nucleo.erros import RegraViolada
from sar.nucleo.subprocesso import FalhaDoFilho, TempoEsgotado, escrever_quadro, ler_quadro, rodar

BYTES_MAXIMO = 2 * 1024 * 1024
PIXELS_MAXIMO = 4_000_000
TEMPO_MAXIMO = 20.0
MEMORIA_MB = 512
ASSINATURAS = {"png": b"\x89PNG\r\n\x1a\n", "jpeg": b"\xff\xd8\xff"}
# Marcas de outro formato dentro do arquivo: poliglota ou contêiner disfarçado (mesmo critério do SEG-04).
OUTROS_FORMATOS = (b"PK\x03\x04", b"%PDF-", b"<svg", b"<SVG", b"MZ\x90\x00", b"Rar!\x1a\x07", b"7z\xbc\xaf\x27\x1c")


# DD-115: metadados que o reencode descarta não entram na busca de marcas. Uma credencial de conteúdo (C2PA) traz uma
# miniatura em SVG, e um XMP pode citar outro formato; nada disso chega ao PNG que o sistema grava.
METADADOS_PNG = frozenset({b"tEXt", b"iTXt", b"zTXt", b"eXIf", b"caBX"})  # texto, XMP, EXIF e C2PA
METADADOS_JPEG = frozenset({*range(0xE0, 0xF0), 0xFE})  # APP0 a APP15 (EXIF, XMP, ICC, C2PA) e comentário


def _partes_png(arquivo: bytes) -> list[bytes]:
    """Os blocos que contam, do cabeçalho ao IEND. Bloco que passa do fim é arquivo truncado; o que vem depois do IEND
    é conteúdo escondido, o truque do arquivo poliglota."""
    partes: list[bytes] = []
    i = len(ASSINATURAS["png"])
    while True:
        if i + 12 > len(arquivo):
            raise RegraViolada("logotipo.invalido")
        tamanho = int.from_bytes(arquivo[i : i + 4], "big")
        tipo = arquivo[i + 4 : i + 8]
        fim = i + 12 + tamanho
        if fim > len(arquivo):
            raise RegraViolada("logotipo.invalido")
        if tipo not in METADADOS_PNG:
            partes.append(arquivo[i + 4 : i + 8 + tamanho])
        i = fim
        if tipo == b"IEND":
            break
    if i != len(arquivo):
        raise RegraViolada("logotipo.outro_formato")
    return partes


def _partes_jpeg(arquivo: bytes) -> list[bytes]:
    """Os segmentos que contam até o início da imagem (SOS), que vai inteira, com o resto do arquivo: depois do fim da
    imagem pode haver uma segunda (MPF, das câmeras), e ela continua varrida."""
    partes: list[bytes] = []
    i = len(ASSINATURAS["jpeg"]) - 1  # o FF do primeiro segmento faz parte da assinatura
    while i + 4 <= len(arquivo) and arquivo[i] == 0xFF:
        marcador = arquivo[i + 1]
        if marcador == 0xFF:  # preenchimento entre segmentos
            i += 1
            continue
        if marcador == 0xDA:
            break
        fim = i + 2 + int.from_bytes(arquivo[i + 2 : i + 4], "big")
        if marcador not in METADADOS_JPEG:
            partes.append(arquivo[i:fim])
        i = fim
    partes.append(arquivo[i:])
    return partes


def conferir(arquivo: bytes) -> str:
    """O tipo pela assinatura, antes de qualquer decodificação; RegraViolada("logotipo.<motivo>"). Marca de outro
    formato fora dos metadados é "logotipo.outro_formato" (DD-115)."""
    if not arquivo:
        raise RegraViolada("logotipo.vazio")
    if len(arquivo) > BYTES_MAXIMO:
        raise RegraViolada("logotipo.tamanho")
    for tipo, marca in ASSINATURAS.items():
        if arquivo.startswith(marca):
            partes = _partes_png(arquivo) if tipo == "png" else _partes_jpeg(arquivo)
            if any(m in parte for parte in partes for m in OUTROS_FORMATOS):
                raise RegraViolada("logotipo.outro_formato")
            return tipo
    raise RegraViolada("logotipo.tipo")


def reencodar(arquivo: bytes) -> bytes:
    """Decodifica com limite de pixels e grava um PNG novo, com transparência, sem metadados. Roda no filho."""
    Image.MAX_IMAGE_PIXELS = PIXELS_MAXIMO
    ImageFile.LOAD_TRUNCATED_IMAGES = False  # o WeasyPrint liga ao ser importado; aqui, truncado é recusado
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
