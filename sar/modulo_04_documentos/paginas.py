"""As páginas de um documento reconstruído como imagem (DDS §8.6, SEG-19): sem reprocessar, a foto é o próprio JPEG;
no PDF/A reconstruído (SEG-10), cada página tem uma imagem DCT só, que é o JPEG da página."""

from __future__ import annotations

import io

import pikepdf

JPEG = "image/jpeg"


def formato_da_origem(origem: str) -> str:
    """O formato do documento reconstruído: a foto da webcam é JPEG; o resto, PDF/A."""
    return "jpeg" if origem == "webcam" else "pdf"


def paginas_jpeg(conteudo: bytes, formato: str) -> list[bytes]:
    if formato == "jpeg":
        return [conteudo]
    with pikepdf.open(io.BytesIO(conteudo)) as pdf:
        return [bytes(pagina.Resources.XObject.Im0.read_raw_bytes()) for pagina in pdf.pages]
