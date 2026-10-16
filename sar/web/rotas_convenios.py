"""Tela de convênios da administração (RF-1204, DD-49): incluir, renomear, inativar e reativar."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from flask import Blueprint, current_app, redirect, render_template, request, url_for
from werkzeug.wrappers import Response

from sar.modulo_01_acesso.contrato import PermissionGuard
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import RegraViolada
from sar.web import contexto_atual
from sar.web.configuracao import ServicosWeb

bp = Blueprint("convenios", __name__, url_prefix="/convenios")
GUARDA = PermissionGuard()

ERROS = {
    "convenio.nome": "Informe o nome do convênio, de 2 a 100 caracteres.",
    "convenio.nome_repetido": "Já existe um convênio com esse nome.",
}
RESULTADOS = {
    "incluido": "Convênio incluído.",
    "renomeado": "Nome do convênio alterado.",
    "inativado": "Convênio inativado. Ele deixa de ser oferecido em cobertura nova; as antigas continuam com ele.",
    "reativado": "Convênio reativado.",
}


def _servicos() -> ServicosWeb:
    servicos: ServicosWeb = current_app.config["SAR_SERVICOS"]
    return servicos


def _contexto() -> Contexto:
    """A tela é da administração: quem só consulta a lista a vê dentro do cadastro, não aqui."""
    contexto = contexto_atual()
    GUARDA.exigir(contexto, "config.convenio.gerir")
    return contexto


def _pagina(contexto: Contexto, **dados: Any) -> str:
    convenios = _servicos().configuracao.listar_convenios(contexto)
    return render_template("convenios.html", convenios=convenios, **dados)


def _executar(acao: Callable[[Contexto], object], resultado: str, **dados: Any) -> Response | str:
    contexto = _contexto()
    try:
        acao(contexto)
    except RegraViolada as erro:
        return _pagina(contexto, erro=ERROS.get(erro.codigo, "Não foi possível concluir."), **dados)
    return redirect(url_for("convenios.lista", resultado=resultado))


@bp.get("")
def lista() -> str:
    contexto = _contexto()
    return _pagina(contexto, resultado=RESULTADOS.get(request.args.get("resultado", "")))


@bp.post("")
def incluir() -> Response | str:
    nome = request.form.get("nome", "")
    return _executar(lambda c: _servicos().configuracao.incluir_convenio(c, nome), "incluido", nome_digitado=nome)


@bp.post("/<int:convenio_id>/renomear")
def renomear(convenio_id: int) -> Response | str:
    nome = request.form.get("nome", "")
    return _executar(lambda c: _servicos().configuracao.renomear_convenio(c, convenio_id, nome), "renomeado")


@bp.post("/<int:convenio_id>/inativar")
def inativar(convenio_id: int) -> Response | str:
    return _executar(lambda c: _servicos().configuracao.inativar_convenio(c, convenio_id), "inativado")


@bp.post("/<int:convenio_id>/reativar")
def reativar(convenio_id: int) -> Response | str:
    return _executar(lambda c: _servicos().configuracao.reativar_convenio(c, convenio_id), "reativado")
