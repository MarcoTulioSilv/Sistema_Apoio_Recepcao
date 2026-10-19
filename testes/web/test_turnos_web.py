"""Tela inicial com as sessões de turno, pela web e com o banco (DD-76, DD-24, DD-32, DD-57, DD-91, RF-909).

O relógio é o de segunda, 19/10/2026; o primeiro turno vai das 06h às 10h. A implantação é o próprio dia 19, para
não haver sessões anteriores sem confirmação (o painel as mostra, como manda a DD-76).
"""

from __future__ import annotations

import re
from datetime import date, datetime

import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, text
from werkzeug.test import TestResponse

from sar.modulo_08_dados.relogio import FUSO_CLINICA
from testes.apoio.acesso import CriarUsuario
from testes.apoio.cadastro import INICIO, dados_completos, pessoa
from testes.apoio.fabrica import Fabrica
from testes.apoio.operacao import definir_implantacao, pacientes_no_turno
from testes.apoio.operacao import montar as montar_operacao
from testes.apoio.relogio_controlado import RelogioControlado
from testes.apoio.web import ORIGEM, get, logado, montar

pytestmark = pytest.mark.integracao

SEGUNDA = date(2026, 10, 19)
SESSAO = "/turnos/2026-10-19/1"


def as_(hora: int, minuto: int = 0) -> datetime:
    return datetime(2026, 10, 19, hora, minuto, tzinfo=FUSO_CLINICA)


def htmx(c: FlaskClient, caminho: str, dados: dict[str, str]) -> TestResponse:
    return c.post(caminho, data=dados, base_url=ORIGEM, headers={"Origin": ORIGEM, "HX-Request": "true"})


@pytest.fixture
def relogio() -> RelogioControlado:
    return RelogioControlado(as_(5, 30))


