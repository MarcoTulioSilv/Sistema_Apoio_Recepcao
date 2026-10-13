"""Telas de usuários e de parâmetros, com o banco de testes (DDS §5.1, §10.1, DD-17, DD-87)."""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text

from testes.apoio.acesso import CriarUsuario
from testes.apoio.web import get, logado, montar, post
from testes.conftest import ZERAR_TRILHA

pytestmark = pytest.mark.integracao


@pytest.fixture
def limpar(trilha_zerada: Engine) -> Iterator[None]:
    """Apaga, no fim, o que as telas criaram: usuários webu_* e valores de parâmetros."""
    yield
    with trilha_zerada.begin() as c:
        for comando in ZERAR_TRILHA:
            c.execute(text(comando))
        c.execute(text("DELETE FROM parametro"))
        criados = "SELECT id FROM usuario WHERE login LIKE 'webu%'"
        for (usuario_id,) in c.execute(text(criados)).all():
            c.execute(text("DELETE FROM sessao_usuario WHERE usuario_id = :u"), {"u": usuario_id})
            c.execute(text("DELETE FROM usuario WHERE id = :u"), {"u": usuario_id})


def versao(engine: Engine, usuario_id: int) -> str:
    with engine.connect() as c:
        return str(c.execute(text("SELECT versao FROM usuario WHERE id = :u"), {"u": usuario_id}).scalar_one())


# ------------------------------------------------------------------ usuários
@pytest.mark.requisito("RF-1002", "DD-83")
def test_ti_cria_usuario_e_ve_a_senha_provisoria_uma_vez(
    criar_usuario: CriarUsuario, engine_web: Engine, limpar: None
) -> None:
    criar_usuario("webu_ti", perfil="ti")
    app = montar(engine_web)
    ti = logado(app, "webu_ti")
    assert "Usuários" in get(ti, "/").get_data(as_text=True)

    corpo = post(ti, "/usuarios/novo", {"nome": "Ana Fictício", "login": "webu_ana", "perfil": "recepcao"}).get_data(
        as_text=True
    )
    senha = re.search(r'data-sobre="senha-provisoria">([^<]+)<', corpo)
    assert senha is not None and len(senha.group(1)) >= 12
    linha = re.search(r'data-login="webu_ana".*?</tr>', get(ti, "/usuarios").get_data(as_text=True), re.S)
    assert linha is not None and "Sem termo" in linha.group(0) and "Senha provisória" in linha.group(0)
    detalhe = re.search(r'href="(/usuarios/\d+)"', linha.group(0))
    assert detalhe is not None
    assert senha.group(1) not in get(ti, detalhe.group(1)).get_data(as_text=True)  # não aparece de novo

    repetido = post(ti, "/usuarios/novo", {"nome": "Outra Fictício", "login": "webu_ana", "perfil": "recepcao"})
    assert "Já existe um usuário com esse login" in repetido.get_data(as_text=True)


@pytest.mark.requisito("DD-17", "RNF-605")
def test_alteracoes_pela_tela_com_versao_e_conflito(
    criar_usuario: CriarUsuario, engine_web: Engine, limpar: None
) -> None:
    criar_usuario("webu_ti2", perfil="ti")
    alvo = criar_usuario("webu_rita")
    ti = logado(montar(engine_web), "webu_ti2")
    velha = versao(engine_web, alvo)

    resposta = post(ti, f"/usuarios/{alvo}/perfil", {"perfil": "visualizador", "versao": velha})
    assert resposta.status_code == 302 and "resultado=perfil" in resposta.headers["Location"]
    assert "Perfil alterado" in get(ti, resposta.headers["Location"]).get_data(as_text=True)

    conflito = post(ti, f"/usuarios/{alvo}/inativar", {"versao": velha})  # formulário aberto antes da mudança
    assert "alterado em outra tela" in conflito.get_data(as_text=True)

    post(ti, f"/usuarios/{alvo}/termo", {"versao": versao(engine_web, alvo)})
    assert "Termo de ciência registrado em" in get(ti, f"/usuarios/{alvo}").get_data(as_text=True)
    redefinida = post(ti, f"/usuarios/{alvo}/senha", {"versao": versao(engine_web, alvo)}).get_data(as_text=True)
    assert 'data-sobre="senha-provisoria"' in redefinida


