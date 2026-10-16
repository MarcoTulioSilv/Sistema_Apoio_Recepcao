"""Bibliotecas de interface servidas pelo próprio SAR, com versão fixa (AD-06, AD-04)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

ESTATICOS = Path(__file__).resolve().parents[2] / "sar" / "web" / "static"

# SHA-256 do htmx.min.js do pacote htmx.org@4.0.0 do npm, cujo tarball confere com o integrity publicado
# (sha512-T/171FUY93Kdfp8t+DnHdk45QvKRiBhVhhrwSzrXgUi4pHKvhp77dUA/qg8FAjsFWPIHNbmUuIdCrcVHuiZWng==).
HTMX = ("js/htmx-4.0.0.min.js", "e484d9171a9db30a39c8f16e3d709d4137f3211c659f8e6125816635033d593f")


@pytest.mark.requisito("RNF-611")
def test_htmx_servido_localmente_e_identico_ao_publicado() -> None:
    caminho, esperado = HTMX
    assert hashlib.sha256((ESTATICOS / caminho).read_bytes()).hexdigest() == esperado
    assert (ESTATICOS / "js" / "LICENSE-htmx.txt").is_file()
