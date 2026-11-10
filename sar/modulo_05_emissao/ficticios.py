"""Imagens fictícias da prévia (DD-42): a foto de um paciente que não existe e um logotipo provisório, para a
administração conferir o leiaute antes de ativar o modelo. Geradas na hora; nunca uma foto de verdade."""

from __future__ import annotations

import io
from functools import cache

from PIL import Image, ImageDraw


def _png(imagem: Image.Image) -> bytes:
    saida = io.BytesIO()
    imagem.save(saida, format="PNG")
    return saida.getvalue()


@cache
def foto() -> bytes:
    """Silhueta 3 × 4."""
    imagem = Image.new("RGB", (300, 400), "#c8d3df")
    desenho = ImageDraw.Draw(imagem)
    desenho.ellipse((95, 60, 205, 170), fill="#6b7d91")
    desenho.ellipse((40, 190, 260, 430), fill="#6b7d91")
    return _png(imagem)


@cache
def logotipo() -> bytes:
    """Quadro com a palavra LOGO, para quando a clínica ainda não enviou o logotipo (RF-1202)."""
    imagem = Image.new("RGB", (160, 160), "white")
    desenho = ImageDraw.Draw(imagem)
    desenho.rectangle((6, 6, 153, 153), outline="black", width=6)
    desenho.text((52, 72), "LOGO", fill="black")
    return _png(imagem)
