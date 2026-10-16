"""Tela de convênios, com o banco de testes (RF-1204, DD-49)."""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text

from testes.apoio.acesso import CriarUsuario
from testes.apoio.web import get, logado, montar, post

pytestmark = pytest.mark.integracao


@pytest.fixture
def sem_convenios(trilha_zerada: Engine) -> Iterator[None]:
    with trilha_zerada.begin() as c:
        c.execute(text("DELETE FROM convenio"))
    yield
    with trilha_zerada.begin() as c:
        c.execute(text("DELETE FROM convenio"))


def id_do_convenio(engine: Engine, nome: str) -> int:
    with engine.connect() as c:
        return int(c.execute(text("SELECT id FROM convenio WHERE nome = :n"), {"n": nome}).scalar_one())


@pytest.mark.requisito("RF-1204", "DD-49")
def test_administracao_gere_convenios_pela_tela(
    criar_usuario: CriarUsuario, engine_web: Engine, sem_convenios: None
) -> None:
    criar_usuario("webc_admin", perfil="administracao")
    admin = logado(montar(engine_web), "webc_admin")
    assert 'href="/convenios"' in get(admin, "/").get_data(as_text=True)
    assert "Nenhum convênio cadastrado" in get(admin, "/convenios").get_data(as_text=True)

    resposta = post(admin, "/convenios", {"nome": "  Ipasgo  "})
    assert resposta.status_code == 302 and "resultado=incluido" in resposta.headers["Location"]
    cid = id_do_convenio(engine_web, "Ipasgo")
    assert "Convênio incluído." in get(admin, "/convenios?resultado=incluido").get_data(as_text=True)

    repetido = post(admin, "/convenios", {"nome": "IPASGO"}).get_data(as_text=True)
    assert "Já existe um convênio com esse nome." in repetido and 'value="IPASGO"' in repetido  # mantém o digitado
    assert "de 2 a 100 caracteres" in post(admin, "/convenios", {"nome": "x"}).get_data(as_text=True)

    post(admin, f"/convenios/{cid}/renomear", {"nome": "Ipasgo Saúde"})
    post(admin, f"/convenios/{cid}/inativar", {})
    linha = re.search(rf'data-convenio="{cid}".*?</tr>', get(admin, "/convenios").get_data(as_text=True), re.S)
    assert linha is not None and 'value="Ipasgo Saúde"' in linha.group(0) and "Inativo" in linha.group(0)
    assert "Reativar" in linha.group(0)
    post(admin, f"/convenios/{cid}/reativar", {})
    linha = re.search(rf'data-convenio="{cid}".*?</tr>', get(admin, "/convenios").get_data(as_text=True), re.S)
    assert linha is not None and "Inativar" in linha.group(0)
    assert get(admin, f"/convenios/{cid + 1000}/inativar").status_code == 405
    assert post(admin, f"/convenios/{cid + 1000}/inativar", {}).status_code == 404


@pytest.mark.requisito("CT-ACE-01", "RF-1204")
@pytest.mark.parametrize("perfil", ["recepcao", "ti", "visualizador", "enfermagem"])
def test_outros_perfis_nao_veem_nem_usam_a_tela(
    criar_usuario: CriarUsuario, engine_web: Engine, sem_convenios: None, perfil: str
) -> None:
    criar_usuario(f"webc_{perfil}", perfil=perfil)
    cliente = logado(montar(engine_web), f"webc_{perfil}")
    assert 'href="/convenios"' not in get(cliente, "/").get_data(as_text=True)
    assert get(cliente, "/convenios").status_code == 403
    assert post(cliente, "/convenios", {"nome": "Ipasgo"}).status_code == 403
    with engine_web.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM convenio")).scalar_one() == 0
