"""O MOD-03 nas portas dos outros módulos, com o banco (DDS §7.8, §7.10, §11.1): CT-CAD-06 e CT-CAD-07 com os
participantes reais, situação da ficha, pendências, termos assinados e leituras para o MOD-05.

Os contextos são de terça, 13/10/2026, às 10h (o primeiro turno de terça acabou de terminar).
"""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from sar.modulo_01_acesso.servicos import ServicoAuditoria
from sar.modulo_02_cadastro.contrato import Situacao, TipoEvento
from sar.modulo_02_cadastro.servicos import ServicoPacientes
from sar.modulo_03_operacao.contrato import vinculo_da_extra, vinculo_da_troca
from sar.modulo_03_operacao.integracao import AlocacaoDaFicha
from sar.modulo_03_operacao.leitura import ServicoLeituraOperacao
from sar.modulo_03_operacao.pendencias import fontes
from sar.modulo_06_configuracao.servicos import ServicoReferencias
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.documentos import DOCUMENTO_DA_EXTRA, DOCUMENTO_DA_TROCA
from sar.nucleo.erros import RegraViolada
from sar.nucleo.eventos import DocumentoIncorporado, DocumentoRevinculado
from sar.nucleo.portas import FontePendencia, ItemPendencia, Prioridade
from testes.apoio.cadastro import AGORA, dados_completos, inserir_documento, pessoa
from testes.apoio.fabrica import Fabrica
from testes.apoio.operacao import Operacao, confirmar, contexto, definir_implantacao, local, montar

pytestmark = pytest.mark.integracao

SEG_1, TER_1 = 1, 2
MIGRACAO_0002 = Path(__file__).resolve().parents[2] / "sar/modulo_08_dados/migracoes/versions/0002_dados_fixos.py"


def d(dia: int, mes: int = 10) -> date:
    return date(2026, mes, dia)


@pytest.fixture
def op(engine_web: Engine, engine_migracao: Engine, operacao_zerada: dict[str, int]) -> Operacao:
    definir_implantacao(engine_migracao, d(28, 9), operacao_zerada["ti"])
    return montar(engine_web)


def paciente(op: Operacao, ids: dict[str, int], fabrica: Fabrica, escala: int | None = SEG_1) -> int:
    pid = op.cadastro.pacientes.criar(pessoa(ids), dados_completos(fabrica), d(1, 9))
    if escala is not None:
        op.escalas.alocar(contexto(ids, "enfermagem", Perfil.ENFERMAGEM), pid, escala, d(1, 9))
    return pid


def contar(engine: Engine, tabela: str) -> int:
    with engine.connect() as c:
        return int(c.execute(text(f"SELECT COUNT(*) FROM {tabela}")).scalar_one())  # noqa: S608 — nome fixo do teste


