"""Rascunho de cadastro no MySQL: RF-919, RF-920, DD-07 (cifra com dado associado), §6.6."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, timedelta

import pytest
from sqlalchemy import Engine, text

from sar.modulo_02_cadastro.contrato import DadosPaciente
from sar.modulo_02_cadastro.rascunhos import FonteRascunhoProximoDoDescarte
from sar.modulo_06_configuracao.servicos import LeitorParametrosSQL
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado, IntegridadeViolada, RegraViolada
from testes.apoio.cadastro import AGORA, INICIO, montar, pessoa
from testes.apoio.fabrica import Fabrica

pytestmark = pytest.mark.integracao


def daqui(contexto: Contexto, dias: int) -> Contexto:
    return replace(contexto, instante=AGORA + timedelta(days=dias))


def auditados(engine: Engine) -> list[tuple[str, object, object]]:
    sql = "SELECT operacao, alteracoes, motivo FROM auditoria WHERE entidade = 'rascunho_cadastro' ORDER BY id"
    with engine.connect() as c:
        return [(str(o), a, m) for o, a, m in c.execute(text(sql))]


@pytest.mark.requisito("RF-919", "DD-07", "RNF-605")
def test_salva_cifrado_retoma_e_audita_sem_conteudo(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    nome = fabrica.nome()
    conteudo = {"nome": nome, "cpf": "529.982.247-25"}
    salvo = cadastro.rascunhos.salvar(recepcao, conteudo)
    assert salvo.descarte_em == date(2026, 10, 16)  # 13/10 + 3 dias (rascunho_prazo)
    cadastro.rascunhos.salvar(recepcao, conteudo)  # igual: nada é gravado nem auditado (DD-10)
    cadastro.rascunhos.salvar(recepcao, {**conteudo, "bairro": "Centro"})
    retomado = cadastro.rascunhos.retomar(recepcao)
    assert retomado is not None and retomado.conteudo == {**conteudo, "bairro": "Centro"}
    with engine_web.connect() as c:
        cifrado = c.execute(text("SELECT conteudo_cifrado FROM rascunho_cadastro")).scalar_one()
    assert nome.encode() not in cifrado and b"529" not in cifrado and b"Centro" not in cifrado
    assert auditados(engine_web) == [
        ("cadastro.rascunho.salvar", None, None),
        ("cadastro.rascunho.salvar", None, None),
        ("cadastro.rascunho.retomar", None, None),
    ]


@pytest.mark.requisito("DD-07")
def test_cifrado_trocado_entre_rascunhos_nao_abre(
    cadastro_zerado: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao, admin = pessoa(cadastro_zerado), pessoa(cadastro_zerado, "admin", Perfil.ADMINISTRACAO)
    cadastro.rascunhos.salvar(recepcao, {"nome": fabrica.nome()})
    cadastro.rascunhos.salvar(admin, {"nome": fabrica.nome()})
    with engine_migracao.begin() as c:  # o cifrado da recepção copiado para o rascunho da administração
        c.execute(
            text(
                "UPDATE rascunho_cadastro a JOIN rascunho_cadastro r ON r.usuario_id = :r"
                " SET a.conteudo_cifrado = r.conteudo_cifrado, a.nonce = r.nonce WHERE a.usuario_id = :a"
            ),
            {"r": cadastro_zerado["recepcao"], "a": cadastro_zerado["admin"]},
        )
    with pytest.raises(IntegridadeViolada):  # o id do rascunho é o dado associado
        cadastro.rascunhos.retomar(admin)


@pytest.mark.requisito("RF-919")
def test_cada_um_ve_so_o_proprio_rascunho_e_descarta(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao, admin = pessoa(cadastro_zerado), pessoa(cadastro_zerado, "admin", Perfil.ADMINISTRACAO)
    cadastro.rascunhos.salvar(recepcao, {"nome": fabrica.nome()})
    assert cadastro.rascunhos.retomar(admin) is None
    cadastro.rascunhos.descartar(admin)  # não tem: nada acontece
    cadastro.rascunhos.descartar(recepcao)
    assert cadastro.rascunhos.retomar(recepcao) is None
    assert [o for o, _, _ in auditados(engine_web)] == ["cadastro.rascunho.salvar", "cadastro.rascunho.descartar"]


@pytest.mark.requisito("RF-919", "RF-102")
def test_salvar_o_paciente_elimina_o_rascunho_de_quem_salvou(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao, admin = pessoa(cadastro_zerado), pessoa(cadastro_zerado, "admin", Perfil.ADMINISTRACAO)
    nome = fabrica.nome()
    cadastro.rascunhos.salvar(recepcao, {"nome": nome})
    cadastro.rascunhos.salvar(admin, {"nome": fabrica.nome()})
    cadastro.pacientes.criar(recepcao, DadosPaciente(nome=nome, prontuario="F1"), INICIO)
    assert cadastro.rascunhos.retomar(recepcao) is None
    assert cadastro.rascunhos.retomar(admin) is not None  # o de outra pessoa fica
    assert ("cadastro.rascunho.descartar", None, "virou cadastro") in auditados(engine_web)


@pytest.mark.requisito("RF-920", "DD-48")
def test_prazo_do_rascunho_e_aviso_so_para_o_autor(
    cadastro_zerado: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao, admin = pessoa(cadastro_zerado), pessoa(cadastro_zerado, "admin", Perfil.ADMINISTRACAO)
    cadastro.rascunhos.salvar(recepcao, {"nome": fabrica.nome()})
    fonte = FonteRascunhoProximoDoDescarte(LeitorParametrosSQL(cadastro.executar))
    assert cadastro.executar(lambda uow: fonte.listar(uow, daqui(recepcao, 1))) == []  # 14/10: antes do aviso
    [item] = cadastro.executar(lambda uow: fonte.listar(uow, daqui(recepcao, 2)))  # 15/10: véspera do descarte
    assert item.descricao == "Rascunho de cadastro será descartado em 16/10/2026" and item.paciente_id is None
    assert cadastro.executar(lambda uow: fonte.listar(uow, daqui(admin, 2))) == []  # não é dela
    assert cadastro.executar(lambda uow: fonte.listar_por_pacientes(uow, daqui(recepcao, 2), [1])) == []
    assert cadastro.rascunhos.retomar(daqui(recepcao, 3)) is not None  # no dia do descarte, até o job rodar
    assert cadastro.rascunhos.retomar(daqui(recepcao, 4)) is None  # vencido
    cadastro.configuracao.alterar_parametro(admin, "rascunho_prazo", 10)
    try:
        assert cadastro.rascunhos.retomar(daqui(recepcao, 4)) is not None
    finally:
        with engine_migracao.begin() as c:  # o parâmetro aponta para o usuário de teste, que a limpeza apaga
            c.execute(text("DELETE FROM parametro"))


@pytest.mark.requisito("RF-919")
def test_primeiros_salvamentos_simultaneos_deixam_um_rascunho(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    nomes = [fabrica.nome() for _ in range(4)]
    with ThreadPoolExecutor(4) as grupo:
        list(grupo.map(lambda nome: cadastro.rascunhos.salvar(recepcao, {"nome": nome}), nomes))
    with engine_web.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM rascunho_cadastro")).scalar_one() == 1
    retomado = cadastro.rascunhos.retomar(recepcao)
    assert retomado is not None and retomado.conteudo["nome"] in nomes


@pytest.mark.requisito("CT-ACE-01")
def test_permissoes_e_limites_do_rascunho(cadastro_zerado: dict[str, int], engine_web: Engine) -> None:
    cadastro = montar(engine_web)
    for perfil in (Perfil.VISUALIZADOR, Perfil.TI, Perfil.ENFERMAGEM):
        with pytest.raises(AcessoNegado):
            cadastro.rascunhos.salvar(pessoa(cadastro_zerado, "ti", perfil), {"nome": "x"})
    with pytest.raises(AcessoNegado):
        cadastro.rascunhos.retomar(Contexto.sistema("teste", AGORA))
    recepcao = pessoa(cadastro_zerado)
    for invalido in ({"x" * 61: "a"}, {"nome": "x" * 501}, {f"c{i}": "a" for i in range(201)}):
        with pytest.raises(RegraViolada) as erro:
            cadastro.rascunhos.salvar(recepcao, invalido)
        assert erro.value.codigo == "rascunho.conteudo"
