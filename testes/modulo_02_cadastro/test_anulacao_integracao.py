"""Anulação de cadastro criado por engano no MySQL: CT-CAD-06 (DEC-61, RF-1008, §6.9) e DD-89."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from sar.modulo_02_cadastro.contrato import TipoTelefone
from sar.modulo_08_dados.erros_banco import restricao_violada
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado, NaoEncontrado
from sar.nucleo.portas import ImpactoAnulacao
from sar.nucleo.uow import UnidadeDeTrabalho
from testes.apoio.cadastro import INICIO, Cadastro, dados_completos, montar, pessoa
from testes.apoio.fabrica import Fabrica

pytestmark = pytest.mark.integracao


@dataclass
class ParticipanteFalso:
    """Faz o papel do MOD-03 e do MOD-04 (Incrementos 3 e 4)."""

    contagens: dict[str, int]
    sessao_confirmada: bool = False
    falhar: bool = False
    descartados: list[int] = field(default_factory=list)

    def impacto(self, uow: UnidadeDeTrabalho, paciente_id: int) -> ImpactoAnulacao:
        return ImpactoAnulacao(self.contagens, self.sessao_confirmada, False)

    def descartar(self, uow: UnidadeDeTrabalho, contexto: Contexto, paciente_id: int) -> None:
        if self.falhar:
            raise RuntimeError("participante falhou")
        self.descartados.append(paciente_id)


def admin(usuarios: dict[str, int]) -> Contexto:
    return pessoa(usuarios, "admin", Perfil.ADMINISTRACAO)


def cadastro_com_contato(cadastro: Cadastro, usuarios: dict[str, int], fabrica: Fabrica) -> int:
    recepcao = pessoa(usuarios)
    pid = cadastro.pacientes.criar(recepcao, replace(dados_completos(fabrica), cep="75800000", rg="123"), INICIO)
    contato = cadastro.contatos.incluir_contato(recepcao, pid, fabrica.nome(), "filha")
    cadastro.contatos.incluir_telefone(recepcao, pid, "64", "99999-0001", TipoTelefone.CELULAR)
    cadastro.contatos.incluir_telefone(recepcao, pid, "64", "99999-0002", TipoTelefone.CELULAR, contato)
    return pid


@pytest.mark.requisito("CT-CAD-06", "RF-1008", "DEC-61")
def test_impacto_mostrado_antes_e_tudo_descartado_na_aprovacao(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    documentos = ParticipanteFalso({"documentos": 1})
    operacao = ParticipanteFalso({"presencas": 3, "alocacoes": 1}, sessao_confirmada=True)
    cadastro.participantes.extend([documentos, operacao])
    recepcao = pessoa(cadastro_zerado)
    pid = cadastro_com_contato(cadastro, cadastro_zerado, fabrica)

    impacto = cadastro.anulacao.impacto(recepcao, pid)
    assert (dict(impacto.contagens), impacto.alcanca_sessao_confirmada) == (
        {"documentos": 1, "presencas": 3, "alocacoes": 1}, True
    )  # fmt: skip
    pedido = cadastro.anulacao.solicitar(recepcao, pid, "Cadastrado no lugar de outro paciente")
    [pendente] = cadastro.autorizacoes.pendentes(admin(cadastro_zerado))
    assert "Será descartado: 1 alocação, 1 documento, 3 presenças." in pendente.descricao
    assert "Alcança sessão já confirmada." in pendente.descricao
    assert documentos.descartados == []  # nada antes da decisão

    assert cadastro.autorizacoes.aprovar(admin(cadastro_zerado), pedido) == "executada"
    assert documentos.descartados == [pid] and operacao.descartados == [pid]
    with pytest.raises(NaoEncontrado):
        cadastro.pacientes.ver_ficha(recepcao, pid)
    assert cadastro.executar(lambda uow: cadastro.leitura.identificacao(uow, pid)) is None


@pytest.mark.requisito("DD-89", "RF-1008")
def test_dados_pessoais_apagados_e_numeros_livres_para_o_cadastro_certo(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    pid = cadastro_com_contato(cadastro, cadastro_zerado, fabrica)
    ficha = cadastro.pacientes.ver_ficha(recepcao, pid)
    cadastro.anulacao.solicitar(admin(cadastro_zerado), pid, "Duplicata")  # P-01: executa na hora

    with engine_web.connect() as c:
        linha = c.execute(text("SELECT * FROM paciente WHERE id = :p"), {"p": pid}).mappings().one()
        preenchidas = {k for k, v in linha.items() if v is not None and v is not False and v != 0}
        assert preenchidas == {"id", "anulado_em", "criado_em", "versao"}
        assert c.execute(text("SELECT COUNT(*) FROM contato")).scalar_one() == 0
        assert c.execute(text("SELECT COUNT(*) FROM telefone")).scalar_one() == 0
        assert (
            c.execute(text("SELECT COUNT(*) FROM periodo_tratamento WHERE paciente_id = :p"), {"p": pid}).scalar_one()
            == 1
        )
        [alteracoes] = (
            c.execute(text("SELECT alteracoes FROM auditoria WHERE operacao = 'cadastro.paciente.anular'"))
            .scalars()
            .all()
        )
    assert alteracoes == '{"anulado":[false,true],"dados_pessoais":[true,false]}'  # sem repetir o que foi apagado

    certo = cadastro.pacientes.criar(recepcao, ficha.dados, INICIO)  # mesmos prontuário, CPF e CNS
    assert cadastro.pacientes.ver_ficha(recepcao, certo).dados.prontuario == ficha.dados.prontuario
    assert [i.paciente_id for i in cadastro.pacientes.buscar(recepcao, ficha.dados.prontuario or "")] == [certo]


@pytest.mark.requisito("CT-CAD-06", "DD-17")
def test_anulacao_invalidada_se_o_cadastro_mudou_depois_do_pedido(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    dados = dados_completos(fabrica)
    pid = cadastro.pacientes.criar(recepcao, dados, INICIO)
    pedido = cadastro.anulacao.solicitar(recepcao, pid, "Engano")
    cadastro.pacientes.atualizar(recepcao, pid, 1, replace(dados, bairro="Centro"))
    assert cadastro.autorizacoes.aprovar(admin(cadastro_zerado), pedido) == "invalidada"
    assert cadastro.pacientes.ver_ficha(recepcao, pid).dados.bairro == "Centro"


@pytest.mark.requisito("CT-CAD-06")
def test_falha_de_um_participante_desfaz_a_anulacao_inteira(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    primeiro, quebrado = ParticipanteFalso({"documentos": 1}), ParticipanteFalso({}, falhar=True)
    cadastro.participantes.extend([primeiro, quebrado])
    recepcao = pessoa(cadastro_zerado)
    pid = cadastro_com_contato(cadastro, cadastro_zerado, fabrica)
    pedido = cadastro.anulacao.solicitar(recepcao, pid, "Engano")
    with pytest.raises(RuntimeError):
        cadastro.autorizacoes.aprovar(admin(cadastro_zerado), pedido)
    ficha = cadastro.pacientes.ver_ficha(recepcao, pid)  # nada mudou: mesma transação
    assert ficha.dados.nome is not None and len(ficha.contatos) == 1


@pytest.mark.requisito("CT-ACE-01", "CT-ACE-03")
def test_quem_pode_pedir_e_ver_o_impacto(cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica) -> None:
    cadastro = montar(engine_web)
    pid = cadastro.pacientes.criar(pessoa(cadastro_zerado), dados_completos(fabrica), INICIO)
    for perfil in (Perfil.VISUALIZADOR, Perfil.TI, Perfil.ENFERMAGEM):
        contexto = pessoa(cadastro_zerado, "ti", perfil)
        with pytest.raises(AcessoNegado):
            cadastro.anulacao.solicitar(contexto, pid, "x")
        with pytest.raises(AcessoNegado):
            cadastro.anulacao.impacto(contexto, pid)
    with pytest.raises(NaoEncontrado):
        cadastro.anulacao.solicitar(pessoa(cadastro_zerado), pid + 999_999, "x")
    assert cadastro.anulacao.impacto(admin(cadastro_zerado), pid).contagens == {}


@pytest.mark.requisito("DD-89", "RF-102")
@pytest.mark.parametrize("coluna", ["prontuario", "nome"])
def test_banco_so_aceita_paciente_sem_prontuario_ou_nome_se_anulado(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica, coluna: str
) -> None:
    cadastro = montar(engine_web)
    pid = cadastro.pacientes.criar(pessoa(cadastro_zerado), dados_completos(fabrica), INICIO)
    with pytest.raises(DBAPIError) as erro, engine_web.begin() as c:
        c.execute(text(f"UPDATE paciente SET {coluna} = NULL WHERE id = :p"), {"p": pid})  # noqa: S608
    assert restricao_violada(erro.value) == "ck_paciente__minimo"
