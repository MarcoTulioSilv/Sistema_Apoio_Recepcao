"""BMP do driver → PNG, em memória (DD-77): o driver ignora o formato pedido e entrega BMP de quase 9 MB por página;
em PNG fica entre 0,7 e 4 MB, sem perda. A página continua em tons de cinza (DD-78)."""

from __future__ import annotations

import io

from PIL import Image


class PaginaInvalida(Exception):
    """O driver devolveu algo que não abre como imagem."""


def bmp_para_png(bmp: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(bmp)) as imagem:
            cinza = imagem if imagem.mode == "L" else imagem.convert("L")
            saida = io.BytesIO()
            cinza.save(saida, format="PNG", optimize=False)
    except Exception:
        raise PaginaInvalida() from None
    return saida.getvalue()
