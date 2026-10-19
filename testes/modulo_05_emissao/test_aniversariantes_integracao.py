"""Aniversariantes do dia na tela inicial, com o banco (RF-909, §10): só quem está em tratamento."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest
from sqlalchemy import Engine, text

from sar.modulo_02_cadastro.contrato import TipoEvento
from sar.modulo_05_emissao.relatorios import ServicoRelatorios
from sar.nucleo.contexto import Perfil
from sar.nucleo.erros import AcessoNegado
from testes.apoio.cadastro import dados_completos, montar, pessoa
from testes.apoio.fabrica import Fabrica

pytestmark = pytest.mark.integracao


@pytest.mark.requisito("RF-909")
def test_aniversariantes_em_tratamento_e_29_de_fevereiro_em_ano_comum(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    relatorios = ServicoRelatorios(cadastro.executar, cadastro.leitura)

    def criar(nascimento: date, inicio: date = date(2026, 1, 5)) -> str:
        dados = replace(dados_completos(fabrica), data_nascimento=nascimento)
        cadastro.pacientes.criar(recepcao, dados, inicio)
        return dados.nome or ""

    hoje = criar(date(1960, 10, 19))
    bissexto = criar(date(1964, 2, 29))
    criar(date(1970, 10, 20))  # amanhã
    criar(date(1955, 10, 19), inicio=date(2026, 11, 1))  # ainda não está em tratamento
    alta = criar(date(1950, 10, 19))
    with engine_web.connect() as c:
        pid = c.execute(text("SELECT id FROM paciente WHERE nome = :n"), {"n": alta}).scalar_one()
    cadastro.eventos.registrar(recepcao, pid, TipoEvento.ALTA, date(2026, 6, 1), None)

    assert relatorios.aniversariantes(recepcao, date(2026, 10, 19)) == [hoje]
    assert relatorios.aniversariantes(recepcao, date(2026, 2, 28)) == [bissexto]  # 2026 não é bissexto
    assert relatorios.aniversariantes(recepcao, date(2028, 2, 28)) == []  # em 2028 há o dia 29
    with pytest.raises(AcessoNegado):
        relatorios.aniversariantes(pessoa(cadastro_zerado, "ti", Perfil.TI), date(2026, 10, 19))
