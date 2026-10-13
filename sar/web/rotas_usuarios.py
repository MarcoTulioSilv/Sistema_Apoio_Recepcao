"""Tela de usuários do TI (DDS §5.1, §4.1): lista, criação e as alterações de cada usuário."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from flask import Blueprint, current_app, redirect, render_template, request, url_for
from werkzeug.wrappers import Response

from sar.modulo_01_acesso.contrato import UsuarioResumo
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import ConflitoDeVersao, NaoEncontrado, RegraViolada
from sar.web import contexto_atual
from sar.web.configuracao import ServicosWeb
from sar.web.rotulos import PERFIS

bp = Blueprint("usuarios", __name__, url_prefix="/usuarios")

ERROS = {
    "usuario.nome": "Informe o nome, com até 120 caracteres.",
    "usuario.login_formato": (
        "O login vai em minúsculas, de 3 a 60 caracteres: letras, números, ponto, hífen e sublinhado."
    ),
    "usuario.login_repetido": "Já existe um usuário com esse login.",
    "usuario.perfil": "Escolha um dos cinco perfis.",
    "usuario.perfil_igual": "O usuário já tem esse perfil.",
    "usuario.ja_inativo": "O usuário já está inativo.",
    "usuario.ja_ativo": "O usuário já está ativo.",
    "usuario.termo_ja_registrado": "O termo de ciência deste usuário já está registrado.",
    "usuario.ultimo_ti": (
        "Este é o único TI ativo. Crie ou reative outro TI antes de inativá-lo ou trocar o perfil dele."
    ),
}
CONFLITO = (
    "Este usuário foi alterado em outra tela. Os dados abaixo já estão atualizados; repita a ação se ainda for preciso."
)
RESULTADOS = {
    "perfil": "Perfil alterado.",
    "inativado": "Usuário inativado. As sessões dele foram encerradas.",
    "reativado": "Usuário reativado.",
    "termo": "Termo de ciência registrado.",
}


def _servicos() -> ServicosWeb:
    servicos: ServicosWeb = current_app.config["SAR_SERVICOS"]
    return servicos


def _perfil(texto: str) -> Perfil | None:
    return next((p for p in PERFIS if p.value == texto), None)


def _usuario(contexto: Contexto, usuario_id: int) -> UsuarioResumo:
    usuario = next((u for u in _servicos().usuarios.consultar(contexto) if u.id == usuario_id), None)
    if usuario is None:
        raise NaoEncontrado()
    return usuario


def _pagina_do_usuario(contexto: Contexto, usuario_id: int, **dados: Any) -> str:
    return render_template("usuario.html", usuario=_usuario(contexto, usuario_id), perfis=PERFIS, **dados)


@bp.get("")
def lista() -> str:
    usuarios = _servicos().usuarios.consultar(contexto_atual())
    return render_template("usuarios.html", usuarios=usuarios, perfis=PERFIS)


@bp.get("/novo")
def novo() -> str:
    contexto_atual()
    return render_template("usuario_novo.html", perfis=PERFIS, dados={})


@bp.post("/novo")
def novo_enviar() -> str:
    contexto = contexto_atual()
    dados = {chave: request.form.get(chave, "") for chave in ("nome", "login", "perfil")}
    perfil = _perfil(dados["perfil"])
    if perfil is None:
        return render_template("usuario_novo.html", perfis=PERFIS, dados=dados, erro=ERROS["usuario.perfil"])
    try:
        criado = _servicos().usuarios.criar(contexto, dados["nome"], dados["login"], perfil)
    except RegraViolada as erro:
        return render_template(
            "usuario_novo.html", perfis=PERFIS, dados=dados, erro=ERROS.get(erro.codigo, erro.codigo)
        )
    return _pagina_do_usuario(contexto, criado.id, senha_provisoria=criado.senha_provisoria)


@bp.get("/<int:usuario_id>")
def detalhe(usuario_id: int) -> str:
    resultado = RESULTADOS.get(request.args.get("resultado", ""))
    return _pagina_do_usuario(contexto_atual(), usuario_id, resultado=resultado)


def _alterar(usuario_id: int, acao: Callable[[Contexto, int], None], resultado: str) -> Response | str:
    contexto = contexto_atual()
    try:
        acao(contexto, int(request.form.get("versao", "0")))
    except ConflitoDeVersao:
        return _pagina_do_usuario(contexto, usuario_id, erro=CONFLITO)
    except RegraViolada as erro:
        return _pagina_do_usuario(contexto, usuario_id, erro=ERROS.get(erro.codigo, erro.codigo))
    return redirect(url_for("usuarios.detalhe", usuario_id=usuario_id, resultado=resultado))


@bp.post("/<int:usuario_id>/perfil")
def alterar_perfil(usuario_id: int) -> Response | str:
    perfil = _perfil(request.form.get("perfil", ""))
    if perfil is None:
        return _pagina_do_usuario(contexto_atual(), usuario_id, erro=ERROS["usuario.perfil"])
    return _alterar(usuario_id, lambda c, v: _servicos().usuarios.alterar_perfil(c, usuario_id, v, perfil), "perfil")


@bp.post("/<int:usuario_id>/inativar")
def inativar(usuario_id: int) -> Response | str:
    return _alterar(usuario_id, lambda c, v: _servicos().usuarios.inativar(c, usuario_id, v), "inativado")


@bp.post("/<int:usuario_id>/reativar")
def reativar(usuario_id: int) -> Response | str:
    return _alterar(usuario_id, lambda c, v: _servicos().usuarios.reativar(c, usuario_id, v), "reativado")


@bp.post("/<int:usuario_id>/termo")
def registrar_termo(usuario_id: int) -> Response | str:
    return _alterar(usuario_id, lambda c, v: _servicos().usuarios.registrar_termo(c, usuario_id, v), "termo")


@bp.post("/<int:usuario_id>/senha")
def redefinir_senha(usuario_id: int) -> str:
    """Mostra a senha provisória nesta resposta e nunca mais (a página não fica em cache)."""
    contexto = contexto_atual()
    try:
        provisoria = _servicos().usuarios.redefinir_senha(contexto, usuario_id, int(request.form.get("versao", "0")))
    except ConflitoDeVersao:
        return _pagina_do_usuario(contexto, usuario_id, erro=CONFLITO)
    return _pagina_do_usuario(contexto, usuario_id, senha_provisoria=provisoria)
