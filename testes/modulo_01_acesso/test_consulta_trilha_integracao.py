"""Consulta da trilha de auditoria no MySQL (RNF-625, DD-10, §3.7)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import Engine, text

from sar.composicao import montar_barramento, montar_executor
from sar.modulo_01_acesso.contrato import FiltroConsulta
from sar.modulo_01_acesso.servicos import ServicoAuditoria
from sar.modulo_08_dados.relogio import RelogioSistema
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado
from sar.nucleo.uow import UnidadeDeTrabalho

pytestmark = pytest.mark.integracao

# 02:30 UTC de 08/10 = 23:30 de 07/10 em Jataí: a data local é 07/10.
VIRADA = datetime(2026, 10, 8, 2, 30, tzinfo=UTC)


def gravar(engine: Engine, contexto: Contexto, entidade: str, quantidade: int = 1) -> None:
    executar = montar_executor(engine, montar_barramento(RelogioSistema()))
    for i in range(quantidade):

        def operacao(uow: UnidadeDeTrabalho, i: int = i) -> None:
            ServicoAuditoria().registrar(
                uow, contexto, f"teste.{entidade}", entidade, str(100 + i), {"nome": ("A", "B")}, "motivo do teste"
            )

        executar(operacao)


def servico(engine: Engine) -> ServicoAuditoria:
    return ServicoAuditoria(montar_executor(engine, montar_barramento(RelogioSistema())))


def pessoa(usuarios: dict[str, int], chave: str, perfil: Perfil) -> Contexto:
    return Contexto(usuarios[chave], perfil, None, "10.0.0.9", VIRADA, "b" * 32)


@pytest.mark.requisito("RF-1006", "RNF-625")
def test_administracao_ve_tudo_e_o_ti_ve_pseudonimizado(usuarios: dict[str, int], engine_web: Engine) -> None:
    autor = pessoa(usuarios, "recepcao", Perfil.RECEPCAO)
    gravar(engine_web, autor, "paciente")
    gravar(engine_web, autor, "usuario")
    filtro = FiltroConsulta(operacao="teste.")

    completa = servico(engine_web).consultar(pessoa(usuarios, "admin", Perfil.ADMINISTRACAO), filtro).registros
    assert [(r.entidade, r.pseudonimizado, r.motivo) for r in completa] == [
        ("usuario", False, "motivo do teste"),
        ("paciente", False, "motivo do teste"),
    ]
    assert completa[1].alteracoes == '{"nome":["A","B"]}'
    assert completa[1].usuario_nome == "Usuário de teste"

    do_ti = servico(engine_web).consultar(pessoa(usuarios, "ti", Perfil.TI), filtro).registros
    paciente = next(r for r in do_ti if r.entidade == "paciente")
    assert (paciente.pseudonimizado, paciente.alteracoes, paciente.motivo) == (True, None, None)
    assert paciente.entidade_id == "100"  # o identificador interno continua (RNF-625)
    tecnico = next(r for r in do_ti if r.entidade == "usuario")
    assert tecnico.alteracoes is not None  # entidade técnica: o TI vê

    with pytest.raises(AcessoNegado):
        servico(engine_web).consultar(autor, filtro)


@pytest.mark.requisito("RNF-625", "DD-10")
def test_a_consulta_fica_na_trilha_com_a_quantidade_e_os_filtros(usuarios: dict[str, int], engine_web: Engine) -> None:
    gravar(engine_web, pessoa(usuarios, "recepcao", Perfil.RECEPCAO), "paciente", 3)
    servico(engine_web).consultar(pessoa(usuarios, "admin", Perfil.ADMINISTRACAO), FiltroConsulta(entidade="paciente"))
    with engine_web.connect() as c:
        alteracoes = c.execute(
            text("SELECT alteracoes FROM auditoria WHERE operacao = 'acesso.auditoria.consultar'")
        ).scalar_one()
    assert '"resultados":[null,3]' in alteracoes and '"entidade":"paciente"' in alteracoes


@pytest.mark.requisito("DDS-3.7")
def test_filtro_de_datas_usa_o_dia_local_da_clinica(usuarios: dict[str, int], engine_web: Engine) -> None:
    gravar(engine_web, pessoa(usuarios, "recepcao", Perfil.RECEPCAO), "paciente")  # instante: VIRADA
    admin = pessoa(usuarios, "admin", Perfil.ADMINISTRACAO)

    def achados(de: date, ate: date) -> int:
        filtro = FiltroConsulta(de=de, ate=ate, operacao="teste.")
        return len(servico(engine_web).consultar(admin, filtro).registros)

    assert achados(date(2026, 10, 7), date(2026, 10, 7)) == 1
    assert achados(date(2026, 10, 8), date(2026, 10, 8)) == 0


@pytest.mark.requisito("RF-1006")
def test_paginacao_do_mais_novo_para_o_mais_antigo(usuarios: dict[str, int], engine_web: Engine) -> None:
    gravar(engine_web, pessoa(usuarios, "recepcao", Perfil.RECEPCAO), "paciente", 105)
    admin = pessoa(usuarios, "admin", Perfil.ADMINISTRACAO)
    primeira = servico(engine_web).consultar(admin, FiltroConsulta(operacao="teste."))
    assert len(primeira.registros) == 100 and primeira.proximo_antes_de_id is not None
    ids = [r.id for r in primeira.registros]
    assert ids == sorted(ids, reverse=True)
    segunda = servico(engine_web).consultar(
        admin, FiltroConsulta(operacao="teste.", antes_de_id=primeira.proximo_antes_de_id)
    )
    assert len(segunda.registros) == 5 and segunda.proximo_antes_de_id is None
    assert max(r.id for r in segunda.registros) < min(ids)
