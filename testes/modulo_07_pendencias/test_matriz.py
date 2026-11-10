"""DD-55: a matriz de pendências do código é a da ERS §3.2.13 e a do DDS §11.1, linha a linha."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sar.modulo_07_pendencias.matriz import MATRIZ, visiveis
from sar.nucleo.contexto import Perfil
from sar.nucleo.portas import Prioridade

DOCS = Path(__file__).resolve().parents[2] / "docs"
COLUNAS = (Perfil.RECEPCAO, Perfil.ADMINISTRACAO, Perfil.VISUALIZADOR, Perfil.TI, Perfil.ENFERMAGEM)
LETRAS = {"R": Perfil.RECEPCAO, "A": Perfil.ADMINISTRACAO, "V": Perfil.VISUALIZADOR, "T": Perfil.TI,
          "E": Perfil.ENFERMAGEM}  # fmt: skip


def _linhas_da_tabela(texto: str, inicio: str, fim: str) -> list[list[str]]:
    secao = texto[texto.index(inicio) : texto.index(fim, texto.index(inicio))]
    linhas = []
    for bruta in secao.splitlines():
        if not bruta.startswith("|") or set(bruta.replace("|", "").strip()) <= {"-", " "}:
            continue
        linhas.append([c.strip() for c in bruta.strip().strip("|").split("|")])
    return linhas[1:]  # sem o cabeçalho


def matriz_da_ers() -> list[frozenset[Perfil]]:
    texto = (DOCS / "fase3-ers-v1_0.md").read_text(encoding="utf-8")
    linhas = _linhas_da_tabela(texto, "#### 3.2.13", "### 3.3")
    return [frozenset(p for p, c in zip(COLUNAS, linha[1:6], strict=True) if c.startswith("✓")) for linha in linhas]


def matriz_do_dds() -> list[tuple[int, frozenset[Perfil], str]]:
    texto = (DOCS / "DDS_recepcao-v1_1.md").read_text(encoding="utf-8")
    saida = []
    for linha in _linhas_da_tabela(texto, "### 11.1 Catálogo de pendências", "### 11.2"):
        if linha[3] == "—":
            continue  # linha 20, retirada pela DEC-74
        perfis = frozenset(LETRAS[letra] for letra in re.findall(r"\b([RAVTE])\b", linha[3]))
        saida.append((int(linha[0]), perfis, linha[4]))
    return saida


@pytest.mark.requisito("DD-55", "RF-1010", "CT-PEN-01")
def test_matriz_do_codigo_e_a_da_ers() -> None:
    da_ers = matriz_da_ers()
    assert len(da_ers) == 19  # o parser leu a tabela inteira
    assert [linha.perfis for linha in MATRIZ] == da_ers


@pytest.mark.requisito("DD-55", "CT-PEN-01")
def test_matriz_do_codigo_e_a_do_dds() -> None:
    do_dds = matriz_do_dds()
    assert [(linha.numero, linha.perfis) for linha in MATRIZ] == [(n, p) for n, p, _ in do_dds]
    for linha, (_, _, prioridade) in zip(MATRIZ, do_dds, strict=True):
        assert prioridade.startswith(linha.prioridade.value), linha.codigo
        assert linha.variavel == (";" in prioridade), linha.codigo  # "A; U a 3 dias do prazo"


@pytest.mark.requisito("DD-55")
def test_codigos_e_numeros_unicos() -> None:
    assert len({linha.codigo for linha in MATRIZ}) == len({linha.numero for linha in MATRIZ}) == len(MATRIZ)
    assert 20 not in {linha.numero for linha in MATRIZ}  # DEC-74: o número não é reaproveitado


@pytest.mark.requisito("RF-1004", "RNF-625", "CT-ACE-02")
def test_ti_so_ve_linhas_sem_paciente_ou_com_identificador() -> None:
    """§11.2: 12, 15, 17, 18 e 19 mostram ao TI só identificadores internos."""
    assert {linha.numero for linha in visiveis(Perfil.TI)} == {12, 15, 17, 18, 19}
    assert not visiveis(Perfil.SISTEMA)


@pytest.mark.requisito("DD-55")
def test_prioridades_validas() -> None:
    assert all(isinstance(linha.prioridade, Prioridade) for linha in MATRIZ)
    assert [linha.numero for linha in MATRIZ if linha.variavel] == [10]