@pytest.mark.requisito("DD-87")
def test_tela_explica_por_que_o_ultimo_ti_nao_sai(
    criar_usuario: CriarUsuario, engine_web: Engine, limpar: None
) -> None:
    ti_id = criar_usuario("webu_unico_ti", perfil="ti")
    ti = logado(montar(engine_web), "webu_unico_ti")
    corpo = post(ti, f"/usuarios/{ti_id}/inativar", {"versao": versao(engine_web, ti_id)}).get_data(as_text=True)
    assert 'role="alert">Este é o único TI ativo' in corpo


@pytest.mark.requisito("RF-1004", "CT-ACE-01")
def test_so_o_ti_abre_a_tela_de_usuarios(criar_usuario: CriarUsuario, engine_web: Engine, limpar: None) -> None:
    criar_usuario("webu_admin", perfil="administracao")
    admin = logado(montar(engine_web), "webu_admin")
    assert "/usuarios" not in get(admin, "/").get_data(as_text=True)  # nem aparece no menu
    assert get(admin, "/usuarios").status_code == 403
    assert post(admin, "/usuarios/novo", {"nome": "X", "login": "webu_x", "perfil": "ti"}).status_code == 403


# ------------------------------------------------------------------ parâmetros
@pytest.mark.requisito("DD-48", "CT-ACE-01")
def test_cada_perfil_edita_so_os_seus_parametros(criar_usuario: CriarUsuario, engine_web: Engine, limpar: None) -> None:
    criar_usuario("webu_adm", perfil="administracao")
    app = montar(engine_web)
    admin = logado(app, "webu_adm")
    corpo = get(admin, "/parametros").get_data(as_text=True)
    operacional = re.search(r'data-parametro="rascunho_prazo".*?</tr>', corpo, re.S)
    tecnico = re.search(r'data-parametro="sessao_inatividade".*?</tr>', corpo, re.S)
    assert operacional is not None and "<form" in operacional.group(0)
    assert tecnico is not None and "<form" not in tecnico.group(0) and "10 minutos" in tecnico.group(0)
    assert post(admin, "/parametros/sessao_inatividade", {"valor": "15"}).status_code == 403

    resposta = post(admin, "/parametros/rascunho_prazo", {"valor": "5"})
    assert resposta.status_code == 302
    assert "valor alterado" in get(admin, resposta.headers["Location"]).get_data(as_text=True)


@pytest.mark.requisito("DD-48")
def test_valor_fora_dos_limites_ou_mal_formado_explica_o_que_fazer(
    criar_usuario: CriarUsuario, engine_web: Engine, limpar: None
) -> None:
    criar_usuario("webu_ti3", perfil="ti")
    ti = logado(montar(engine_web), "webu_ti3")
    assert "use um valor de 2 a 30" in post(ti, "/parametros/sessao_inatividade", {"valor": "0"}).get_data(as_text=True)
    assert "formato inválido" in post(ti, "/parametros/sessao_inatividade", {"valor": "dez"}).get_data(as_text=True)
    assert post(ti, "/parametros/extracao_ligada", {"valor": "nao"}).status_code == 302
    assert post(ti, "/parametros/data_implantacao", {"valor": "2026-11-03"}).status_code == 302
    corpo = get(ti, "/parametros").get_data(as_text=True)
    assert 'value="2026-11-03"' in corpo
    assert get(ti, "/parametros/nao_existe").status_code == 405  # só POST
    assert post(ti, "/parametros/nao_existe", {"valor": "1"}).status_code == 404


@pytest.mark.requisito("DD-48")
def test_recepcao_ve_os_parametros_so_para_leitura(
    criar_usuario: CriarUsuario, engine_web: Engine, limpar: None
) -> None:
    criar_usuario("webu_recep")
    recepcao = logado(montar(engine_web), "webu_recep")
    assert "/parametros" not in get(recepcao, "/").get_data(as_text=True)
    corpo = get(recepcao, "/parametros").get_data(as_text=True)
    assert "Inatividade até encerrar a sessão" in corpo and '<form class="flex flex-wrap items-center' not in corpo