@pytest.fixture
def pacientes(
    operacao_zerada: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> list[tuple[int, str]]:
    """Três pacientes no primeiro turno de segunda, quarta e sexta."""
    definir_implantacao(engine_migracao, SEGUNDA, operacao_zerada["ti"])
    return pacientes_no_turno(engine_web, operacao_zerada, fabrica, 3, 1, INICIO)


def cliente(engine: Engine, criar_usuario: CriarUsuario, relogio: RelogioControlado, perfil: str) -> FlaskClient:
    login = f"webturno_{perfil[:5]}"
    criar_usuario(login, perfil=perfil)
    return logado(montar(engine, relogio=relogio), login)


def situacoes(engine: Engine) -> dict[int, str]:
    with engine.connect() as c:
        return {p: s for p, s in c.execute(text("SELECT paciente_id, situacao FROM presenca"))}


def versao(html: str) -> str:
    achado = re.search(r'name="versao" value="(\d+)"', html)
    assert achado, html[:300]
    return achado.group(1)


@pytest.mark.requisito("DD-76", "RF-502", "P-13", "DD-24", "DD-32", "CT-FRQ-03")
def test_preparacao_marcacao_e_confirmacao_pela_tela_inicial(
    pacientes: list[tuple[int, str]], criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    recepcao = cliente(engine_web, criar_usuario, relogio, "recepcao")
    inicio = get(recepcao, "/").get_data(as_text=True)
    assert "Primeiro turno" in inicio and "Em preparação" in inicio and 'data-estado="preparacao"' in inicio
    assert all(nome in inicio for _, nome in pacientes) and inicio.count(">Mover para faltantes<") == 3
    assert "Aniversariantes de hoje" in inicio and 'hx-trigger="every 60s"' in inicio

    pid, nome = pacientes[0]
    parcial = htmx(recepcao, f"{SESSAO}/presenca", {"paciente_id": str(pid), "presente": "0"}).get_data(as_text=True)
    assert "<html" not in parcial and "Avisou que vai faltar" in parcial  # só o painel, com o motivo da falta
    assert f'data-focar="paciente-2026-10-19-1-{pid}"' in parcial
    assert situacoes(engine_web) == {pid: "ausente"}  # só a exceção (DD-24)
    assert f"Mover para presentes: {nome}" in parcial

    relogio.ajustar(as_(8, 0))
    recepcao = logado(montar(engine_web, relogio=relogio), "webturno_recep")
    aberta = get(recepcao, "/").get_data(as_text=True)
    assert 'data-estado="aberta"' in aberta and "Liberada na última hora do turno" in aberta
    cedo = htmx(recepcao, f"{SESSAO}/confirmar", {"versao": versao(aberta)}).get_data(as_text=True)
    assert "A confirmação é liberada na última hora do turno." in cedo

    relogio.ajustar(as_(9, 5))
    recepcao = logado(montar(engine_web, relogio=relogio), "webturno_recep")
    liberada = get(recepcao, "/").get_data(as_text=True)
    feita = htmx(recepcao, f"{SESSAO}/confirmar", {"versao": versao(liberada)}).get_data(as_text=True)
    assert "Sessão confirmada." in feita
    assert sorted(situacoes(engine_web).values()) == ["ausente", "presente", "presente"]


@pytest.mark.requisito("DD-17", "CT-FRQ-04")
def test_confirmar_com_a_tela_desatualizada_avisa_e_mostra_a_lista_nova(
    pacientes: list[tuple[int, str]], criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    relogio.ajustar(as_(9, 5))
    recepcao = cliente(engine_web, criar_usuario, relogio, "recepcao")
    antiga = versao(get(recepcao, "/").get_data(as_text=True))
    htmx(recepcao, f"{SESSAO}/presenca", {"paciente_id": str(pacientes[1][0]), "presente": "0"})
    conflito = htmx(recepcao, f"{SESSAO}/confirmar", {"versao": antiga}).get_data(as_text=True)
    assert "Outra estação mudou esta sessão" in conflito
    assert situacoes(engine_web) == {pacientes[1][0]: "ausente"}  # nada confirmado


@pytest.mark.requisito("RF-917", "DD-25", "DD-90")
def test_acrescentar_paciente_pela_busca(
    pacientes: list[tuple[int, str]],
    criar_usuario: CriarUsuario,
    engine_web: Engine,
    relogio: RelogioControlado,
    operacao_zerada: dict[str, int],
    fabrica: Fabrica,
) -> None:
    op = montar_operacao(engine_web)
    dados = dados_completos(fabrica)
    outro = op.cadastro.pacientes.criar(pessoa(operacao_zerada), dados, INICIO)  # sem alocação
    relogio.ajustar(as_(7, 0))
    recepcao = cliente(engine_web, criar_usuario, relogio, "recepcao")
    assert "Digite ao menos 3" in htmx(recepcao, f"{SESSAO}/candidatos", {"termo": "ab"}).get_data(as_text=True)
    achados = htmx(recepcao, f"{SESSAO}/candidatos", {"termo": (dados.nome or "")[:6]}).get_data(as_text=True)
    assert f'name="paciente_id" value="{outro}"' in achados
    escolha = htmx(recepcao, f"{SESSAO}/escolher", {"paciente_id": str(outro), "nome": dados.nome or ""})
    assert "Nenhuma ausência a compensar" in escolha.get_data(as_text=True)
    feito = htmx(recepcao, f"{SESSAO}/acrescentar", {"paciente_id": str(outro), "ausencia_id": ""})
    html = feito.get_data(as_text=True)
    assert "Paciente acrescentado à sessão." in html and "Acrescentado pela recepção" in html
    assert situacoes(engine_web) == {outro: "presente"}
    with engine_web.connect() as c:  # a filtragem enquanto se digita não vai para a trilha (DD-90)
        sql = "SELECT COUNT(*) FROM auditoria WHERE operacao = 'cadastro.paciente.buscar'"
        assert c.execute(text(sql)).scalar_one() == 0
    retirado = htmx(recepcao, f"{SESSAO}/retirar", {"paciente_id": str(outro)}).get_data(as_text=True)
    assert "Paciente retirado da sessão." in retirado and situacoes(engine_web) == {}


@pytest.mark.requisito("P-12", "RF-507")
def test_administracao_registra_sessao_nao_realizada(
    pacientes: list[tuple[int, str]], criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    relogio.ajustar(as_(7, 0))
    admin = cliente(engine_web, criar_usuario, relogio, "administracao")
    assert "A sessão não aconteceu" in get(admin, "/").get_data(as_text=True)
    sem_motivo = htmx(admin, f"{SESSAO}/nao-realizada", {"motivo": " "}).get_data(as_text=True)
    assert "Informe o motivo." in sem_motivo
    feito = htmx(admin, f"{SESSAO}/nao-realizada", {"motivo": "Falta de energia"}).get_data(as_text=True)
    assert "registrada como não realizada" in feito and "Primeiro turno" not in feito  # saiu do painel


@pytest.mark.requisito("CT-ACE-01", "DD-76", "RNF-625")
def test_quem_ve_e_quem_mexe_nos_quadros(
    pacientes: list[tuple[int, str]], criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    for perfil in ("visualizador", "enfermagem"):
        c = cliente(engine_web, criar_usuario, relogio, perfil)
        html = get(c, "/").get_data(as_text=True)
        assert "Primeiro turno" in html and 'data-travado="true"' in html and "Mover para" not in html
        assert "Aniversariantes de hoje" not in html  # só recepção e administração (§4.5)
        resposta = htmx(c, f"{SESSAO}/presenca", {"paciente_id": str(pacientes[0][0]), "presente": "0"})
        assert resposta.status_code == 403
    ti = cliente(engine_web, criar_usuario, relogio, "ti")
    html = get(ti, "/").get_data(as_text=True)
    assert "Bem-vindo ao SAR" in html and pacientes[0][1] not in html  # o TI nunca recebe dado de paciente
    assert get(ti, "/turnos/painel").get_data(as_text=True).strip() == ""


@pytest.mark.requisito("DD-91")
def test_sem_data_de_implantacao_a_tela_avisa(
    pacientes: list[tuple[int, str]],
    criar_usuario: CriarUsuario,
    engine_web: Engine,
    engine_migracao: Engine,
    relogio: RelogioControlado,
    operacao_zerada: dict[str, int],
) -> None:
    definir_implantacao(engine_migracao, None, operacao_zerada["ti"])
    recepcao = cliente(engine_web, criar_usuario, relogio, "recepcao")
    html = get(recepcao, "/").get_data(as_text=True)
    assert "Data de implantação não definida" in html and "Primeiro turno" not in html


@pytest.mark.requisito("DD-57")
def test_atualizacao_automatica_devolve_so_o_painel(
    pacientes: list[tuple[int, str]], criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    recepcao = cliente(engine_web, criar_usuario, relogio, "recepcao")
    resposta = recepcao.get("/turnos/painel", base_url=ORIGEM, headers={"X-SAR-Automatica": "1"})
    html = resposta.get_data(as_text=True)
    assert resposta.status_code == 200 and "<html" not in html and "Primeiro turno" in html


@pytest.mark.requisito("DD-76", "DD-23")
def test_sessoes_anteriores_sem_confirmacao_aparecem_em_urgencia(
    pacientes: list[tuple[int, str]],
    criar_usuario: CriarUsuario,
    engine_web: Engine,
    engine_migracao: Engine,
    relogio: RelogioControlado,
    operacao_zerada: dict[str, int],
) -> None:
    definir_implantacao(engine_migracao, date(2026, 10, 15), operacao_zerada["ti"])  # quinta
    recepcao = cliente(engine_web, criar_usuario, relogio, "recepcao")
    html = get(recepcao, "/").get_data(as_text=True)
    assert html.count('data-estado="vencida"') == 2  # as duas mais antigas com quadro
    assert "Mais 7 sessões de dias anteriores sem confirmação" in html  # 15, 16 e 17: nove ao todo
    assert 'href="/turnos/2026-10-17/6"' in html
    avulsa = get(recepcao, "/turnos/2026-10-17/6").get_data(as_text=True)
    assert "Sessão de 17/10/2026" in avulsa and "Aguardando confirmação" in avulsa
