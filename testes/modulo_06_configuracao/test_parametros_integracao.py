"""Parâmetros no MySQL, pelo usuário de banco da web (DD-58)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import Engine, text

from sar.composicao import montar_barramento, montar_executor
from sar.modulo_01_acesso.servicos import ServicoAuditoria
from sar.modulo_06_configuracao.servicos import LeitorParametrosSQL, ServicoConfiguracao
from sar.modulo_08_dados.relogio import RelogioSistema
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado, RegraViolada
from sar.nucleo.parametros import PARAMETROS
from sar.nucleo.uow import UnidadeDeTrabalho
from testes.apoio.vazamento import ColetorLogs

pytestmark = pytest.mark.integracao

AGORA = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


@dataclass
class UsoFalso:
    parametro: str
    usado: bool

    def em_uso(self, uow: UnidadeDeTrabalho) -> bool:
        return self.usado


@pytest.fixture
def parametros_limpos(usuarios: dict[str, int], trilha_zerada: Engine) -> Iterator[dict[str, int]]:
    with trilha_zerada.begin() as c:
        c.execute(text("DELETE FROM parametro"))
    yield usuarios
    with trilha_zerada.begin() as c:
        c.execute(text("DELETE FROM parametro"))  # antes dos usuários, que ele referencia


def montar(engine: Engine, uso: UsoFalso | None = None) -> tuple[LeitorParametrosSQL, ServicoConfiguracao]:
    executar = montar_executor(engine, montar_barramento(RelogioSistema()))
    verificadores = {uso.parametro: uso} if uso else {}
    return LeitorParametrosSQL(executar), ServicoConfiguracao(executar, ServicoAuditoria(), verificadores)


def pessoa(usuarios: dict[str, int], chave: str, perfil: Perfil) -> Contexto:
    return Contexto(usuarios[chave], perfil, None, "10.0.0.9", AGORA, "d" * 32)


def auditorias(engine: Engine) -> list[tuple[object, ...]]:
    sql = "SELECT entidade_id, alteracoes FROM auditoria WHERE operacao = 'config.parametro.alterar' ORDER BY id"
    with engine.connect() as c:
        return [tuple(linha) for linha in c.execute(text(sql))]


@pytest.mark.requisito("DD-48", "DD-73")
def test_sem_valor_gravado_vale_o_padrao(parametros_limpos: dict[str, int], engine_web: Engine) -> None:
    leitor, _ = montar(engine_web)
    assert (leitor.valor("sessao_inatividade"), leitor.valor("extracao_ligada")) == (10, True)
    assert leitor.valor("data_implantacao") is None
    with pytest.raises(LookupError):
        leitor.valor("parametro_que_nao_existe")


@pytest.mark.requisito("DD-48", "RNF-605")
def test_administracao_altera_operacional_com_auditoria_de_antes_e_depois(
    parametros_limpos: dict[str, int], engine_web: Engine
) -> None:
    leitor, servico = montar(engine_web)
    admin = pessoa(parametros_limpos, "admin", Perfil.ADMINISTRACAO)
    servico.alterar_parametro(admin, "rascunho_prazo", 5)
    assert leitor.valor("rascunho_prazo") == 5
    servico.alterar_parametro(admin, "rascunho_prazo", 5)  # igual: não grava nem audita de novo
    assert auditorias(engine_web) == [("rascunho_prazo", '{"valor":[3,5]}')]


@pytest.mark.requisito("DD-48", "CT-ACE-01")
def test_cada_perfil_so_altera_os_seus_parametros(parametros_limpos: dict[str, int], engine_web: Engine) -> None:
    leitor, servico = montar(engine_web)
    admin = pessoa(parametros_limpos, "admin", Perfil.ADMINISTRACAO)
    ti = pessoa(parametros_limpos, "ti", Perfil.TI)
    with pytest.raises(AcessoNegado):
        servico.alterar_parametro(admin, "sessao_inatividade", 15)  # técnico
    with pytest.raises(AcessoNegado):
        servico.alterar_parametro(ti, "rascunho_prazo", 5)  # operacional
    with pytest.raises(AcessoNegado):
        servico.alterar_parametro(pessoa(parametros_limpos, "recepcao", Perfil.RECEPCAO), "rascunho_prazo", 5)
    servico.alterar_parametro(ti, "sessao_inatividade", 15)
    assert leitor.valor("sessao_inatividade") == 15


@pytest.mark.requisito("DD-48")
def test_valor_fora_dos_limites_nao_e_gravado(parametros_limpos: dict[str, int], engine_web: Engine) -> None:
    leitor, servico = montar(engine_web)
    with pytest.raises(RegraViolada):
        servico.alterar_parametro(pessoa(parametros_limpos, "ti", Perfil.TI), "sessao_inatividade", 0)
    assert leitor.valor("sessao_inatividade") == 10
    assert auditorias(engine_web) == []


@pytest.mark.requisito("DD-48", "DD-81")
def test_valor_invalido_gravado_no_banco_volta_ao_padrao_com_aviso(
    parametros_limpos: dict[str, int], engine_web: Engine, trilha_zerada: Engine
) -> None:
    with trilha_zerada.begin() as c:
        c.execute(
            text("INSERT INTO parametro VALUES ('sessao_inatividade', '0', NOW(6), :u)"),
            {"u": parametros_limpos["ti"]},
        )
    leitor, _ = montar(engine_web)
    coletor = ColetorLogs()
    logging.getLogger("sar").addHandler(coletor)
    try:
        assert leitor.valor("sessao_inatividade") == 10  # inatividade de zero minuto nunca vale
    finally:
        logging.getLogger("sar").removeHandler(coletor)
    assert any('"evento":"config.parametro.valor_invalido"' in linha for linha in coletor.linhas)


@pytest.mark.requisito("DD-51")
def test_data_de_implantacao_trava_depois_do_uso(parametros_limpos: dict[str, int], engine_web: Engine) -> None:
    ti = pessoa(parametros_limpos, "ti", Perfil.TI)
    uso = UsoFalso("data_implantacao", usado=False)
    leitor, servico = montar(engine_web, uso)
    servico.alterar_parametro(ti, "data_implantacao", date(2026, 11, 3))
    servico.alterar_parametro(ti, "data_implantacao", date(2026, 11, 4))  # antes do uso, ainda muda
    uso.usado = True
    with pytest.raises(RegraViolada) as erro:
        servico.alterar_parametro(ti, "data_implantacao", date(2026, 11, 5))
    assert erro.value.codigo == "parametro.imutavel"
    assert leitor.valor("data_implantacao") == date(2026, 11, 4)


@pytest.mark.requisito("DD-48")
def test_todos_os_perfis_listam_os_parametros_vigentes(parametros_limpos: dict[str, int], engine_web: Engine) -> None:
    _, servico = montar(engine_web)
    servico.alterar_parametro(pessoa(parametros_limpos, "admin", Perfil.ADMINISTRACAO), "titular_prazo", 10)
    lista = servico.listar_parametros(pessoa(parametros_limpos, "recepcao", Perfil.RECEPCAO))
    assert [p.nome for p in lista] == sorted(PARAMETROS)
    titular = next(p for p in lista if p.nome == "titular_prazo")
    assert (titular.valor, titular.padrao, titular.maximo) == (10, 15, 15)
    assert titular.alterado_por == parametros_limpos["admin"]
