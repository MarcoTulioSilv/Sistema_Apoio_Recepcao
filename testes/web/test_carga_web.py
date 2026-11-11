"""Carga inicial pela web (DDS §14.3, RF-1106, P-29): relatório, tratamento, conferência e aceite, com o banco e as
planilhas sintéticas (PT §5.3). O TI não vê nada disso (RF-1004)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine

from sar.modulo_10_carga.contrato import CAMPOS_CONFERIDOS
from testes.apoio import planilhas
from testes.apoio.acesso import CriarUsuario
from testes.apoio.carga import contar, ti
from testes.apoio.web import get, logado, montar, post, servicos_web

pytestmark = pytest.mark.integracao


def efetivar(engine: Engine, usuarios: dict[str, int], pasta: Path) -> None:
    """Pelo mesmo serviço que a web monta (mesma chave), como o TI faria no terminal."""
    servicos_web(engine).carga.efetivar(ti(usuarios), pasta)


def cliente(engine: Engine, criar_usuario: CriarUsuario, perfil: str) -> FlaskClient:
    login = f"webcarga_{perfil[:5]}"
    criar_usuario(login, perfil=perfil)
    return logado(montar(engine), login)


def ids(html: str, padrao: str) -> list[int]:
    return [int(n) for n in re.findall(padrao, html)]


@pytest.mark.requisito("RF-1004", "DD-65", "AD-20")
def test_menu_so_com_carga_em_revisao_e_nunca_para_o_ti(
    carga: dict[str, int],
    engine_web: Engine,
    criar_usuario: CriarUsuario,
    sinteticas: tuple[planilhas.Sinteticas, Path],
) -> None:
    recepcao = cliente(engine_web, criar_usuario, "recepcao")
    assert 'href="/carga"' not in get(recepcao, "/").get_data(as_text=True)  # antes de qualquer carga
    efetivar(engine_web, carga, sinteticas[1])
    assert 'href="/carga"' in get(recepcao, "/").get_data(as_text=True)
    ti_web = cliente(engine_web, criar_usuario, "ti")
    assert 'href="/carga"' not in get(ti_web, "/").get_data(as_text=True)
    assert get(ti_web, "/carga").status_code == 403
    assert get(ti_web, "/carga/amostra").status_code == 403


@pytest.mark.requisito("RF-1106", "P-28", "DD-114")
def test_relatorio_e_tratamento_das_excecoes(
    carga: dict[str, int],
    engine_web: Engine,
    criar_usuario: CriarUsuario,
    sinteticas: tuple[planilhas.Sinteticas, Path],
) -> None:
    gerado, pasta = sinteticas
    efetivar(engine_web, carga, pasta)
    recepcao = cliente(engine_web, criar_usuario, "recepcao")
    html = get(recepcao, "/carga").get_data(as_text=True)
    saida = next(f for f in gerado.fichas if f.defeito == "evento_de_saida")
    assert saida.nome in html and "Consta na planilha de eventos" in html
    assert f"{gerado.esperados()['excecoes']} a tratar" in html
    assert "/carga/" not in "".join(re.findall(r'href="([^"]*\?[^"]*)"', html))  # nenhum dado em URL
    linha = ids(html, r'action="/carga/excecoes/(\d+)"')[0]
    sem_motivo = post(recepcao, f"/carga/excecoes/{linha}", {"tratamento": "descartada", "motivo": ""})
    assert sem_motivo.status_code == 422 and "pelo menos 5 caracteres" in sem_motivo.get_data(as_text=True)
    sem_escolha = post(recepcao, f"/carga/excecoes/{linha}", {"motivo": "qualquer"})
    assert sem_escolha.status_code == 422
    feito = post(recepcao, f"/carga/excecoes/{linha}", {"tratamento": "descartada", "motivo": "paciente já saiu"})
    assert feito.status_code == 302 and feito.headers["Location"].endswith(f"#linha-{linha}")
    depois = get(recepcao, "/carga").get_data(as_text=True)
    assert "Descartada:</span> paciente já saiu" in depois and "Refazer a decisão" in depois


@pytest.mark.requisito("P-29", "ND-50", "RF-1106")
def test_conferencia_lado_a_lado_registra_em_partes(
    carga: dict[str, int],
    engine_web: Engine,
    criar_usuario: CriarUsuario,
    sinteticas: tuple[planilhas.Sinteticas, Path],
) -> None:
    efetivar(engine_web, carga, sinteticas[1])
    recepcao = cliente(engine_web, criar_usuario, "recepcao")
    lista = get(recepcao, "/carga/amostra").get_data(as_text=True)
    sorteados = ids(lista, r'href="/carga/amostra/(\d+)"')
    assert len(sorteados) == 15 and "15 a conferir" in lista
    tela = get(recepcao, f"/carga/amostra/{sorteados[0]}").get_data(as_text=True)
    assert "Ficha na planilha de endereços" in tela and "Na planilha de entradas" in tela
    assert all(f'name="campo-{campo}"' in tela for campo, _ in CAMPOS_CONFERIDOS)
    parcial = post(recepcao, f"/carga/amostra/{sorteados[0]}", {"campo-nome": "conferido", "campo-cpf": "divergente"})
    assert parcial.status_code == 302
    tela = get(recepcao, f"/carga/amostra/{sorteados[0]}?resultado=conferencia").get_data(as_text=True)
    assert "2 de 13 campos registrados" in tela and "Corrigir na ficha" in tela
    assert "2 de 13 campos" in get(recepcao, "/carga/amostra").get_data(as_text=True)


def conferir_e_tratar_tudo(c: FlaskClient) -> None:
    html = get(c, "/carga").get_data(as_text=True)
    for linha in ids(html, r'action="/carga/excecoes/(\d+)"'):
        post(c, f"/carga/excecoes/{linha}", {"tratamento": "descartada", "motivo": "conferido com a recepção"})
    for sorteado in ids(get(c, "/carga/amostra").get_data(as_text=True), r'href="/carga/amostra/(\d+)"'):
        post(c, f"/carga/amostra/{sorteado}", {f"campo-{campo}": "conferido" for campo, _ in CAMPOS_CONFERIDOS})


@pytest.mark.requisito("DD-69", "DD-114", "P-29")
def test_aceite_da_administracao_com_a_contagem_da_recepcao(
    carga: dict[str, int],
    engine_web: Engine,
    criar_usuario: CriarUsuario,
    sinteticas: tuple[planilhas.Sinteticas, Path],
) -> None:
    gerado, pasta = sinteticas
    efetivar(engine_web, carga, pasta)
    recepcao = cliente(engine_web, criar_usuario, "recepcao")
    assert "Aceite da carga" not in get(recepcao, "/carga/amostra").get_data(as_text=True)  # só a administração
    assert post(recepcao, "/carga/aceitar", {"ativos": "1"}).status_code == 403
    admin = cliente(engine_web, criar_usuario, "administracao")
    conferir_e_tratar_tudo(admin)
    importados = gerado.esperados()["importados"]
    painel = get(admin, "/carga/amostra").get_data(as_text=True)
    assert "Aceite da carga" in painel and f'<strong class="numero">{importados}</strong>' in painel
    assert post(admin, "/carga/aceitar", {"ativos": "muitos"}).status_code == 422
    diferente = post(admin, "/carga/aceitar", {"ativos": str(importados - 2)})
    assert diferente.status_code == 422
    assert f"A contagem da recepção ({importados - 2}) é diferente da carga ({importados})" in diferente.get_data(
        as_text=True
    )
    aceito = post(admin, "/carga/aceitar", {"ativos": str(importados - 2), "confirmar": "sim"})
    assert aceito.status_code == 302 and aceito.headers["Location"].endswith("/carga?resultado=aceita")
    assert contar(engine_web, "SELECT COUNT(*) FROM carga_linha") == 0
    assert 'href="/carga"' not in get(admin, "/").get_data(as_text=True)  # o item some depois do aceite
    assert "A carga inicial está encerrada" in get(admin, "/carga").get_data(as_text=True)
