"""Os contratos de fachada do `.importlinter` cobrem o módulo inteiro, não uma lista de nomes (DD-16, DDS §3.12)."""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest

CONFIGURACAO = Path(__file__).resolve().parents[1] / ".importlinter"


@pytest.mark.requisito("DD-16")
def test_fora_de_cada_modulo_so_o_contrato_pode_ser_importado() -> None:
    ini = configparser.ConfigParser()
    ini.read(CONFIGURACAO, encoding="utf-8")
    fachadas = [s for s in ini.sections() if s.startswith("importlinter:contract:contrato_")]
    assert len(fachadas) == 10
    for secao in fachadas:
        modulo = ini[secao]["name"].split("só ")[1].removesuffix(".contrato pode ser importado")
        # Antes, só servicos, regras e executores eram proibidos: pendencias.py ou cep.py ficavam abertos.
        assert ini[secao]["forbidden_modules"].split() == [f"{modulo}.*"], secao
        assert ini[secao]["ignore_imports"].split() == ["**", "->", f"{modulo}.contrato"], secao
