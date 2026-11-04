"""Atendimento ao titular com o banco (DDS §15, RF-1009, DD-18, DD-105, §11.1 linha 10).

O relógio dos contextos é terça, 13/10/2026, às 10h em Jataí.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta

import pikepdf
import pytest
from sqlalchemy import Engine, text

from sar.modulo_01_acesso.servicos import ServicoAuditoria
from sar.modulo_03_operacao.leitura import ServicoLeituraOperacao
from sar.modulo_05_emissao.emissao import ServicoEmissao
from sar.modulo_06_configuracao.contrato import DadosInstitucionais
from sar.modulo_06_configuracao.servicos import LeitorParametrosSQL, ServicoReferencias
from sar.modulo_11_titular.contrato import (
    FUNDAMENTO_GUARDA,
    Canal,
    FormaEntrega,
    SituacaoRequisicao,
    TipoRequisicao,
)
from sar.modulo_11_titular.pendencias import FontePedidoTitular
from sar.modulo_11_titular.servicos import ServicoTitular
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado, NaoEncontrado, RegraViolada
from sar.nucleo.portas import Prioridade
from testes.apoio.cadastro import AGORA, INICIO, Cadastro, dados_completos, montar, pessoa
from testes.apoio.fabrica import Fabrica
from testes.apoio.modelos import conversor_no_ar, texto_do_pdf

pytestmark = pytest.mark.integracao

HOJE = date(2026, 10, 13)
CLINICA = DadosInstitucionais("Clínica Fictícia de Teste", "Rua das Flores, 100", "75803000", "5211909", None, None)


@dataclass
class CopiaFalsa:
    """A LeituraDocumentos só com a cópia ao titular: o cofre e a cópia são testados no MOD-04."""

    paginas: int = 2
    pedidos: list[int] = field(default_factory=list)

    def copia_ao_titular(self, contexto: Contexto, paciente_id: int) -> bytes:
        self.pedidos.append(paciente_id)
        pdf = pikepdf.new()
        for _ in range(self.paginas):
            pdf.add_blank_page()
        saida = io.BytesIO()
        pdf.save(saida)
        return saida.getvalue()


@dataclass
class Cenario:
    cadastro: Cadastro
    titular: ServicoTitular
    fonte: FontePedidoTitular
    copia: CopiaFalsa
    ids: dict[str, int]
    paciente_id: int
    nome: str

    def contexto(self, chave: str = "recepcao", perfil: Perfil = Perfil.RECEPCAO, dias: int = 0) -> Contexto:
        base = pessoa(self.ids, chave, perfil)
        return Contexto(base.usuario_id, perfil, None, base.origem, AGORA + timedelta(days=dias), base.requisicao_id)

    @property
    def admin(self) -> Contexto:
        return self.contexto("admin", Perfil.ADMINISTRACAO)


@pytest.fixture
def cenario(
    cadastro_zerado: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> Iterator[Cenario]:
    cadastro = montar(engine_web)
    parametros = LeitorParametrosSQL(cadastro.executar)
    copia = CopiaFalsa()
    auditoria = ServicoAuditoria()
    operacao = ServicoLeituraOperacao(cadastro.leitura, parametros)
    emissao = ServicoEmissao(cadastro.executar, auditoria, ServicoReferencias(), cadastro.leitura, cadastro.pacientes,
                             operacao, copia, conversor_no_ar())  # fmt: skip
    titular = ServicoTitular(cadastro.executar, auditoria, cadastro.leitura, parametros, copia, emissao)
    cadastro.configuracao.alterar_institucional(pessoa(cadastro_zerado, "admin", Perfil.ADMINISTRACAO), CLINICA)
    dados = dados_completos(fabrica)
    paciente_id = cadastro.pacientes.criar(pessoa(cadastro_zerado), dados, INICIO)
    yield Cenario(cadastro, titular, FontePedidoTitular(cadastro.leitura, parametros), copia, cadastro_zerado,
                  paciente_id, dados.nome or "")  # fmt: skip
    with engine_migracao.begin() as c:
        for comando in ("DELETE FROM requisicao_titular", "DELETE FROM emissao_documento", "DELETE FROM instituicao",
                        "DELETE FROM parametro"):  # fmt: skip
            c.execute(text(comando))


def auditorias(engine: Engine, operacao: str) -> list[dict[str, list[object]]]:
    with engine.connect() as c:
        sql = "SELECT alteracoes FROM auditoria WHERE operacao = :o ORDER BY id"
        return [json.loads(a) if a else {} for (a,) in c.execute(text(sql), {"o": operacao})]


@pytest.mark.requisito("RF-1009", "DD-18")
def test_pedido_registrado_e_acompanhado_com_prazo_derivado(cenario: Cenario, engine_web: Engine) -> None:
    pedido = cenario.titular.registrar(cenario.contexto(), cenario.paciente_id, TipoRequisicao.CORRECAO,
                                       Canal.PRESENCIAL, date(2026, 10, 9))  # fmt: skip
    [item] = cenario.titular.consultar(cenario.contexto("admin", Perfil.VISUALIZADOR))
    assert (item.id, item.nome, item.tipo, item.canal) == (pedido, cenario.nome, TipoRequisicao.CORRECAO,
                                                          Canal.PRESENCIAL)  # fmt: skip
    assert (item.recebida_em, item.prazo, item.dias_restantes) == (date(2026, 10, 9), date(2026, 10, 24), 11)
    assert auditorias(engine_web, "titular.requisicao.registrar")[0]["tipo"] == [None, "correcao"]
    assert auditorias(engine_web, "titular.requisicao.consultar") == [{"quantidade": [None, 1]}]

    with engine_web.begin() as c:  # a administração reduz o prazo para 10 dias: o derivado acompanha (DD-18)
        c.execute(text("INSERT INTO parametro VALUES ('titular_prazo', '10', NOW(6), :u)"), {"u": cenario.ids["admin"]})
    assert cenario.titular.ver(cenario.admin, pedido).prazo == date(2026, 10, 19)


@pytest.mark.requisito("RF-1009")
def test_data_de_recebimento_no_futuro_e_recusada(cenario: Cenario) -> None:
    with pytest.raises(RegraViolada) as erro:
        cenario.titular.registrar(cenario.contexto(), cenario.paciente_id, TipoRequisicao.OUTROS, Canal.EMAIL,
                                  HOJE + timedelta(days=1))  # fmt: skip
    assert erro.value.codigo == "titular.recebida_no_futuro"
    with pytest.raises(NaoEncontrado):
        cenario.titular.registrar(cenario.contexto(), 999_999_999, TipoRequisicao.OUTROS, Canal.EMAIL, HOJE)


@pytest.mark.requisito("RF-1009", "DD-105", "RF-801")
def test_atendimento_de_acesso_entrega_declaracao_ficha_e_copia(cenario: Cenario, engine_web: Engine) -> None:
    pedido = cenario.titular.registrar(cenario.contexto(), cenario.paciente_id, TipoRequisicao.CONFIRMACAO_ACESSO,
                                       Canal.PRESENCIAL, HOJE)  # fmt: skip
    pacote = cenario.titular.atender_acesso(cenario.admin, pedido, FormaEntrega.EM_MAOS)
    with pikepdf.open(io.BytesIO(pacote.pdf)) as pdf:
        assert len(pdf.pages) == 4  # declaração, ficha e as duas páginas da cópia
    texto = texto_do_pdf(pacote.pdf)
    assert "DECLARAÇÃO DE ATENDIMENTO AO TITULAR DOS DADOS" in texto.upper() and cenario.nome in texto
    assert "2 páginas" in texto and "FICHA DE CADASTRO DO PACIENTE" in texto.upper()
    assert pacote.paginas_documentos == 2 and cenario.copia.pedidos == [cenario.paciente_id]
    assert auditorias(engine_web, "titular.copia.gerar") == [{"entrega": [None, "em_maos"], "paginas": [None, 4]}]
    with engine_web.connect() as c:
        modelos = [m for (m,) in c.execute(text("SELECT modelo FROM emissao_documento ORDER BY id"))]
    assert modelos == ["TITULAR", "DOC-01"]
    assert cenario.titular.ver(cenario.admin, pedido).situacao is SituacaoRequisicao.ABERTA  # concluir é à parte


@pytest.mark.requisito("RF-1009")
def test_atendimento_de_acesso_so_para_pedido_aberto_de_acesso_e_pela_administracao(cenario: Cenario) -> None:
    correcao = cenario.titular.registrar(cenario.contexto(), cenario.paciente_id, TipoRequisicao.CORRECAO,
                                         Canal.PRESENCIAL, HOJE)  # fmt: skip
    with pytest.raises(RegraViolada) as erro:
        cenario.titular.atender_acesso(cenario.admin, correcao, FormaEntrega.EM_MAOS)
    assert erro.value.codigo == "titular.nao_e_acesso"
    acesso = cenario.titular.registrar(cenario.contexto(), cenario.paciente_id, TipoRequisicao.CONFIRMACAO_ACESSO,
                                       Canal.EMAIL, HOJE)  # fmt: skip
    with pytest.raises(AcessoNegado):
        cenario.titular.atender_acesso(cenario.contexto(), acesso, FormaEntrega.EMAIL)
    cenario.titular.concluir(cenario.admin, acesso, "Cópia entregue em mãos ao titular.")
    with pytest.raises(RegraViolada) as erro:
        cenario.titular.atender_acesso(cenario.admin, acesso, FormaEntrega.EMAIL)
    assert erro.value.codigo == "titular.encerrada"


@pytest.mark.requisito("RF-1009")
def test_conclusao_e_negativa_fundamentada_auditadas(cenario: Cenario, engine_web: Engine) -> None:
    eliminacao = cenario.titular.registrar(cenario.contexto(), cenario.paciente_id, TipoRequisicao.ELIMINACAO,
                                           Canal.CARTA, HOJE)  # fmt: skip
    with pytest.raises(RegraViolada) as erro:
        cenario.titular.negar(cenario.admin, eliminacao, "  ")
    assert erro.value.codigo == "titular.negativa_sem_fundamento"
    with pytest.raises(AcessoNegado):
        cenario.titular.negar(cenario.contexto(), eliminacao, FUNDAMENTO_GUARDA)
    cenario.titular.negar(cenario.admin, eliminacao, FUNDAMENTO_GUARDA)
    with pytest.raises(RegraViolada) as erro:
        cenario.titular.concluir(cenario.admin, eliminacao, "Atendido depois de negado.")
    assert erro.value.codigo == "titular.encerrada"
    negado = cenario.titular.ver(cenario.admin, eliminacao)
    assert negado.situacao is SituacaoRequisicao.NEGADA and negado.desfecho == FUNDAMENTO_GUARDA
    assert negado.atendente_id == cenario.ids["admin"]
    assert auditorias(engine_web, "titular.requisicao.negar") == [
        {"situacao": ["aberta", "negada"], "desfecho": [None, FUNDAMENTO_GUARDA]}
    ]
    assert cenario.titular.consultar(cenario.admin) == []
    assert [r.id for r in cenario.titular.consultar(cenario.admin, None)] == [eliminacao]


@pytest.mark.requisito("RF-1009", "RF-1010", "RF-1004")
def test_pendencia_do_pedido_alta_e_urgente_a_tres_dias_do_prazo(cenario: Cenario) -> None:
    pedido = cenario.titular.registrar(cenario.contexto(), cenario.paciente_id, TipoRequisicao.INFORMACAO,
                                       Canal.TELEFONE, HOJE)  # fmt: skip

    def itens(contexto: Contexto) -> list[tuple[Prioridade, str]]:
        listados = cenario.cadastro.executar(lambda uow: cenario.fonte.listar(uow, contexto))
        return [(i.prioridade, i.descricao) for i in listados]

    descricao = "Pedido do titular (informação sobre uso e compartilhamento), prazo até 28/10/2026"
    assert itens(cenario.contexto()) == [(Prioridade.ALTA, descricao)]
    assert itens(cenario.contexto("admin", Perfil.VISUALIZADOR, dias=11)) == [(Prioridade.ALTA, descricao)]
    assert itens(cenario.contexto("admin", Perfil.ADMINISTRACAO, dias=12)) == [(Prioridade.URGENCIA, descricao)]
    assert itens(cenario.contexto("ti", Perfil.TI)) == []  # o TI nunca recebe dado de paciente
    por_paciente = cenario.cadastro.executar(
        lambda uow: cenario.fonte.listar_por_pacientes(uow, cenario.contexto(), [cenario.paciente_id])
    )
    assert [i.destino for i in por_paciente] == [f"/titular/{pedido}"]
    cenario.titular.concluir(cenario.admin, pedido, "Informações prestadas por telefone ao titular.")
    assert itens(cenario.contexto()) == []
