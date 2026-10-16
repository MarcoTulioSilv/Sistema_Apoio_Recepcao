"""Sessão de turno com o banco (DDS §7.3): CT-FRQ-03, CT-FRQ-04, P-12, P-13, DD-24, DD-30, DD-32, DD-76, DD-91.

A sessão de referência é a de segunda, 19/10/2026, no primeiro turno (1-seg, 06h às 10h): preparação às 05h e
confirmação liberada às 09h. A implantação é 01/10.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date, datetime

import pytest
from sqlalchemy import Engine, text

from sar.modulo_03_operacao.contrato import EstadoSessao, Origem
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado, ConflitoDeVersao, RegraViolada, RequerAutorizacao
from testes.apoio.cadastro import INICIO, dados_completos, pessoa
from testes.apoio.fabrica import Fabrica
from testes.apoio.operacao import Operacao, contexto, definir_implantacao, local, montar

pytestmark = pytest.mark.integracao

SEG_1, TER_1, SEG_2 = 1, 2, 3
SEGUNDA = date(2026, 10, 19)


@pytest.fixture
def op(engine_web: Engine, engine_migracao: Engine, operacao_zerada: dict[str, int]) -> Operacao:
    definir_implantacao(engine_migracao, INICIO, operacao_zerada["ti"])
    return montar(engine_web)


def as_(
    ids: dict[str, int], hora: int, minuto: int = 0, perfil: Perfil = Perfil.RECEPCAO, dia: date = SEGUNDA
) -> Contexto:
    chave = {Perfil.RECEPCAO: "recepcao", Perfil.ADMINISTRACAO: "admin", Perfil.TI: "ti"}.get(perfil, "enfermagem")
    return contexto(ids, chave, perfil, local(dia, hora, minuto))


def alocados(op: Operacao, ids: dict[str, int], fabrica: Fabrica, quantos: int, escala: int = SEG_1) -> list[int]:
    enfermeira = contexto(ids, "enfermagem", Perfil.ENFERMAGEM)
    criados = []
    for _ in range(quantos):
        pid = op.cadastro.pacientes.criar(pessoa(ids), dados_completos(fabrica), INICIO)
        op.escalas.alocar(enfermeira, pid, escala, INICIO)
        criados.append(pid)
    return criados


def presencas(engine: Engine) -> dict[int, str]:
    with engine.connect() as c:
        return dict(c.execute(text("SELECT paciente_id, situacao FROM presenca")).all())  # type: ignore[arg-type]


# ------------------------------------------------------------------ CT-FRQ-03
@pytest.mark.requisito("CT-FRQ-03", "DD-24", "INV-14", "P-13", "RF-502", "RF-922")
def test_confirmacao_materializa_todas_as_presencas_e_antes_so_ha_excecoes(
    op: Operacao, operacao_zerada: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    ids = operacao_zerada
    a, b, c = alocados(op, ids, fabrica, 3)
    tela = op.turnos.tela_do_turno(as_(ids, 5, 30), SEGUNDA, SEG_1)
    assert tela.estado is EstadoSessao.EM_PREPARACAO and tela.versao == 0
    assert [(p.paciente_id, p.presente, p.origem) for p in sorted(tela.pacientes, key=lambda p: p.paciente_id)] == [
        (a, True, Origem.ALOCADO), (b, True, Origem.ALOCADO), (c, True, Origem.ALOCADO)
    ]  # fmt: skip
    assert op.turnos.proximo_turno(as_(ids, 5, 30)) == tela  # RF-922: o próximo turno, na preparação
    with engine_web.connect() as conexao:  # ver a tela não grava nada (DD-23)
        assert conexao.execute(text("SELECT COUNT(*) FROM sessao_turno")).scalar_one() == 0

    with pytest.raises(RegraViolada) as erro:
        op.turnos.marcar_ausencia(as_(ids, 4, 59), SEGUNDA, SEG_1, c)  # antes da preparação (P-13)
    assert erro.value.codigo == "sessao.fora_da_marcacao"
    versao = op.turnos.marcar_ausencia(as_(ids, 5, 0), SEGUNDA, SEG_1, c)  # ausência avisada
    assert presencas(engine_web) == {c: "ausente"}  # só a exceção (DD-24, INV-14)

    with pytest.raises(RegraViolada) as erro:
        op.turnos.confirmar(as_(ids, 8, 59), SEGUNDA, SEG_1, versao)  # antes da última hora (DD-32)
    assert erro.value.codigo == "sessao.confirmacao_nao_liberada"
    op.turnos.confirmar(as_(ids, 9, 0), SEGUNDA, SEG_1, versao)
    assert presencas(engine_web) == {a: "presente", b: "presente", c: "ausente"}
    depois = op.turnos.tela_do_turno(as_(ids, 9, 1), SEGUNDA, SEG_1)
    assert depois.estado is EstadoSessao.CONFIRMADA
    with pytest.raises(RequerAutorizacao) as autorizacao:
        op.turnos.desmarcar(as_(ids, 9, 2), SEGUNDA, SEG_1, c)
    assert autorizacao.value.tipo == "operacao.presenca.alterar_confirmada"
    with engine_web.connect() as conexao:
        sql = "SELECT usuario_id, alteracoes FROM auditoria WHERE operacao = 'operacao.sessao.confirmar'"
        registros = [tuple(r) for r in conexao.execute(text(sql))]
        assert registros == [(ids["recepcao"], '{"ausentes":[null,1],"presentes":[null,2]}')]


@pytest.mark.requisito("P-10", "DD-24")
def test_troca_saindo_vem_ausente_e_desmarcar_volta_a_exigir_so_a_excecao(
    op: Operacao, operacao_zerada: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    ids = operacao_zerada
    [pid] = alocados(op, ids, fabrica, 1)
    op.escalas.registrar_troca(contexto(ids, "enfermagem", Perfil.ENFERMAGEM), pid, SEGUNDA, date(2026, 10, 20), TER_1)
    [item] = op.turnos.tela_do_turno(as_(ids, 6), SEGUNDA, SEG_1).pacientes
    assert (item.origem, item.presente, item.marcado) == (Origem.TROCA_SAINDO, False, False)
    op.turnos.desmarcar(as_(ids, 6), SEGUNDA, SEG_1, pid)  # veio mesmo assim
    assert presencas(engine_web) == {pid: "presente"}
    op.turnos.marcar_ausencia(as_(ids, 6), SEGUNDA, SEG_1, pid)  # de volta ao padrão da troca: sem exceção
    assert presencas(engine_web) == {}
    with pytest.raises(RegraViolada) as erro:
        op.turnos.marcar_ausencia(as_(ids, 10, 30), SEGUNDA, SEG_2, pid)  # o segundo turno, já em preparação
    assert erro.value.codigo == "paciente.fora_da_lista"


# ------------------------------------------------------------------ CT-FRQ-04
@pytest.mark.requisito("CT-FRQ-04", "DD-17")
@pytest.mark.parametrize("com_marcacao", [False, True])
def test_duas_estacoes_confirmam_ao_mesmo_tempo_e_so_uma_consegue(
    op: Operacao, operacao_zerada: dict[str, int], engine_web: Engine, fabrica: Fabrica, com_marcacao: bool
) -> None:
    ids = operacao_zerada
    a, _ = alocados(op, ids, fabrica, 2)
    versao = op.turnos.marcar_ausencia(as_(ids, 9, 5), SEGUNDA, SEG_1, a) if com_marcacao else 0
    largada = threading.Barrier(2)
    resultados: list[str] = []

    def estacao() -> None:
        largada.wait()
        try:
            montar(engine_web).turnos.confirmar(as_(ids, 9, 10), SEGUNDA, SEG_1, versao)
            resultados.append("confirmou")
        except ConflitoDeVersao:
            resultados.append("conflito")

    linhas = [threading.Thread(target=estacao) for _ in range(2)]
    for linha in linhas:
        linha.start()
    for linha in linhas:
        linha.join(timeout=30)
    assert sorted(resultados) == ["confirmou", "conflito"]
    with engine_web.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM presenca")).scalar_one() == 2  # gravadas uma vez só


@pytest.mark.requisito("DD-17")
def test_confirmar_tela_antiga_depois_de_outra_marcacao_e_conflito(
    op: Operacao, operacao_zerada: dict[str, int], fabrica: Fabrica
) -> None:
    ids = operacao_zerada
    a, b = alocados(op, ids, fabrica, 2)
    lida = op.turnos.tela_do_turno(as_(ids, 9, 5), SEGUNDA, SEG_1).versao
    op.turnos.marcar_ausencia(as_(ids, 9, 6), SEGUNDA, SEG_1, b)  # outra estação
    with pytest.raises(ConflitoDeVersao):
        op.turnos.confirmar(as_(ids, 9, 7), SEGUNDA, SEG_1, lida)
    assert a != b


# ------------------------------------------------------------------ acréscimo (RF-917, RF-506, DD-25)
@pytest.mark.requisito("RF-917", "DD-25", "INV-04", "RF-921")
def test_acrescentar_mostra_as_ausencias_do_mes_e_liga_a_escolhida(
    op: Operacao, operacao_zerada: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    ids = operacao_zerada
    [pid] = alocados(op, ids, fabrica, 1, escala=TER_1)
    terca = date(2026, 10, 13)
    versao = op.turnos.marcar_ausencia(as_(ids, 9, 0, dia=terca), terca, TER_1, pid)
    op.turnos.confirmar(as_(ids, 9, 30, dia=terca), terca, TER_1, versao)

    antes = op.turnos.frequencia_ao_acrescentar(as_(ids, 6), pid, SEGUNDA)
    ausencia = next(a for a in antes.ausencias if a.data == terca)
    assert ausencia.presenca_id is not None and ausencia.livre and antes.extras_no_mes == 0
    depois = op.turnos.acrescentar_paciente(as_(ids, 6), SEGUNDA, SEG_1, pid, ausencia.presenca_id)
    assert not next(a for a in depois.ausencias if a.data == terca).livre  # compensada pela ligação
    [item] = op.turnos.tela_do_turno(as_(ids, 6), SEGUNDA, SEG_1).pacientes
    assert (item.origem, item.presente, item.marcado) == (Origem.ACRESCENTADO, True, True)
    with engine_web.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM ligacao_manual")).scalar_one() == 1

    with pytest.raises(RegraViolada) as erro:
        op.turnos.acrescentar_paciente(as_(ids, 6), SEGUNDA, SEG_1, pid)
    assert erro.value.codigo == "paciente.ja_na_lista"
    with pytest.raises(RegraViolada) as erro:  # a mesma ausência não liga duas presenças
        op.turnos.acrescentar_paciente(as_(ids, 10, 30), SEGUNDA, SEG_2, pid, ausencia.presenca_id)
    assert erro.value.codigo == "ligacao.invalida"
    tardio = op.cadastro.pacientes.criar(pessoa(ids), dados_completos(fabrica), date(2026, 10, 25))
    with pytest.raises(RegraViolada) as erro:
        op.turnos.acrescentar_paciente(as_(ids, 6), SEGUNDA, SEG_1, tardio)
    assert erro.value.codigo == "INV-04"
    op.turnos.retirar_acrescentado(as_(ids, 6), SEGUNDA, SEG_1, pid)  # engano desfeito, com a ligação
    with engine_web.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM ligacao_manual")).scalar_one() == 0


@pytest.mark.requisito("RF-506", "RN-01")
def test_acrescentar_avisa_com_quatro_extras_no_mes_sem_bloquear(
    op: Operacao, operacao_zerada: dict[str, int], fabrica: Fabrica
) -> None:
    ids = operacao_zerada
    [pid] = alocados(op, ids, fabrica, 1, escala=TER_1)
    for dia in (5, 7, 9, 12):  # segundas, quartas e sextas: fora da escala dele
        data = date(2026, 10, dia)
        op.turnos.acrescentar_paciente(as_(ids, 7, dia=data), data, SEG_1, pid)
    frequencia = op.turnos.frequencia_ao_acrescentar(as_(ids, 6), pid, SEGUNDA)
    assert (frequencia.extras_no_mes, frequencia.aviso_extra) == (4, True)
    quinta = op.turnos.acrescentar_paciente(as_(ids, 6), SEGUNDA, SEG_1, pid)  # avisa, nunca bloqueia
    assert quinta.extras_no_mes == 5


# ------------------------------------------------------------------ não realizada (P-12)
@pytest.mark.requisito("P-12", "RF-507", "DEC-66")
def test_sessao_nao_realizada_so_pela_administracao_e_sem_presencas(
    op: Operacao, operacao_zerada: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    ids = operacao_zerada
    a, _ = alocados(op, ids, fabrica, 2)
    op.turnos.marcar_ausencia(as_(ids, 6), SEGUNDA, SEG_1, a)
    with pytest.raises(AcessoNegado):
        op.turnos.registrar_nao_realizada(as_(ids, 7), SEGUNDA, SEG_1, "falta de energia")
    admin = as_(ids, 7, perfil=Perfil.ADMINISTRACAO)
    for codigo, quando, motivo in (("sessao.futura", 5, "falta de energia"), ("motivo.obrigatorio", 7, "   ")):
        with pytest.raises(RegraViolada) as erro:
            op.turnos.registrar_nao_realizada(as_(ids, quando, perfil=Perfil.ADMINISTRACAO), SEGUNDA, SEG_1, motivo)
        assert erro.value.codigo == codigo
    op.turnos.registrar_nao_realizada(admin, SEGUNDA, SEG_1, "falta de energia")
    assert presencas(engine_web) == {}
    assert op.turnos.tela_do_turno(admin, SEGUNDA, SEG_1).estado is EstadoSessao.NAO_REALIZADA
    with pytest.raises(RegraViolada) as erro:
        op.turnos.registrar_nao_realizada(admin, SEGUNDA, SEG_1, "de novo")
    assert erro.value.codigo == "sessao.confirmada"


# ------------------------------------------------------------------ painel da tela inicial (DD-76, DD-91)
@pytest.mark.requisito("DD-76", "DD-23", "RF-501")
def test_painel_mostra_as_que_pedem_acao_da_mais_antiga_para_a_mais_nova(
    op: Operacao, operacao_zerada: dict[str, int], engine_migracao: Engine
) -> None:
    ids = operacao_zerada
    definir_implantacao(engine_migracao, date(2026, 10, 17), ids["ti"])  # sábado
    painel = op.turnos.painel(as_(ids, 12))
    assert painel.implantacao_definida
    assert [(s.data.day, s.escala.codigo, s.estado) for s in painel.sessoes] == [
        (17, "1-ter", EstadoSessao.URGENCIA),
        (17, "2-ter", EstadoSessao.URGENCIA),
        (17, "3-ter", EstadoSessao.URGENCIA),
        (19, "1-seg", EstadoSessao.URGENCIA),
        (19, "2-seg", EstadoSessao.DEVIDA),
    ]
    assert len(op.turnos.devidas_nao_confirmadas(as_(ids, 12))) == 5
    assert op.turnos.proximo_turno(as_(ids, 10, 15)) is not None  # o segundo turno, em preparação
    intervalo = op.turnos.painel(as_(ids, 10, 30))  # acabou um, começa a preparação do outro (DD-76)
    assert [s.estado for s in intervalo.sessoes][-2:] == [EstadoSessao.URGENCIA, EstadoSessao.EM_PREPARACAO]


@pytest.mark.requisito("DD-91")
def test_sem_data_de_implantacao_nenhuma_sessao_e_devida(
    op: Operacao, operacao_zerada: dict[str, int], engine_migracao: Engine, fabrica: Fabrica
) -> None:
    ids = operacao_zerada
    [pid] = alocados(op, ids, fabrica, 1)
    definir_implantacao(engine_migracao, None, ids["ti"])
    assert op.turnos.painel(as_(ids, 9)).implantacao_definida is False
    assert op.turnos.devidas_nao_confirmadas(as_(ids, 9)) == [] and op.turnos.proximo_turno(as_(ids, 5, 30)) is None
    chamadas: list[Callable[[], object]] = [
        lambda: op.turnos.tela_do_turno(as_(ids, 9), SEGUNDA, SEG_1),
        lambda: op.turnos.marcar_ausencia(as_(ids, 9), SEGUNDA, SEG_1, pid),
        lambda: op.turnos.confirmar(as_(ids, 9), SEGUNDA, SEG_1, 0),
    ]
    for chamada in chamadas:
        with pytest.raises(RegraViolada) as erro:
            chamada()
        assert erro.value.codigo == "implantacao.indefinida"


@pytest.mark.requisito("CT-ACE-01")
def test_quem_ve_e_quem_marca(op: Operacao, operacao_zerada: dict[str, int], fabrica: Fabrica) -> None:
    ids = operacao_zerada
    [pid] = alocados(op, ids, fabrica, 1)
    for perfil in (Perfil.VISUALIZADOR, Perfil.ENFERMAGEM):
        assert op.turnos.tela_do_turno(as_(ids, 6, perfil=perfil), SEGUNDA, SEG_1).pacientes
        with pytest.raises(AcessoNegado):
            op.turnos.marcar_ausencia(as_(ids, 6, perfil=perfil), SEGUNDA, SEG_1, pid)
    with pytest.raises(AcessoNegado):
        op.turnos.tela_do_turno(as_(ids, 6, perfil=Perfil.TI), SEGUNDA, SEG_1)  # TI não vê dado de paciente
    assert isinstance(local(SEGUNDA, 6), datetime)
