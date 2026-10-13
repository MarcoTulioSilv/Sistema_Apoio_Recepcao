"""Contatos e telefones no MySQL: CT-CAD-05 (INV-12), RF-201, RF-202."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from sar.modulo_02_cadastro.contrato import TipoTelefone
from sar.modulo_08_dados.erros_banco import restricao_violada
from sar.nucleo.contexto import Perfil
from sar.nucleo.erros import AcessoNegado, NaoEncontrado, RegraViolada
from testes.apoio.cadastro import INICIO, Cadastro, dados_completos, montar, pessoa
from testes.apoio.fabrica import Fabrica

pytestmark = pytest.mark.integracao

CELULAR = TipoTelefone.CELULAR


def auditorias(engine: Engine, entidade: str) -> list[tuple[str, str]]:
    sql = "SELECT entidade_id, alteracoes FROM auditoria WHERE entidade = :e ORDER BY id"
    with engine.connect() as c:
        return [(str(a), str(b)) for a, b in c.execute(text(sql), {"e": entidade})]


def novo_paciente(cadastro: Cadastro, usuarios: dict[str, int], fabrica: Fabrica) -> int:
    return cadastro.pacientes.criar(pessoa(usuarios), dados_completos(fabrica), INICIO)


@pytest.mark.requisito("CT-CAD-05", "INV-12", "RF-201", "RF-202")
def test_telefone_tem_um_dono_so_e_o_do_contato_nao_vai_para_o_paciente(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    pid = novo_paciente(cadastro, cadastro_zerado, fabrica)
    contato = cadastro.contatos.incluir_contato(recepcao, pid, fabrica.nome(), " filha ")
    do_paciente = cadastro.contatos.incluir_telefone(recepcao, pid, "64", "99999-0001", CELULAR)
    do_contato = cadastro.contatos.incluir_telefone(recepcao, pid, "(64)", "3631-0002", TipoTelefone.FIXO, contato)
    ficha = cadastro.pacientes.ver_ficha(recepcao, pid)
    assert [t.id for t in ficha.telefones] == [do_paciente]
    [ficha_contato] = ficha.contatos
    assert (ficha_contato.parentesco, [t.id for t in ficha_contato.telefones]) == ("filha", [do_contato])
    with engine_web.connect() as c:
        donos = c.execute(text("SELECT id, paciente_id, contato_id FROM telefone ORDER BY id")).all()
    assert [tuple(d) for d in donos] == [(do_paciente, pid, None), (do_contato, None, contato)]


@pytest.mark.requisito("CT-CAD-05", "INV-12")
@pytest.mark.parametrize("donos", ["NULL, NULL", ":p, :c"])
def test_banco_recusa_telefone_sem_dono_ou_com_dois(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica, donos: str
) -> None:
    cadastro = montar(engine_web)
    pid = novo_paciente(cadastro, cadastro_zerado, fabrica)
    contato = cadastro.contatos.incluir_contato(pessoa(cadastro_zerado), pid, fabrica.nome(), None)
    colunas = "paciente_id, contato_id, ddd, numero, tipo"
    sql = f"INSERT INTO telefone ({colunas}) VALUES ({donos}, '64', '999990000', 'celular')"  # noqa: S608
    with pytest.raises(DBAPIError) as erro, engine_web.begin() as c:
        c.execute(text(sql), {"p": pid, "c": contato})
    assert restricao_violada(erro.value) == "ck_telefone__um_dono"


@pytest.mark.requisito("CT-CAD-05", "INV-12")
def test_contato_de_outro_paciente_nao_recebe_telefone(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    pid, outro = novo_paciente(cadastro, cadastro_zerado, fabrica), novo_paciente(cadastro, cadastro_zerado, fabrica)
    contato_do_outro = cadastro.contatos.incluir_contato(recepcao, outro, fabrica.nome(), None)
    with pytest.raises(NaoEncontrado):
        cadastro.contatos.incluir_telefone(recepcao, pid, "64", "99999-0001", CELULAR, contato_do_outro)
    assert cadastro.pacientes.ver_ficha(recepcao, pid).telefones == ()


@pytest.mark.requisito("RF-202", "RNF-605")
def test_alterar_e_remover_telefone_com_auditoria_e_sem_repetir_numero(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    pid = novo_paciente(cadastro, cadastro_zerado, fabrica)
    tid = cadastro.contatos.incluir_telefone(recepcao, pid, "64", "99999-0001", CELULAR)
    with pytest.raises(RegraViolada) as erro:
        cadastro.contatos.incluir_telefone(recepcao, pid, "64", "999990001", TipoTelefone.RECADO)
    assert erro.value.codigo == "telefone.repetido"
    cadastro.contatos.alterar_telefone(recepcao, tid, "64", "99999-0001", CELULAR)  # igual: nada é auditado
    cadastro.contatos.alterar_telefone(recepcao, tid, "64", "99999-0001", TipoTelefone.RECADO)
    cadastro.contatos.remover_telefone(recepcao, tid)
    assert cadastro.pacientes.ver_ficha(recepcao, pid).telefones == ()
    assert [a for _, a in auditorias(engine_web, "telefone")] == [
        '{"ddd":[null,"64"],"numero":[null,"999990001"],"paciente_id":[null,PID],"tipo":[null,"celular"]}'.replace(
            "PID", str(pid)
        ),
        '{"tipo":["celular","recado"]}',
        '{"ddd":["64",null],"numero":["999990001",null],"paciente_id":[PID,null],"tipo":["recado",null]}'.replace(
            "PID", str(pid)
        ),
    ]
    with pytest.raises(NaoEncontrado):
        cadastro.contatos.remover_telefone(recepcao, tid)


@pytest.mark.requisito("RF-201", "INV-12")
def test_remover_contato_leva_os_telefones_dele(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    pid = novo_paciente(cadastro, cadastro_zerado, fabrica)
    contato = cadastro.contatos.incluir_contato(recepcao, pid, fabrica.nome(), "filho")
    nome = fabrica.nome()
    cadastro.contatos.alterar_contato(recepcao, contato, nome, "neto")
    cadastro.contatos.alterar_contato(recepcao, contato, nome, "neto")  # igual: nada é auditado
    do_contato = cadastro.contatos.incluir_telefone(recepcao, pid, "64", "99999-0002", CELULAR, contato)
    cadastro.contatos.alterar_telefone(recepcao, do_contato, "64", "99999-0012", CELULAR)  # continua do contato
    proprio = cadastro.contatos.incluir_telefone(recepcao, pid, "64", "99999-0003", CELULAR)
    cadastro.contatos.remover_contato(recepcao, contato)
    ficha = cadastro.pacientes.ver_ficha(recepcao, pid)
    assert ficha.contatos == () and [t.id for t in ficha.telefones] == [proprio]
    assert len(auditorias(engine_web, "contato")) == 3 and len(auditorias(engine_web, "telefone")) == 4
    with pytest.raises(NaoEncontrado):
        cadastro.contatos.alterar_contato(recepcao, contato, fabrica.nome(), None)
    with pytest.raises(RegraViolada) as erro:
        cadastro.contatos.incluir_contato(recepcao, pid, "   ", None)
    assert erro.value.codigo == "contato.nome"


@pytest.mark.requisito("CT-ACE-01", "RF-1008")
def test_so_recepcao_e_administracao_gerem_e_anulado_nao_recebe(
    cadastro_zerado: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    pid = novo_paciente(cadastro, cadastro_zerado, fabrica)
    for perfil in (Perfil.VISUALIZADOR, Perfil.TI, Perfil.ENFERMAGEM):
        with pytest.raises(AcessoNegado):
            cadastro.contatos.incluir_contato(pessoa(cadastro_zerado, "admin", perfil), pid, fabrica.nome(), None)
    admin = pessoa(cadastro_zerado, "admin", Perfil.ADMINISTRACAO)
    cadastro.contatos.incluir_telefone(admin, pid, "64", "99999-0004", CELULAR)
    with engine_migracao.begin() as c:
        c.execute(text("UPDATE paciente SET anulado_em = NOW(6) WHERE id = :p"), {"p": pid})
    with pytest.raises(NaoEncontrado):
        cadastro.contatos.incluir_telefone(admin, pid, "64", "99999-0005", CELULAR)
