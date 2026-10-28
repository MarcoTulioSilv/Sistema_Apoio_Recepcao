"""Tokens de cor do tema (src/sar.css): o texto sobre cada fundo passa do nível AA (RNF-406, 4,5:1)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
TEMA = RAIZ / "sar" / "web" / "src" / "sar.css"
TEMA_GUIA = RAIZ / "docs" / "prototipo" / "src" / "sar.css"
FREQUENCIA = ("previstas", "realizadas", "ausencias", "reposicoes", "extras", "a-realizar")


def tokens(css: Path) -> dict[str, str]:
    return dict(re.findall(r"--color-([a-z-]+):\s*(#[0-9a-f]{6});", css.read_text(encoding="utf-8")))


def contraste(texto: str, fundo: str) -> float:
    def luminancia(cor: str) -> float:
        canais = [int(cor[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canais)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    claro, escuro = sorted((luminancia(texto), luminancia(fundo)), reverse=True)
    return (claro + 0.05) / (escuro + 0.05)


@pytest.mark.requisito("RNF-406", "RF-916")
@pytest.mark.parametrize("nome", FREQUENCIA)
def test_balanco_da_frequencia_legivel_sobre_a_cor_de_cada_cartao(nome: str) -> None:
    cores = tokens(TEMA)
    fundo = cores[f"freq-{nome}"]
    assert contraste(cores["suave"], fundo) >= 4.5  # rótulo
    assert contraste(cores["tinta"], fundo) >= 7  # número


def test_guia_usa_o_mesmo_tema_da_aplicacao() -> None:
    assert tokens(TEMA_GUIA) == tokens(TEMA)
