"""Leitura das planilhas sintéticas (PT §5.3) pelo extrator, sem banco."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from sar.modulo_10_carga import extrator, regras
from sar.nucleo.erros import RegraViolada
from testes.apoio import planilhas
from testes.apoio.fabrica import Fabrica


@pytest.mark.requisito("RF-1101", "RF-1102", "RF-1103", "AD-22", "ND-56")
def test_le_as_tres_planilhas_inteiras(fabrica: Fabrica, tmp_path: Path) -> None:
    sinteticas = planilhas.gerar(fabrica)
    lidas = extrator.ler(sinteticas.gravar(tmp_path))
    assert len(lidas.p1) == len(sinteticas.fichas)
    assert [b.numero_linha for b in lidas.p1] == [f.linha for f in sinteticas.fichas]
    assert len(lidas.p4) == sinteticas.linhas_p4  # o "2009" solto e o cabeçalho não contam
    assert len(lidas.p3) == sinteticas.linhas_p3  # anos, sentinelas e linhas vazias não contam
    assert {linha.ano for linha in lidas.p3} == {2018, 2019, 2024}


@pytest.mark.requisito("RNF-103", "DD-114", "CT-MIG-01")
def test_cada_defeito_cai_onde_deve_no_planejamento(fabrica: Fabrica, tmp_path: Path) -> None:
    sinteticas = planilhas.gerar(fabrica)
    lidas = extrator.ler(sinteticas.gravar(tmp_path))
    plano = regras.planejar(lidas.p1, lidas.p4, lidas.p3, date(2026, 11, 11))
    for ficha, item in zip(sinteticas.fichas, plano.itens, strict=True):
        esperado, _ = planilhas.DEFEITOS.get(ficha.defeito or "", (planilhas.IMPORTADO, ()))
        if esperado in ("p1.rotulo_desconhecido", "P-03.minimo", "evento_saida"):  # as que a planilha já decide
            assert item.excecao == esperado, ficha.defeito
    assert plano.contagens_p4["sem_prontuario"] == 1
    assert plano.contagens_p3["casadas"] == sinteticas.casadas_p3
    assert plano.cid_descartados >= 1


def test_planilha_ausente_e_recusada_sem_dizer_o_conteudo(tmp_path: Path) -> None:
    with pytest.raises(RegraViolada) as erro:
        extrator.ler(tmp_path)
    assert (erro.value.codigo, erro.value.detalhe) == ("carga.planilha_ausente", {"planilha": "p1"})


def test_arquivo_que_nao_e_planilha_e_recusado(fabrica: Fabrica, tmp_path: Path) -> None:
    planilhas.gerar(fabrica).gravar(tmp_path)
    (tmp_path / extrator.ARQUIVOS["p4"]).write_bytes(b"isto nao e um xlsx")
    with pytest.raises(RegraViolada) as erro:
        extrator.ler(tmp_path)
    assert erro.value.codigo == "carga.planilha_ilegivel"
