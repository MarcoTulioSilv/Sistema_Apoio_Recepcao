"""Interface web (Flask). Rotas chamam só os contratos dos módulos; nunca o banco (DD-16)."""

from __future__ import annotations

import logging
import time

from flask import Flask, Response, g, render_template
from werkzeug.exceptions import HTTPException

from sar.nucleo.logs import campos_do_erro, encerrar_requisicao, iniciar_requisicao

# DD-09: nenhum recurso de fora do servidor, nenhum código ou estilo inline.
POLITICA_CONTEUDO = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)
CABECALHO_REQUISICAO = "X-Requisicao-Id"

log = logging.getLogger(__name__)


def criar_app() -> Flask:
    app = Flask(__name__, template_folder="modelos", static_folder="static")

    from sar.web.rotas_saude import bp as saude

    app.register_blueprint(saude)

    @app.before_request
    def abrir_requisicao() -> None:
        g.requisicao_id = iniciar_requisicao()  # DD-81: liga log técnico e auditoria da mesma requisição
        g.inicio = time.perf_counter()

    @app.after_request
    def cabecalhos_e_registro(resposta: Response) -> Response:
        resposta.headers["Content-Security-Policy"] = POLITICA_CONTEUDO
        resposta.headers["X-Content-Type-Options"] = "nosniff"
        resposta.headers["Referrer-Policy"] = "no-referrer"
        if "requisicao_id" in g:
            resposta.headers[CABECALHO_REQUISICAO] = g.requisicao_id
            # Sem caminho nem parâmetros: o acesso com caminho é registrado pelo Caddy, sem a query (DD-81).
            duracao = (time.perf_counter() - g.inicio) * 1000
            log.info("web.requisicao", extra={"resultado": str(resposta.status_code), "duracao_ms": duracao})
        return resposta

    @app.teardown_request
    def fechar_requisicao(_erro: BaseException | None) -> None:
        encerrar_requisicao()

    @app.errorhandler(Exception)
    def erro_inesperado(erro: Exception) -> Response | HTTPException | tuple[str, int]:
        if isinstance(erro, HTTPException):
            return erro
        # Nunca str(erro) nem traceback: só o tipo e, em erro de banco, a restrição (DD-81, RNF-624).
        log.error("web.erro_inesperado", extra=campos_do_erro(erro))
        return render_template("erro.html"), 500

    return app