# ------------------------------------------------------------------ CT-CAD-07 (DD-31)
@pytest.mark.requisito("CT-CAD-07", "DD-31", "P-08", "RF-604")
def test_presenca_posterior_impede_o_evento_e_trocas_e_extras_depois_dele_sao_canceladas(
    op: Operacao, operacao_zerada: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    ids = operacao_zerada
    pid = paciente(op, ids, fabrica)
    confirmar(op, ids, d(12), SEG_1)  # presente na segunda, 12/10
    enfermeira = contexto(ids, "enfermagem", Perfil.ENFERMAGEM)
    op.escalas.registrar_troca(enfermeira, pid, d(14), d(15), TER_1)
    op.escalas.registrar_extra(enfermeira, pid, d(17), TER_1)

    with pytest.raises(RegraViolada) as erro:
        op.cadastro.eventos.registrar(pessoa(ids), pid, TipoEvento.OBITO, d(9), None)
    assert erro.value.codigo == "evento.impedimentos"
    [impedimento] = erro.value.detalhe["impedimentos"]
    assert (impedimento.codigo, tuple(impedimento.datas)) == ("presenca_posterior", (d(12),))

    op.cadastro.eventos.registrar(pessoa(ids), pid, TipoEvento.ALTA, d(13), None)
    with engine_web.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM troca_pontual WHERE cancelada_em IS NULL")).scalar_one() == 0
        assert c.execute(text("SELECT COUNT(*) FROM extra_planejada WHERE cancelada_em IS NULL")).scalar_one() == 0
        sql = "SELECT motivo FROM auditoria WHERE operacao IN ('operacao.troca.cancelar', 'operacao.extra.cancelar')"
        assert c.execute(text(sql)).scalars().all() == ["Período encerrado em 13/10/2026"] * 2


# ------------------------------------------------------------------ CT-CAD-06 (DEC-61)
@pytest.mark.requisito("CT-CAD-06", "DEC-61", "RF-1008", "RF-915")
def test_anulacao_mostra_o_impacto_descarta_tudo_e_marca_o_mes_fechado(
    op: Operacao, operacao_zerada: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    ids = operacao_zerada
    pid = paciente(op, ids, fabrica)
    for data, escala in [(d(28, 9), 1), (d(28, 9), 3), (d(28, 9), 5), (d(29, 9), 2), (d(29, 9), 4), (d(29, 9), 6),
                         (d(30, 9), 1), (d(30, 9), 3), (d(30, 9), 5)]:  # fmt: skip
        confirmar(op, ids, data, escala)  # setembro fechado, com as presenças dele
    enfermeira = contexto(ids, "enfermagem", Perfil.ENFERMAGEM)
    op.escalas.registrar_troca(enfermeira, pid, d(14), d(15), TER_1)
    op.escalas.registrar_extra(enfermeira, pid, d(17), TER_1)

    impacto = op.cadastro.anulacao.impacto(pessoa(ids), pid)
    assert impacto.contagens == {"presencas": 2, "alocacoes": 1, "trocas": 1, "extras": 1}
    assert impacto.alcanca_sessao_confirmada and impacto.alcanca_mes_fechado
    sid = op.cadastro.anulacao.solicitar(pessoa(ids), pid, "Cadastro em duplicidade")
    op.cadastro.autorizacoes.aprovar(contexto(ids, "admin", Perfil.ADMINISTRACAO), sid)
    for tabela in ("presenca", "alocacao", "troca_pontual", "extra_planejada"):
        assert contar(engine_web, tabela) == 0, tabela
    with engine_web.connect() as c:
        marca = c.execute(text("SELECT competencia, motivo FROM mes_alterado")).one()
        assert tuple(marca) == ("2026-09", "Cadastro em duplicidade")
        assert c.execute(text("SELECT COUNT(*) FROM sessao_turno")).scalar_one() == 9  # as sessões continuam


# ------------------------------------------------------------------ situação da ficha (§6.3)
@pytest.mark.requisito("RF-403", "DD-27")
def test_ficha_mostra_sem_alocacao_ate_a_enfermagem_alocar(
    op: Operacao, operacao_zerada: dict[str, int], fabrica: Fabrica
) -> None:
    ids = operacao_zerada
    cadastro = op.cadastro
    pacientes = ServicoPacientes(cadastro.executar, ServicoAuditoria(), ServicoReferencias(), cadastro.provedor_cep,
                                 AlocacaoDaFicha(cadastro.leitura))  # fmt: skip
    pid = paciente(op, ids, fabrica, escala=None)
    assert pacientes.ver_ficha(pessoa(ids), pid).situacao is Situacao.SEM_ALOCACAO
    op.escalas.alocar(contexto(ids, "enfermagem", Perfil.ENFERMAGEM), pid, TER_1, d(1, 9))
    assert pacientes.ver_ficha(pessoa(ids), pid).situacao is Situacao.ATIVO


# ------------------------------------------------------------------ pendências (§11.1, linhas 4 a 8)
def itens(op: Operacao, ctx: Contexto, codigo: str, ids: list[int] | None = None) -> list[ItemPendencia]:
    fonte: FontePendencia = next(f for f in fontes(op.cadastro.leitura, op.parametros) if f.codigo == codigo)
    if ids is not None:
        return op.cadastro.executar(lambda uow: fonte.listar_por_pacientes(uow, ctx, ids))
    return op.cadastro.executar(lambda uow: fonte.listar(uow, ctx))


@pytest.mark.requisito("RF-403", "RF-809", "RF-921", "RN-01", "DD-54", "RNF-625")
def test_pendencias_da_operacao_por_perfil(
    op: Operacao, operacao_zerada: dict[str, int], engine_migracao: Engine, fabrica: Fabrica
) -> None:
    ids = operacao_zerada
    recepcao, enfermeira = pessoa(ids), contexto(ids, "enfermagem", Perfil.ENFERMAGEM)
    ti = contexto(ids, "ti", Perfil.TI)
    definir_implantacao(engine_migracao, d(12), ids["ti"])
    sem_escala = paciente(op, ids, fabrica, escala=None)
    regular = paciente(op, ids, fabrica, escala=TER_1)

    nao_confirmadas = itens(op, recepcao, "sessao_nao_confirmada")
    assert len(nao_confirmadas) == 4 and {i.prioridade for i in nao_confirmadas} == {Prioridade.URGENCIA}
    assert nao_confirmadas[-1].descricao == "Primeiro turno de 13/10/2026 sem confirmação"
    assert itens(op, enfermeira, "sessao_nao_confirmada") == [] and itens(op, ti, "sessao_nao_confirmada") == []

    assert [i.paciente_id for i in itens(op, enfermeira, "sem_alocacao")] == [sem_escala]
    assert itens(op, ti, "sem_alocacao") == []  # TI nunca recebe dado de paciente

    troca = op.escalas.registrar_troca(enfermeira, regular, d(15), d(14), SEG_1)
    op.escalas.registrar_extra(enfermeira, regular, d(16), SEG_1)
    termos = itens(op, recepcao, "termo_a_emitir")
    assert [i.descricao for i in termos] == [
        "Declaração de troca de turno a emitir e assinar (15/10 para 14/10)",
        "Termo de diálise extra de 10/2026 a emitir e assinar",
    ]
    assert itens(op, recepcao, "termo_a_emitir", [sem_escala]) == []

    for dia in (12, 13):  # fora da escala dele, sem troca nem extra planejada
        op.turnos.acrescentar_paciente(contexto(ids, "recepcao", Perfil.RECEPCAO, local(d(dia), 9)), d(dia),
                                       SEG_1 if dia == 12 else TER_1, sem_escala)  # fmt: skip
    sem_registro = itens(op, enfermeira, "presenca_sem_registro")
    assert [i.paciente_id for i in sem_registro] == [sem_escala, sem_escala]
    assert itens(op, recepcao, "presenca_sem_registro") == []  # linha 7: só a enfermagem
    assert troca > 0


@pytest.mark.requisito("RN-01", "INV-05", "CT-FRQ-08")
def test_pendencia_de_extra_alem_do_limite_a_partir_da_quinta(
    op: Operacao, operacao_zerada: dict[str, int], fabrica: Fabrica
) -> None:
    ids = operacao_zerada
    pid = paciente(op, ids, fabrica, escala=TER_1)
    for dia in (2, 5, 7, 9):
        op.turnos.acrescentar_paciente(contexto(ids, "recepcao", Perfil.RECEPCAO, local(d(dia), 7)), d(dia), SEG_1, pid)
    assert itens(op, pessoa(ids), "extra_alem_do_limite") == []  # quatro: aviso, sem pendência
    op.turnos.acrescentar_paciente(contexto(ids, "recepcao", Perfil.RECEPCAO, local(d(12), 7)), d(12), SEG_1, pid)
    [item] = itens(op, pessoa(ids), "extra_alem_do_limite")
    assert (item.paciente_id, item.descricao) == (pid, "5 sessões extras em 10/2026 (limite de 4)")


# ------------------------------------------------------------------ termos assinados (RF-805, RF-809, DD-28)
@pytest.mark.requisito("RF-809", "RF-805", "DD-28", "RF-713")
def test_termo_assinado_encerra_a_pendencia_e_o_revinculo_a_reabre(
    op: Operacao, operacao_zerada: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> None:
    ids = operacao_zerada
    pid, outro = paciente(op, ids, fabrica, escala=TER_1), paciente(op, ids, fabrica, escala=TER_1)
    enfermeira = contexto(ids, "enfermagem", Perfil.ENFERMAGEM)
    troca = op.escalas.registrar_troca(enfermeira, pid, d(15), d(14), SEG_1)
    op.escalas.registrar_extra(enfermeira, pid, d(16), SEG_1)
    declaracao = inserir_documento(engine_migracao, pid, DOCUMENTO_DA_TROCA, ids["recepcao"])
    termo = inserir_documento(engine_migracao, pid, DOCUMENTO_DA_EXTRA, ids["recepcao"])

    def publicar(evento: DocumentoIncorporado | DocumentoRevinculado) -> None:
        op.cadastro.executar(lambda uow: uow.publicar(evento))

    publicar(DocumentoIncorporado(declaracao, outro, DOCUMENTO_DA_TROCA, vinculo_da_troca(troca)))  # outro paciente
    publicar(DocumentoIncorporado(termo, pid, DOCUMENTO_DA_TROCA, vinculo_da_extra("2026-10")))  # tipo errado
    assert len(itens(op, pessoa(ids), "termo_a_emitir")) == 2

    publicar(DocumentoIncorporado(declaracao, pid, DOCUMENTO_DA_TROCA, vinculo_da_troca(troca)))
    publicar(DocumentoIncorporado(termo, pid, DOCUMENTO_DA_EXTRA, vinculo_da_extra("2026-10")))
    assert itens(op, pessoa(ids), "termo_a_emitir") == []
    assert contar(engine_web, "termo_extra") == 1

    publicar(DocumentoRevinculado(declaracao, pid, outro))
    publicar(DocumentoRevinculado(termo, pid, outro))
    assert len(itens(op, pessoa(ids), "termo_a_emitir")) == 2  # a pendência volta por derivação


@pytest.mark.requisito("RF-809", "DEC-41")
def test_tipos_dos_termos_existem_na_migracao() -> None:
    spec = importlib.util.spec_from_file_location("dados_fixos_0002", MIGRACAO_0002)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    assert {DOCUMENTO_DA_TROCA, DOCUMENTO_DA_EXTRA} <= {t[0] for t in modulo.TIPOS_DOCUMENTO}


# ------------------------------------------------------------------ leituras para o MOD-05 (RF-913 a RF-915)
@pytest.mark.requisito("RF-913", "RF-914", "RF-915", "DD-26")
def test_leituras_do_mes_para_os_relatorios(op: Operacao, operacao_zerada: dict[str, int], fabrica: Fabrica) -> None:
    ids = operacao_zerada
    pid = paciente(op, ids, fabrica)
    leitura = ServicoLeituraOperacao(op.cadastro.leitura, op.parametros)
    executar = op.cadastro.executar
    aberto = executar(lambda uow: leitura.mes_fechado(uow, "2026-09", d(13)))
    assert not aberto.fechado and len(aberto.pendentes) == 9  # RF-913: quantas faltam e quais
    confirmar(op, ids, d(28, 9), SEG_1)
    restantes = executar(lambda uow: leitura.sessoes_nao_confirmadas(uow, d(28, 9), d(30, 9), AGORA))
    assert len(restantes) == 8  # RF-914
    assert executar(lambda uow: leitura.marcas_alteracao(uow, ["2026-09"])) == []
    frequencia = executar(lambda uow: leitura.frequencia_do_mes(uow, "2026-09", AGORA))
    assert frequencia[pid].balanco.previstas == 2 and frequencia[pid].balanco.realizadas == 2
