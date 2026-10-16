"""Escalas da enfermagem com o banco (DDS §7.7): RF-402 a RF-406, INV-01, INV-03, P-11, DD-27 e DD-51.

O relógio dos contextos é terça, 13/10/2026, às 10h; os pacientes começam o tratamento em 01/10.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import Engine, text

from sar.composicao import VERIFICADORES_USO
from sar.modulo_01_acesso.servicos import ServicoAuditoria
from sar.modulo_02_cadastro.contrato import TipoEvento
from sar.modulo_06_configuracao.servicos import ServicoConfiguracao
from sar.nucleo.contexto import Perfil
from sar.nucleo.erros import AcessoNegado, NaoEncontrado, RegraViolada, RequerAutorizacao
from testes.apoio.cadastro import INICIO, dados_completos, pessoa
from testes.apoio.fabrica import Fabrica
from testes.apoio.operacao import Operacao, confirmar_direto, contexto, definir_implantacao, montar

pytestmark = pytest.mark.integracao

SEG_1, TER_1, SEG_2, TER_2 = 1, 2, 3, 4  # ids das escalas 1-seg, 1-ter, 2-seg e 2-ter (0002)


def d(dia: int) -> date:
    return date(2026, 10, dia)


@pytest.fixture
def op(engine_web: Engine) -> Operacao:
    return montar(engine_web)


def paciente(op: Operacao, ids: dict[str, int], fabrica: Fabrica, inicio: date = INICIO) -> int:
    return op.cadastro.pacientes.criar(pessoa(ids), dados_completos(fabrica), inicio)


def auditoria(engine: Engine, operacao: str) -> list[tuple[int, str]]:
    with engine.connect() as c:
        sql = "SELECT usuario_id, alteracoes FROM auditoria WHERE operacao = :o ORDER BY id"
        return [(u, a) for u, a in c.execute(text(sql), {"o": operacao})]


# ------------------------------------------------------------------ alocação
@pytest.mark.requisito("RF-402", "RF-403", "RF-404", "RF-406", "DD-27")
def test_alocar_preserva_as_anteriores_conta_por_escala_e_audita_o_autor(
    op: Operacao, operacao_zerada: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    enfermeira = contexto(operacao_zerada, "enfermagem", Perfil.ENFERMAGEM)
    a, b, sem = (paciente(op, operacao_zerada, fabrica) for _ in range(3))
    op.escalas.alocar(enfermeira, a, SEG_1, INICIO)
    op.escalas.alocar(enfermeira, b, TER_2, INICIO)
    op.escalas.alocar(enfermeira, a, SEG_1, d(5))  # a mesma escala que já vale: nada muda (DD-10)
    op.escalas.alocar(enfermeira, a, SEG_2, d(19))  # muda daqui em diante; a de 01/10 continua (RF-402)

    recepcao = pessoa(operacao_zerada)
    antes = op.escalas.contagem(recepcao, d(13))
    assert (antes.por_escala[SEG_1], antes.por_escala[TER_2], antes.por_escala[SEG_2], antes.sem_alocacao) == (
        1,
        1,
        0,
        1,
    )
    depois = op.escalas.contagem(recepcao, d(20))
    assert (depois.por_escala[SEG_1], depois.por_escala[SEG_2]) == (0, 1)
    assert sem not in (a, b)

    registros = auditoria(engine_web, "operacao.alocacao.registrar")
    assert len(registros) == 3 and {u for u, _ in registros} == {operacao_zerada["enfermagem"]}  # RF-406
    assert '"escala":["1-seg","2-seg"]' in registros[-1][1]
    with engine_web.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM alocacao")).scalar_one() == 3

    op.escalas.alocar(enfermeira, a, None, d(26))  # sem alocação a partir de: fato explícito (RF-403)
    assert op.escalas.contagem(recepcao, d(27)).sem_alocacao == 2


@pytest.mark.requisito("RF-406", "CT-ACE-01")
@pytest.mark.parametrize("perfil", [Perfil.RECEPCAO, Perfil.ADMINISTRACAO, Perfil.VISUALIZADOR, Perfil.TI])
def test_so_a_enfermagem_registra_escalas_trocas_e_extras(
    op: Operacao, operacao_zerada: dict[str, int], fabrica: Fabrica, perfil: Perfil
) -> None:
    pid = paciente(op, operacao_zerada, fabrica)
    outro = contexto(operacao_zerada, "admin", perfil)
    for chamada in (
        lambda: op.escalas.alocar(outro, pid, SEG_1, INICIO),
        lambda: op.escalas.alocar_em_lote(outro, [(pid, SEG_1)], INICIO),
        lambda: op.escalas.registrar_troca(outro, pid, d(14), d(15), TER_1),
        lambda: op.escalas.registrar_extra(outro, pid, d(15), TER_1),
    ):
        with pytest.raises(AcessoNegado):
            chamada()
    if perfil is Perfil.TI:  # o TI nunca recebe dado de paciente, nem a contagem das escalas
        with pytest.raises(AcessoNegado):
            op.escalas.contagem(outro, d(13))
    else:
        assert op.escalas.contagem(outro, d(13)).sem_alocacao == 1


@pytest.mark.requisito("INV-03", "INV-01")
def test_alocacao_exige_periodo_na_data_e_nada_depois_do_obito(
    op: Operacao, operacao_zerada: dict[str, int], fabrica: Fabrica
) -> None:
    enfermeira = contexto(operacao_zerada, "enfermagem", Perfil.ENFERMAGEM)
    pid = paciente(op, operacao_zerada, fabrica, inicio=d(5))
    for codigo, escala, inicio in (("INV-03", SEG_1, d(2)), ("escala.inexistente", 99, d(5))):
        with pytest.raises(RegraViolada) as erro:
            op.escalas.alocar(enfermeira, pid, escala, inicio)
        assert erro.value.codigo == codigo
    op.cadastro.eventos.registrar(pessoa(operacao_zerada), pid, TipoEvento.OBITO, d(9), None)
    with pytest.raises(RegraViolada) as erro:
        op.escalas.alocar(enfermeira, pid, SEG_1, d(10))
    assert erro.value.codigo == "INV-01"
    with pytest.raises(NaoEncontrado):
        op.escalas.alocar(enfermeira, pid + 1000, SEG_1, d(5))


@pytest.mark.requisito("RF-405")
def test_alocar_em_lote_grava_tudo_ou_nada(
    op: Operacao, operacao_zerada: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    enfermeira = contexto(operacao_zerada, "enfermagem", Perfil.ENFERMAGEM)
    a, b = paciente(op, operacao_zerada, fabrica), paciente(op, operacao_zerada, fabrica)
    tardio = paciente(op, operacao_zerada, fabrica, inicio=d(20))
    with pytest.raises(RegraViolada) as erro:
        op.escalas.alocar_em_lote(enfermeira, [(a, SEG_1), (tardio, TER_1)], INICIO)
    assert (erro.value.codigo, erro.value.detalhe) == ("INV-03", {"paciente_id": tardio})
    with engine_web.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM alocacao")).scalar_one() == 0
    op.escalas.alocar_em_lote(enfermeira, [(a, SEG_1), (b, TER_1)], INICIO)
    assert len(auditoria(engine_web, "operacao.alocacao.registrar_em_lote")) == 2


@pytest.mark.requisito("RF-402", "DD-26")
def test_alocacao_que_alcanca_sessao_confirmada_pede_autorizacao(
    op: Operacao, operacao_zerada: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    enfermeira = contexto(operacao_zerada, "enfermagem", Perfil.ENFERMAGEM)
    pid = paciente(op, operacao_zerada, fabrica)
    op.escalas.alocar(enfermeira, pid, SEG_1, INICIO)
    confirmar_direto(engine_web, d(12), SEG_1, operacao_zerada["recepcao"])
    with pytest.raises(RequerAutorizacao) as erro:
        op.escalas.alocar(enfermeira, pid, SEG_2, d(5))
    assert erro.value.tipo == "operacao.alocacao.registrar_retroativa"
    op.escalas.alocar(enfermeira, pid, SEG_2, d(13))  # a partir de hoje, nada confirmado é alcançado


# ------------------------------------------------------------------ troca pontual
@pytest.mark.requisito("RF-503", "P-11", "INV-04", "RF-406")
def test_troca_pontual_regras_e_cancelamento(
    op: Operacao, operacao_zerada: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    enfermeira = contexto(operacao_zerada, "enfermagem", Perfil.ENFERMAGEM)
    pid = paciente(op, operacao_zerada, fabrica)
    op.escalas.alocar(enfermeira, pid, SEG_1, INICIO)  # segunda, quarta e sexta
    recusas = [
        ("P-11", d(30), date(2026, 11, 3), TER_1),
        ("troca.origem_fora_da_escala", d(13), d(15), TER_1),  # terça não é dia dele
        ("troca.destino_na_propria_escala", d(14), d(16), SEG_1),
        ("sessao.inexistente", d(14), d(18), TER_1),  # domingo
        ("escala.inexistente", d(14), d(15), 99),
    ]
    for codigo, origem, destino, escala in recusas:
        with pytest.raises(RegraViolada) as erro:
            op.escalas.registrar_troca(enfermeira, pid, origem, destino, escala)
        assert erro.value.codigo == codigo, codigo

    troca = op.escalas.registrar_troca(enfermeira, pid, d(14), d(15), TER_1)
    with pytest.raises(RegraViolada) as erro:
        op.escalas.registrar_troca(enfermeira, pid, d(14), d(17), TER_1)
    assert erro.value.codigo == "troca.origem_repetida"
    op.escalas.cancelar_troca(enfermeira, troca, "  paciente   remarcou  ")
    with pytest.raises(NaoEncontrado):
        op.escalas.cancelar_troca(enfermeira, troca)
    op.escalas.registrar_troca(enfermeira, pid, d(14), d(17), TER_1)  # cancelada, a origem fica livre
    [(autor, alteracoes)] = auditoria(engine_web, "operacao.troca.cancelar")
    assert autor == operacao_zerada["enfermagem"] and alteracoes == '{"cancelada":[false,true]}'


@pytest.mark.requisito("INV-04", "RN-05")
def test_troca_e_extra_fora_do_periodo_ou_antes_da_implantacao(
    op: Operacao, operacao_zerada: dict[str, int], engine_migracao: Engine, fabrica: Fabrica
) -> None:
    enfermeira = contexto(operacao_zerada, "enfermagem", Perfil.ENFERMAGEM)
    pid = paciente(op, operacao_zerada, fabrica, inicio=d(14))
    op.escalas.alocar(enfermeira, pid, SEG_1, d(14))
    with pytest.raises(RegraViolada) as erro:
        op.escalas.registrar_troca(enfermeira, pid, d(16), d(13), TER_1)
    assert erro.value.codigo == "INV-04"
    with pytest.raises(RegraViolada) as erro:
        op.escalas.registrar_extra(enfermeira, pid, d(13), TER_1)
    assert erro.value.codigo == "INV-04"
    definir_implantacao(engine_migracao, d(20), operacao_zerada["ti"])
    with pytest.raises(RegraViolada) as erro:
        op.escalas.registrar_extra(enfermeira, pid, d(17), TER_1)
    assert erro.value.codigo == "sessao.inexistente"


@pytest.mark.requisito("RF-1008", "DD-26")
def test_troca_que_alcanca_sessao_confirmada_pede_autorizacao(
    op: Operacao, operacao_zerada: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    enfermeira = contexto(operacao_zerada, "enfermagem", Perfil.ENFERMAGEM)
    pid = paciente(op, operacao_zerada, fabrica)
    op.escalas.alocar(enfermeira, pid, SEG_1, INICIO)
    troca = op.escalas.registrar_troca(enfermeira, pid, d(14), d(15), TER_1)
    confirmar_direto(engine_web, d(12), SEG_1, operacao_zerada["recepcao"])
    with pytest.raises(RequerAutorizacao) as erro:
        op.escalas.registrar_troca(enfermeira, pid, d(12), d(13), TER_1)
    assert erro.value.tipo == "operacao.sessao.reabrir"
    confirmar_direto(engine_web, d(15), TER_1, operacao_zerada["recepcao"])
    with pytest.raises(RequerAutorizacao) as erro:
        op.escalas.cancelar_troca(enfermeira, troca)
    assert erro.value.tipo == "operacao.troca.cancelar_realizada"


# ------------------------------------------------------------------ extra planejada
@pytest.mark.requisito("RF-504", "RF-406")
def test_extra_planejada_regras_e_cancelamento(
    op: Operacao, operacao_zerada: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> None:
    enfermeira = contexto(operacao_zerada, "enfermagem", Perfil.ENFERMAGEM)
    pid = paciente(op, operacao_zerada, fabrica)
    op.escalas.alocar(enfermeira, pid, SEG_1, INICIO)
    for codigo, data, escala in (("extra.na_propria_escala", d(14), SEG_1), ("sessao.inexistente", d(14), TER_1)):
        with pytest.raises(RegraViolada) as erro:
            op.escalas.registrar_extra(enfermeira, pid, data, escala)
        assert erro.value.codigo == codigo
    extra = op.escalas.registrar_extra(enfermeira, pid, d(15), TER_1)
    with pytest.raises(RegraViolada) as erro:
        op.escalas.registrar_extra(enfermeira, pid, d(15), TER_1)
    assert erro.value.codigo == "extra.repetida"
    confirmar_direto(engine_web, d(15), TER_1, operacao_zerada["recepcao"])
    with pytest.raises(RequerAutorizacao):
        op.escalas.cancelar_extra(enfermeira, extra)
    with engine_migracao.begin() as c:  # a aplicação nunca apaga sessão; só o teste, para seguir adiante
        c.execute(text("DELETE FROM sessao_turno"))
    op.escalas.cancelar_extra(enfermeira, extra)
    assert len(auditoria(engine_web, "operacao.extra.registrar")) == 1
    assert len(auditoria(engine_web, "operacao.extra.cancelar")) == 1


# ------------------------------------------------------------------ data de implantação (DD-51)
@pytest.mark.requisito("DD-51")
def test_data_de_implantacao_trava_na_primeira_sessao_confirmada(
    op: Operacao, operacao_zerada: dict[str, int], engine_web: Engine
) -> None:
    ti = contexto(operacao_zerada, "ti", Perfil.TI)
    configuracao = ServicoConfiguracao(op.cadastro.executar, ServicoAuditoria(), VERIFICADORES_USO)
    configuracao.alterar_parametro(ti, "data_implantacao", d(1))
    configuracao.alterar_parametro(ti, "data_implantacao", d(5))  # ainda sem sessão confirmada: muda
    confirmar_direto(engine_web, d(12), SEG_1, operacao_zerada["recepcao"])
    with pytest.raises(RegraViolada) as erro:
        configuracao.alterar_parametro(ti, "data_implantacao", d(1))
    assert erro.value.codigo == "parametro.imutavel"
