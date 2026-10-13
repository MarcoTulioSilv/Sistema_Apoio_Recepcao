"""Convênios e municípios no MySQL, pelo usuário de banco da web (RF-1204, RF-1205, DD-49)."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, text

from sar.composicao import montar_barramento, montar_executor
from sar.modulo_01_acesso.servicos import ServicoAuditoria
from sar.modulo_06_configuracao.servicos import ServicoConfiguracao, ServicoReferencias
from sar.modulo_08_dados.relogio import RelogioSistema
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado, NaoEncontrado, RegraViolada
from sar.nucleo.uow import ExecutorDeOperacao

pytestmark = pytest.mark.integracao

AGORA = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


@pytest.fixture
def convenios_limpos(usuarios: dict[str, int], trilha_zerada: Engine) -> Iterator[dict[str, int]]:
    with trilha_zerada.begin() as c:
        c.execute(text("DELETE FROM convenio"))
    yield usuarios
    with trilha_zerada.begin() as c:
        c.execute(text("DELETE FROM convenio"))


def montar(engine: Engine) -> tuple[ExecutorDeOperacao, ServicoConfiguracao]:
    executar = montar_executor(engine, montar_barramento(RelogioSistema()))
    return executar, ServicoConfiguracao(executar, ServicoAuditoria())


def pessoa(usuarios: dict[str, int], chave: str, perfil: Perfil) -> Contexto:
    return Contexto(usuarios[chave], perfil, None, "10.0.0.9", AGORA, "e" * 32)


def auditorias(engine: Engine) -> list[tuple[object, ...]]:
    sql = "SELECT entidade_id, alteracoes FROM auditoria WHERE operacao = 'config.convenio.gerir' ORDER BY id"
    with engine.connect() as c:
        return [tuple(linha) for linha in c.execute(text(sql))]


@pytest.mark.requisito("RF-1204", "RNF-605")
def test_administracao_inclui_renomeia_inativa_e_reativa_com_auditoria(
    convenios_limpos: dict[str, int], engine_web: Engine
) -> None:
    _, servico = montar(engine_web)
    admin = pessoa(convenios_limpos, "admin", Perfil.ADMINISTRACAO)
    cid = servico.incluir_convenio(admin, "  Unimed   Jataí ")
    servico.renomear_convenio(admin, cid, "Unimed Jataí")  # igual: não grava nem audita (DD-10)
    servico.renomear_convenio(admin, cid, "Unimed Rio Verde")
    servico.inativar_convenio(admin, cid)
    servico.inativar_convenio(admin, cid)  # já inativo: nada muda
    servico.reativar_convenio(admin, cid)
    assert auditorias(engine_web) == [
        (str(cid), '{"ativo":[null,true],"nome":[null,"Unimed Jataí"]}'),
        (str(cid), '{"nome":["Unimed Jataí","Unimed Rio Verde"]}'),
        (str(cid), '{"ativo":[true,false]}'),
        (str(cid), '{"ativo":[false,true]}'),
    ]
    assert [(c.nome, c.ativo) for c in servico.listar_convenios(admin)] == [("Unimed Rio Verde", True)]


@pytest.mark.requisito("RF-1204")
def test_nome_repetido_sem_distincao_de_caixa_e_acento_e_recusado(
    convenios_limpos: dict[str, int], engine_web: Engine
) -> None:
    _, servico = montar(engine_web)
    admin = pessoa(convenios_limpos, "admin", Perfil.ADMINISTRACAO)
    cid = servico.incluir_convenio(admin, "Saúde Caixa")
    outro = servico.incluir_convenio(admin, "Ipasgo")
    for repetido in ("saude caixa", "SAÚDE CAIXA"):
        with pytest.raises(RegraViolada) as erro:
            servico.incluir_convenio(admin, repetido)
        assert erro.value.codigo == "convenio.nome_repetido"
    with pytest.raises(RegraViolada):
        servico.renomear_convenio(admin, outro, "Saude Caixa")
    servico.renomear_convenio(admin, cid, "SAÚDE CAIXA")  # o próprio, só com outra caixa: permitido
    assert {c.nome for c in servico.listar_convenios(admin)} == {"SAÚDE CAIXA", "Ipasgo"}


@pytest.mark.requisito("RF-1204")
def test_inclusoes_simultaneas_do_mesmo_nome_gravam_uma_so(
    convenios_limpos: dict[str, int], engine_web: Engine
) -> None:
    _, servico = montar(engine_web)
    admin = pessoa(convenios_limpos, "admin", Perfil.ADMINISTRACAO)

    def incluir(_: int) -> str:
        try:
            servico.incluir_convenio(admin, "Bradesco Saúde")
        except RegraViolada as erro:
            return erro.codigo
        return "ok"

    with ThreadPoolExecutor(4) as grupo:
        resultados = sorted(grupo.map(incluir, range(4)))
    assert resultados == ["convenio.nome_repetido"] * 3 + ["ok"]


@pytest.mark.requisito("RF-1204", "CT-ACE-01")
def test_so_a_administracao_gere_convenios_e_todos_consultam(
    convenios_limpos: dict[str, int], engine_web: Engine
) -> None:
    _, servico = montar(engine_web)
    admin = pessoa(convenios_limpos, "admin", Perfil.ADMINISTRACAO)
    cid = servico.incluir_convenio(admin, "Ipasgo")
    for chave, perfil in (("recepcao", Perfil.RECEPCAO), ("ti", Perfil.TI)):
        contexto = pessoa(convenios_limpos, chave, perfil)
        with pytest.raises(AcessoNegado):
            servico.incluir_convenio(contexto, "Outro")
        with pytest.raises(AcessoNegado):
            servico.inativar_convenio(contexto, cid)
        assert [c.nome for c in servico.listar_convenios(contexto)] == ["Ipasgo"]
    with pytest.raises(NaoEncontrado):
        servico.inativar_convenio(admin, cid + 1000)


@pytest.mark.requisito("RF-302", "DD-49")
def test_referencias_oferecem_so_os_ativos_e_acham_o_inativado_pelo_id(
    convenios_limpos: dict[str, int], engine_web: Engine
) -> None:
    executar, servico = montar(engine_web)
    admin = pessoa(convenios_limpos, "admin", Perfil.ADMINISTRACAO)
    ativo = servico.incluir_convenio(admin, "Ipasgo")
    inativo = servico.incluir_convenio(admin, "Amil")
    servico.inativar_convenio(admin, inativo)
    referencias = ServicoReferencias()
    assert [c.id for c in executar(referencias.convenios_ativos)] == [ativo]
    antigo = executar(lambda uow: referencias.convenio(uow, inativo))
    assert antigo is not None and (antigo.nome, antigo.ativo) == ("Amil", False)


@pytest.mark.requisito("RF-1205")
def test_busca_de_municipio_sem_acento_e_por_uf(usuarios: dict[str, int], engine_web: Engine) -> None:
    executar, servico = montar(engine_web)
    recepcao = pessoa(usuarios, "recepcao", Perfil.RECEPCAO)
    assert [(m.nome, m.uf) for m in servico.buscar_municipios(recepcao, "jatai", "go")] == [("Jataí", "GO")]
    goiania = servico.buscar_municipios(recepcao, "GOIANIA", "GO")
    assert [m.nome for m in goiania] == ["Goiânia"] and goiania[0].codigo == "5208707"
    assert len(servico.buscar_municipios(recepcao, "sa")) == 20  # limite
    assert servico.buscar_municipios(recepcao, "%") == []  # curinga não vale como curinga
    assert servico.buscar_municipios(recepcao, "j") == []
    with pytest.raises(RegraViolada):
        servico.buscar_municipios(recepcao, "jatai", "XX")
    jatai = executar(lambda uow: ServicoReferencias().municipio(uow, "5211909"))
    assert jatai is not None and (jatai.nome, jatai.uf) == ("Jataí", "GO")
    assert executar(lambda uow: ServicoReferencias().municipio(uow, "0000000")) is None
