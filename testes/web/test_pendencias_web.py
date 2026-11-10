"""Pendências e jobs pela web, com o banco (RF-1010, RNF-408, RF-922, DD-30, RF-1004, DD-112).

O relógio é o de segunda, 19/10/2026, às 05h30: o primeiro turno está em preparação. Os pacientes da fábrica vêm sem
sexo nem endereço: têm cadastro incompleto e documentos do checklist faltando.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine

from sar.modulo_08_dados.relogio import FUSO_CLINICA
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.portas import ItemPendencia, Prioridade
from sar.web.rotas_pendencias import POR_TIPO, agrupar
from testes.apoio.acesso import CriarUsuario
from testes.apoio.cadastro import INICIO
from testes.apoio.fabrica import Fabrica
from testes.apoio.operacao import definir_implantacao, pacientes_no_turno
from testes.apoio.relogio_controlado import RelogioControlado
from testes.apoio.web import ORIGEM, get, logado, montar

SEGUNDA = date(2026, 10, 19)


@pytest.fixture
def relogio() -> RelogioControlado:
    return RelogioControlado(datetime(2026, 10, 19, 5, 30, tzinfo=FUSO_CLINICA))


@pytest.fixture
def pacientes(
    operacao_zerada: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> list[tuple[int, str]]:
    definir_implantacao(engine_migracao, SEGUNDA, operacao_zerada["ti"])
    return pacientes_no_turno(engine_web, operacao_zerada, fabrica, 2, 1, INICIO)


def cliente(engine: Engine, criar_usuario: CriarUsuario, relogio: RelogioControlado, perfil: str) -> FlaskClient:
    login = f"webpend_{perfil[:5]}"
    criar_usuario(login, perfil=perfil)
    return logado(montar(engine, relogio=relogio), login)


@pytest.mark.integracao
@pytest.mark.requisito("RF-1010", "RNF-408", "CT-PEN-03")
def test_recepcao_ve_a_tela_unica_com_os_nomes(
    pacientes: list[tuple[int, str]], engine_web: Engine, criar_usuario: CriarUsuario, relogio: RelogioControlado
) -> None:
    c = cliente(engine_web, criar_usuario, relogio, "recepcao")
    html = get(c, "/pendencias").get_data(as_text=True)
    (pid, nome), _ = pacientes
    assert f"Cadastro incompleto: {nome}" in html and f"Documento faltante: {nome}" in html
    assert 'data-prioridade="N"' in html and f'href="/pacientes/{pid}"' in html
    assert 'href="/pendencias"' in get(c, "/").get_data(as_text=True)  # o item do menu


@pytest.mark.integracao
@pytest.mark.requisito("RNF-408", "DD-57", "CT-PEN-02")
def test_inicio_mostra_a_contagem_e_atualiza_sem_renovar_a_sessao(
    pacientes: list[tuple[int, str]], engine_web: Engine, criar_usuario: CriarUsuario, relogio: RelogioControlado
) -> None:
    c = cliente(engine_web, criar_usuario, relogio, "recepcao")
    html = get(c, "/").get_data(as_text=True)
    assert 'id="pendencias-resumo"' in html and 'hx-get="/pendencias/resumo"' in html
    assert 'data-contagem="N"' in html
    fragmento = c.get("/pendencias/resumo", base_url=ORIGEM, headers={"X-SAR-Automatica": "1"})
    assert fragmento.status_code == 200 and 'data-contagem="U"' in fragmento.get_data(as_text=True)


@pytest.mark.integracao
@pytest.mark.requisito("RF-922", "DD-30", "CT-PEN-04")
def test_cartoes_do_turno_mostram_as_pendencias_de_cada_paciente(
    pacientes: list[tuple[int, str]], engine_web: Engine, criar_usuario: CriarUsuario, relogio: RelogioControlado
) -> None:
    c = cliente(engine_web, criar_usuario, relogio, "recepcao")
    html = get(c, "/").get_data(as_text=True)
    for pid, _ in pacientes:
        cartao = html[html.index(f'data-paciente="{pid}"') :]
        cartao = cartao[: cartao.index("</li>")]
        assert 'class="etiqueta-n">Cadastro incompleto<' in cartao
        assert 'class="etiqueta-n">Documento faltante<' in cartao


@pytest.mark.integracao
@pytest.mark.requisito("RF-1010", "CT-PEN-04")
def test_ficha_mostra_as_outras_pendencias(
    pacientes: list[tuple[int, str]], engine_web: Engine, criar_usuario: CriarUsuario, relogio: RelogioControlado
) -> None:
    c = cliente(engine_web, criar_usuario, relogio, "recepcao")
    (pid, _), _ = pacientes
    html = get(c, f"/pacientes/{pid}").get_data(as_text=True)
    outras = html[html.index('id="outras-pend-t"') :]
    outras = outras[: outras.index("</section>")]
    assert "Falta:" in outras  # o checklist faltante; o cadastro incompleto continua no bloco dele
    assert f'href="/pacientes/{pid}"' not in outras  # a própria ficha não vira link


@pytest.mark.integracao
@pytest.mark.requisito("RF-1004", "RNF-625", "CT-ACE-02", "DD-112")
def test_ti_ve_pendencias_e_jobs_sem_dado_de_paciente(
    pacientes: list[tuple[int, str]], engine_web: Engine, criar_usuario: CriarUsuario, relogio: RelogioControlado
) -> None:
    c = cliente(engine_web, criar_usuario, relogio, "ti")
    respostas = [get(c, caminho) for caminho in ("/", "/pendencias", "/pendencias/resumo", "/agendamento")]
    assert all(r.status_code == 200 for r in respostas)
    texto = " ".join(r.get_data(as_text=True) for r in respostas)
    for _, nome in pacientes:
        assert nome not in texto
    jobs = respostas[3].get_data(as_text=True)
    assert 'data-job="backup"' in jobs and "sar job executar" in jobs and "<form" not in jobs.split("<main")[1]


@pytest.mark.integracao
@pytest.mark.requisito("DD-112", "AD-20")
def test_jobs_so_para_o_ti(
    pacientes: list[tuple[int, str]], engine_web: Engine, criar_usuario: CriarUsuario, relogio: RelogioControlado
) -> None:
    c = cliente(engine_web, criar_usuario, relogio, "recepcao")
    assert get(c, "/agendamento").status_code == 403
    assert 'href="/agendamento"' not in get(c, "/").get_data(as_text=True)


# ------------------------------------------------------------------ agrupamento (sem banco)
def _item(codigo: str, prioridade: Prioridade, horas: int, paciente: int | None = None) -> ItemPendencia:
    return ItemPendencia(codigo, prioridade, datetime(2026, 10, 19, tzinfo=UTC) - timedelta(hours=horas), "detalhe",
                         f"/pacientes/{paciente}" if paciente else "/pendencias", paciente)  # fmt: skip


@pytest.mark.requisito("RNF-408", "CT-PEN-02")
def test_mais_de_cinco_do_mesmo_tipo_ficam_em_mais() -> None:
    recepcao = Contexto(1, Perfil.RECEPCAO, 1, "10.0.0.5", datetime(2026, 10, 19, tzinfo=UTC), "a" * 32)
    itens = [_item("cadastro_incompleto", Prioridade.NORMAL, 100 - i, i) for i in range(POR_TIPO + 3)]
    itens.append(_item("rascunho_proximo_descarte", Prioridade.NORMAL, 1))
    itens.insert(0, _item("sessao_nao_confirmada", Prioridade.URGENCIA, 2))
    grupos = agrupar(recepcao, itens, {0: "Fulano Fictício"})
    assert [g.prioridade for g in grupos] == [Prioridade.URGENCIA, Prioridade.NORMAL]
    normal = grupos[1]
    assert len(normal.linhas) == POR_TIPO + 1 and normal.total == POR_TIPO + 4
    assert list(normal.mais) == ["cadastro_incompleto"] and len(normal.mais["cadastro_incompleto"]) == 3
    assert normal.linhas[0].titulo == "Cadastro incompleto: Fulano Fictício"
    assert grupos[0].linhas[0].destino is None  # "/pendencias": sem tela para resolver, sem botão


@pytest.mark.requisito("DEC-55")
def test_enfermagem_nao_recebe_link_para_a_ficha() -> None:
    enfermagem = Contexto(1, Perfil.ENFERMAGEM, 1, "10.0.0.5", datetime(2026, 10, 19, tzinfo=UTC), "a" * 32)
    (grupo,) = agrupar(enfermagem, [_item("sem_alocacao", Prioridade.ALTA, 1, 7)], {})
    assert grupo.linhas[0].destino is None
