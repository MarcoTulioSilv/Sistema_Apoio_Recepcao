"""Frequência, mês fechado e autorizações com o banco: CT-FRQ-10, DD-26, RF-915, RF-916, RF-918, RF-921.

A implantação é segunda, 28/09/2026: setembro tem só nove sessões (28, 29 e 30, três turnos cada). Os contextos
são de terça, 13/10/2026, às 10h, quando setembro já terminou.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import Engine, text

from sar.modulo_03_operacao.contrato import OrigemPar
from sar.nucleo.contexto import Perfil
from sar.nucleo.erros import AcessoNegado, RegraViolada, RequerAutorizacao
from testes.apoio.cadastro import dados_completos, pessoa
from testes.apoio.fabrica import Fabrica
from testes.apoio.operacao import Operacao, contexto, definir_implantacao, local, montar

pytestmark = pytest.mark.integracao

SEG_1, TER_1 = 1, 2
IMPLANTACAO = date(2026, 9, 28)
SETEMBRO = [(date(2026, 9, d), e) for d, es in ((28, (1, 3, 5)), (29, (2, 4, 6)), (30, (1, 3, 5))) for e in es]


@pytest.fixture
def op(engine_web: Engine, engine_migracao: Engine, operacao_zerada: dict[str, int]) -> Operacao:
    definir_implantacao(engine_migracao, IMPLANTACAO, operacao_zerada["ti"])
    return montar(engine_web)


def alocado(op: Operacao, ids: dict[str, int], fabrica: Fabrica, escala: int = SEG_1) -> int:
    pid = op.cadastro.pacientes.criar(pessoa(ids), dados_completos(fabrica), date(2026, 9, 1))
    op.escalas.alocar(contexto(ids, "enfermagem", Perfil.ENFERMAGEM), pid, escala, date(2026, 9, 1))
    return pid


def confirmar(op: Operacao, ids: dict[str, int], data: date, escala: int) -> None:
    """Pela confirmação de verdade, na última hora do turno: ela grava a presença de todos (DD-24)."""
    fim = {1: 10, 2: 10, 3: 15, 4: 15, 5: 20, 6: 20}[escala]
    quando = contexto(ids, "recepcao", Perfil.RECEPCAO, local(data, fim - 1, 30))
    op.turnos.confirmar(quando, data, escala, op.turnos.tela_do_turno(quando, data, escala).versao)


def fechar_setembro(op: Operacao, ids: dict[str, int]) -> None:
    for data, escala in SETEMBRO:
        confirmar(op, ids, data, escala)


def marcas(engine: Engine) -> list[tuple[object, ...]]:
    with engine.connect() as c:
        sql = "SELECT competencia, responsavel_id, autorizador_id, motivo, solicitacao_id FROM mes_alterado ORDER BY id"
        return [tuple(r) for r in c.execute(text(sql))]


# ------------------------------------------------------------------ CT-FRQ-10
@pytest.mark.requisito("CT-FRQ-10", "DD-26", "RF-915", "RF-1008", "QAS-10")
def test_alteracao_autorizada_em_mes_fechado_grava_a_marca(
    op: Operacao, operacao_zerada: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    ids = operacao_zerada
    pid = alocado(op, ids, fabrica)
    recepcao, admin = pessoa(ids), contexto(ids, "admin", Perfil.ADMINISTRACAO)
    assert op.frequencia.balanco(recepcao, pid, "2026-09").provisorio  # sessões sem confirmação: aberto
    fechar_setembro(op, ids)
    assert not op.frequencia.balanco(recepcao, pid, "2026-09").provisorio  # terminou e tudo confirmado

    with pytest.raises(RequerAutorizacao) as pedido:
        op.turnos.marcar_ausencia(recepcao, date(2026, 9, 28), SEG_1, pid)
    assert pedido.value.tipo == "operacao.presenca.alterar_confirmada"
    motivo = "Faltou e a presença foi lançada por engano"
    sid = op.turnos.solicitar_alteracao_confirmada(recepcao, date(2026, 9, 28), SEG_1, pid, False, motivo)
    assert marcas(engine_web) == []  # pendente: nada mudou ainda
    assert op.autorizacoes.aprovar(admin, sid) == "executada"
    assert marcas(engine_web) == [("2026-09", ids["recepcao"], ids["admin"], motivo, bytes.fromhex(sid))]
    balanco = op.frequencia.balanco(recepcao, pid, "2026-09")
    assert (balanco.previstas, balanco.ausencias_nao_compensadas) == (2, 1)  # 28 e 30, primeiro turno

    # A administração pede e aprova na hora (P-01); reabrir alcança o mês ainda fechado e o reabre.
    op.turnos.solicitar_reabertura(admin, date(2026, 9, 29), TER_1, "Conferência do turno")
    assert [m[0] for m in marcas(engine_web)] == ["2026-09", "2026-09"]
    assert op.frequencia.balanco(recepcao, pid, "2026-09").provisorio  # reaberto (DD-26)

    # Em mês aberto, a mesma alteração não gera marca.
    confirmar(op, ids, date(2026, 10, 12), SEG_1)
    op.turnos.solicitar_alteracao_confirmada(admin, date(2026, 10, 12), SEG_1, pid, False, "Faltou")
    assert len(marcas(engine_web)) == 2


@pytest.mark.requisito("RF-402", "DD-26")
def test_alocacao_retroativa_e_cancelamento_de_troca_realizada_por_autorizacao(
    op: Operacao, operacao_zerada: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    ids = operacao_zerada
    enfermeira, admin = contexto(ids, "enfermagem", Perfil.ENFERMAGEM), contexto(ids, "admin", Perfil.ADMINISTRACAO)
    pid = alocado(op, ids, fabrica)
    troca = op.escalas.registrar_troca(enfermeira, pid, date(2026, 9, 30), date(2026, 9, 29), TER_1)
    fechar_setembro(op, ids)

    with pytest.raises(RequerAutorizacao):
        op.escalas.alocar(enfermeira, pid, TER_1, date(2026, 9, 29))
    sid = op.escalas.solicitar_alocacao_retroativa(enfermeira, pid, TER_1, date(2026, 9, 29), "Escala errada")
    op.autorizacoes.aprovar(admin, sid)
    assert op.escalas.contagem(pessoa(ids), date(2026, 10, 13)).por_escala[TER_1] == 1
    assert [m[0] for m in marcas(engine_web)] == ["2026-09"]

    with pytest.raises(RequerAutorizacao) as pedido:
        op.escalas.cancelar_troca(enfermeira, troca)
    assert pedido.value.tipo == "operacao.troca.cancelar_realizada"
    sid = op.escalas.solicitar_cancelamento_troca(enfermeira, troca, "Troca registrada no paciente errado")
    op.autorizacoes.aprovar(admin, sid)
    with engine_web.connect() as c:
        assert c.execute(text("SELECT cancelada_em IS NOT NULL FROM troca_pontual")).scalar_one() == 1
    assert len(marcas(engine_web)) == 2
    with pytest.raises(AcessoNegado):  # a enfermagem não pede reabertura de sessão (matriz §4.3)
        op.turnos.solicitar_reabertura(enfermeira, date(2026, 9, 28), SEG_1, "x")


# ------------------------------------------------------------------ pareamento e balanço (RF-916, RF-918)
@pytest.mark.requisito("RF-918", "RF-916", "DD-25")
def test_pareamento_do_mes_e_refazer_em_mes_aberto(
    op: Operacao, operacao_zerada: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    ids = operacao_zerada
    recepcao = pessoa(ids)
    pid = alocado(op, ids, fabrica, escala=TER_1)
    for dia in (6, 8):  # duas ausências nas terças e quintas dele
        data = date(2026, 10, dia)
        versao = op.turnos.marcar_ausencia(contexto(ids, "recepcao", Perfil.RECEPCAO, local(data, 9)), data, TER_1, pid)
        op.turnos.confirmar(contexto(ids, "recepcao", Perfil.RECEPCAO, local(data, 9, 5)), data, TER_1, versao)
    for dia in (7, 9):  # e duas presenças fora da escala
        data = date(2026, 10, dia)
        op.turnos.acrescentar_paciente(contexto(ids, "recepcao", Perfil.RECEPCAO, local(data, 7)), data, SEG_1, pid)

    automatico = op.frequencia.pareamento_do_mes(recepcao, pid, "2026-10")
    assert [(p.ausencia.data.day, p.presenca.data.day, p.origem) for p in automatico.pares] == [
        (6, 7, OrigemPar.AUTOMATICO), (8, 9, OrigemPar.AUTOMATICO)
    ]  # fmt: skip
    assert not automatico.mes_fechado and automatico.balanco.reposicoes == 2 and automatico.balanco.extras == 0

    ausencia_6, presenca_9 = automatico.pares[0].ausencia.presenca_id, automatico.pares[1].presenca.presenca_id
    assert ausencia_6 is not None and presenca_9 is not None  # confirmadas e acrescentadas: linhas gravadas
    op.frequencia.refazer(recepcao, pid, "2026-10", [(ausencia_6, presenca_9)])  # o automático junta 08 com 07
    refeito = op.frequencia.pareamento_do_mes(recepcao, pid, "2026-10")
    assert [(p.ausencia.data.day, p.presenca.data.day, p.origem) for p in refeito.pares] == [
        (6, 9, OrigemPar.MANUAL), (8, 7, OrigemPar.AUTOMATICO)
    ]  # fmt: skip
    with pytest.raises(RegraViolada) as erro:
        op.frequencia.refazer(recepcao, pid, "2026-10", [(presenca_9, ausencia_6)])  # lados invertidos
    assert erro.value.codigo == "ligacao.invalida"
    with pytest.raises(AcessoNegado):
        op.frequencia.refazer(contexto(ids, "admin", Perfil.VISUALIZADOR), pid, "2026-10", [])
    with engine_web.connect() as c:
        sql = "SELECT alteracoes FROM auditoria WHERE operacao = 'operacao.pareamento.refazer'"
        assert c.execute(text(sql)).scalar_one().startswith('{"competencia":[null,"2026-10"],"ligacoes":["",')


@pytest.mark.requisito("DD-26", "RF-918", "CT-FRQ-10")
def test_refazer_em_mes_fechado_so_por_autorizacao_e_com_marca(
    op: Operacao, operacao_zerada: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    ids = operacao_zerada
    recepcao, admin = pessoa(ids), contexto(ids, "admin", Perfil.ADMINISTRACAO)
    pid = alocado(op, ids, fabrica)
    fechar_setembro(op, ids)
    with pytest.raises(RequerAutorizacao) as pedido:
        op.frequencia.refazer(recepcao, pid, "2026-09", [])
    assert pedido.value.tipo == "operacao.pareamento.refazer"
    sid = op.frequencia.solicitar_refazer(recepcao, pid, "2026-09", [], "Conferência do faturamento")
    op.autorizacoes.aprovar(admin, sid)  # sem ligações para trocar: nada muda, mas a aprovação alcançou o mês
    assert [m[0] for m in marcas(engine_web)] == ["2026-09"]
    with pytest.raises(RegraViolada):
        op.frequencia.balanco(recepcao, pid, "2026-13")


# ------------------------------------------------------------------ ciência da enfermagem (RF-921)
@pytest.mark.requisito("RF-921", "DEC-48")
def test_enfermagem_da_ciencia_da_presenca_acrescentada(
    op: Operacao, operacao_zerada: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    ids = operacao_zerada
    enfermeira = contexto(ids, "enfermagem", Perfil.ENFERMAGEM)
    alocado_seg, alocado_ter = alocado(op, ids, fabrica), alocado(op, ids, fabrica, escala=TER_1)
    segunda = date(2026, 10, 12)
    op.turnos.acrescentar_paciente(contexto(ids, "recepcao", Perfil.RECEPCAO, local(segunda, 7)), segunda, SEG_1,
                                   alocado_ter)  # fmt: skip
    with engine_web.connect() as c:
        sql = "SELECT id FROM presenca WHERE paciente_id = :p"
        acrescentada = c.execute(text(sql), {"p": alocado_ter}).scalar_one()
    with pytest.raises(AcessoNegado):
        op.frequencia.dar_ciencia(pessoa(ids), acrescentada)
    op.frequencia.dar_ciencia(enfermeira, acrescentada)
    with pytest.raises(RegraViolada) as erro:
        op.frequencia.dar_ciencia(enfermeira, acrescentada)
    assert erro.value.codigo == "ciencia.ja_registrada"
    confirmar = contexto(ids, "recepcao", Perfil.RECEPCAO, local(segunda, 9))
    op.turnos.confirmar(confirmar, segunda, SEG_1, op.turnos.tela_do_turno(confirmar, segunda, SEG_1).versao)
    with engine_web.connect() as c:
        regular = c.execute(text("SELECT id FROM presenca WHERE paciente_id = :p"), {"p": alocado_seg}).scalar_one()
    with pytest.raises(RegraViolada) as erro:
        op.frequencia.dar_ciencia(enfermeira, regular)  # presença na própria escala: nada a cientificar
    assert erro.value.codigo == "ciencia.desnecessaria"
