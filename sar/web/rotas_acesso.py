"""Entrada, saída, página inicial e troca da própria senha (DDS §5.2, DD-19, DD-84, DD-85)."""

from __future__ import annotations

from typing import Any

from flask import Blueprint, abort, current_app, g, redirect, render_template, request, url_for
from werkzeug.wrappers import Response

from sar.modulo_01_acesso.contrato import CredencialInvalida, TermoPendente, TrocaDeSenhaExigida
from sar.nucleo.erros import RegraViolada
from sar.web import COOKIE_PERFIL_DEV, COOKIE_SESSAO, ROTULOS_PERFIL, contexto_atual
from sar.web.configuracao import ServicosWeb

bp = Blueprint("acesso", __name__)

# Por que a pessoa voltou à tela de entrada; só códigos na URL, nunca dado (DD-81).
AVISOS_DE_ENTRADA = {
    "novo_login": "Sua sessão foi encerrada porque houve uma entrada com o seu usuário em outra estação.",
    "inatividade": "Sua sessão foi encerrada por inatividade. Entre de novo para continuar.",
    "limite": "Sua sessão chegou ao tempo máximo do dia. Entre de novo para continuar.",
    "saida": "Você saiu do sistema.",
    "inativacao": "Seu acesso foi desativado. Procure o TI.",
    "sessao": "Entre para continuar.",
}
ERRO_ENTRADA = "Login ou senha incorretos. Confira e tente de novo."  # sempre o mesmo (§5.2)
ERROS_SENHA = {
    "senha.tamanho": "A senha nova precisa ter de 8 a 64 caracteres.",
    "senha.fraca": "Essa senha é fácil de adivinhar. Use uma frase, ou palavras que só você associe.",
    "senha.contem_nome": "A senha nova não pode conter o seu nome nem o seu login.",
    "senha.igual_a_atual": "A senha nova precisa ser diferente da atual.",
    "senha.confirmacao": "As duas senhas novas não são iguais. Digite de novo.",
}
OPCOES_COOKIE: dict[str, Any] = {"secure": True, "httponly": True, "samesite": "Strict", "path": "/"}


def _servicos() -> ServicosWeb:
    servicos: ServicosWeb = current_app.config["SAR_SERVICOS"]
    return servicos


def _origem() -> str:
    return request.remote_addr or "desconhecida"


def _pagina_de_entrada(**dados: Any) -> str:
    return render_template("entrar.html", **dados)


@bp.get("/entrar")
def entrar() -> str:
    return _pagina_de_entrada(aviso=AVISOS_DE_ENTRADA.get(request.args.get("motivo", "")))


@bp.post("/entrar")
def entrar_enviar() -> Response | str:
    login, senha = request.form.get("login", ""), request.form.get("senha", "")
    troca = "nova_senha" in request.form
    nova, repetida = request.form.get("nova_senha", ""), request.form.get("nova_senha_repetida", "")
    if troca and nova != repetida:
        return _pagina_de_entrada(login=login, troca=True, erro=ERROS_SENHA["senha.confirmacao"])
    try:
        aberta = _servicos().autenticacao.entrar(login, senha, _origem(), nova if troca else None)
    except CredencialInvalida:
        return _pagina_de_entrada(login=login, erro=ERRO_ENTRADA)
    except TermoPendente:
        erro = "Seu acesso ainda não foi liberado: o TI precisa registrar o termo de ciência de uso."
        return _pagina_de_entrada(login=login, erro=erro)
    except TrocaDeSenhaExigida:
        aviso = "Sua senha é provisória. Digite-a de novo e escolha uma senha nova para continuar."
        return _pagina_de_entrada(login=login, troca=True, aviso=aviso)
    except RegraViolada as erro:
        return _pagina_de_entrada(login=login, troca=True, erro=ERROS_SENHA.get(erro.codigo, ERRO_ENTRADA))
    resposta = redirect(url_for("acesso.inicio"))
    resposta.set_cookie(COOKIE_SESSAO, aberta.token, **OPCOES_COOKIE)  # sem prazo: some ao fechar o navegador
    resposta.delete_cookie(COOKIE_PERFIL_DEV, **OPCOES_COOKIE)
    return resposta


@bp.post("/sair")
def sair() -> Response:
    _servicos().autenticacao.sair(contexto_atual())
    resposta = redirect(url_for("acesso.entrar", motivo="saida"))
    resposta.delete_cookie(COOKIE_SESSAO, **OPCOES_COOKIE)
    resposta.delete_cookie(COOKIE_PERFIL_DEV, **OPCOES_COOKIE)
    return resposta


@bp.get("/")
def inicio() -> str:
    contexto_atual()
    return render_template("inicio.html")


@bp.get("/senha")
def senha() -> str:
    contexto_atual()
    return render_template("senha.html")


@bp.post("/senha")
def senha_enviar() -> str:
    contexto = contexto_atual()
    atual, nova = request.form.get("senha_atual", ""), request.form.get("nova_senha", "")
    if nova != request.form.get("nova_senha_repetida", ""):
        return render_template("senha.html", erro=ERROS_SENHA["senha.confirmacao"])
    try:
        _servicos().autenticacao.trocar_propria_senha(contexto, atual, nova)
    except CredencialInvalida:
        return render_template("senha.html", erro="A senha atual não confere. Digite de novo.")
    except RegraViolada as erro:
        return render_template("senha.html", erro=ERROS_SENHA.get(erro.codigo, "Não foi possível trocar a senha."))
    return render_template("senha.html", resultado="Senha trocada. Use a senha nova na próxima entrada.")


@bp.post("/desenvolvimento/perfil")
def trocar_perfil() -> Response:
    """Superusuário de desenvolvimento (DD-85): escolhe com qual perfil age. Fora disso, a rota não existe."""
    if not g.get("superusuario"):
        abort(404)
    perfil = request.form.get("perfil", "")
    if perfil not in {p.value for p in ROTULOS_PERFIL}:
        abort(400)
    resposta = redirect(url_for("acesso.inicio"))
    resposta.set_cookie(COOKIE_PERFIL_DEV, perfil, **OPCOES_COOKIE)
    return resposta
