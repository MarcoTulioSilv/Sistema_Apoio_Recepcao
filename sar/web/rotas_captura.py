"""Rotas de captura (DDS §8.5, DD-94): chamadas pelo agente da estação e pelo módulo de câmera, autenticadas só pelo
token de uso único da ingestão, no cabeçalho `Authorization: Bearer`. Não usam o cookie de sessão, por isso ficam fora
da conferência de `Origin` (DD-84). Nenhum cabeçalho de CORS: uma página de outra origem não consegue chamá-las.

Respostas curtas em JSON, sem dado de paciente: 204 quando deu certo, 403 com token inválido, 422 com o código da
regra violada.
"""

from __future__ import annotations

from flask import Blueprint, Response, current_app, jsonify, request

from sar.nucleo.erros import AcessoNegado, NaoEncontrado, RegraViolada
from sar.web.configuracao import ServicosWeb

bp = Blueprint("captura", __name__, url_prefix="/captura")


def _servicos() -> ServicosWeb:
    servicos: ServicosWeb = current_app.config["SAR_SERVICOS"]
    return servicos


def _token() -> str:
    esquema, _, token = request.headers.get("Authorization", "").partition(" ")
    if esquema.lower() != "bearer" or not token.strip():
        raise AcessoNegado()
    return token.strip()


def _erro(status: int, codigo: str) -> tuple[Response, int]:
    return jsonify({"erro": codigo}), status


@bp.errorhandler(AcessoNegado)
def _acesso_negado(_erro_: AcessoNegado) -> tuple[Response, int]:
    return _erro(403, "acesso")


@bp.errorhandler(NaoEncontrado)
def _nao_encontrado(_erro_: NaoEncontrado) -> tuple[Response, int]:
    return _erro(403, "acesso")  # mesma resposta do token errado: não revela se a ingestão existe


@bp.errorhandler(RegraViolada)
def _regra(erro: RegraViolada) -> tuple[Response, int]:
    return _erro(422, erro.codigo)


@bp.put("/ingestoes/<ingestao_id>/paginas/<int:numero>")
def receber_pagina(ingestao_id: str, numero: int) -> tuple[str, int]:
    """O corpo é a página, lida em blocos até o limite (SEG-06), direto para a quarentena cifrada."""
    _servicos().ingestao.receber_pagina(ingestao_id, _token(), numero, request.stream)
    return "", 204


@bp.post("/ingestoes/<ingestao_id>/concluir")
def concluir(ingestao_id: str) -> tuple[str, int]:
    corpo = request.get_json(silent=True) or {}
    paginas = corpo.get("paginas")
    if not isinstance(paginas, int) or isinstance(paginas, bool):
        raise RegraViolada("paginas.faltando")
    _servicos().ingestao.concluir(ingestao_id, _token(), paginas)
    return "", 204
