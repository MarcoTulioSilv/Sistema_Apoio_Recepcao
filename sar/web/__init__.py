"""Interface web (Flask). Rotas chamam só os contratos dos módulos; nunca o banco (DD-16)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from typing import Any

from flask import Flask, Response, abort, g, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.wrappers import Response as RespostaWerkzeug

from sar.modulo_01_acesso.contrato import PermissionGuard, SessaoEncerrada
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado, NaoEncontrado
from sar.nucleo.logs import campos_do_erro, encerrar_requisicao, identificar_usuario, iniciar_requisicao
from sar.web.configuracao import ConfigWeb, ServicosWeb
from sar.web.rotulos import PERFIS

# DD-09: nenhum recurso de fora do servidor, nenhum código ou estilo inline.
POLITICA_CONTEUDO = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)
CABECALHO_REQUISICAO = "X-Requisicao-Id"
CABECALHO_AUTOMATICA = "X-SAR-Automatica"  # requisição da própria tela, que não renova a inatividade (DD-57)
COOKIE_SESSAO = "__Host-sar_sessao"  # DD-19: Secure, Path=/ e sem Domain, que o prefixo exige
COOKIE_PERFIL_DEV = "__Host-sar_perfil_dev"  # só vale para o superusuário, em desenvolvimento (DD-85)
METODOS_QUE_ALTERAM = frozenset({"POST", "PUT", "PATCH", "DELETE"})
PUBLICOS = frozenset({"saude.saude", "static", "acesso.entrar", "acesso.entrar_enviar"})

ROTULOS_PERFIL = PERFIS

GUARDA = PermissionGuard()
log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ItemMenu:
    rotulo: str
    endpoint: str
    permissoes: tuple[tuple[str, str | None], ...] = ()  # (operação, condição); vazio: todo perfil autenticado

    def visivel(self, contexto: Contexto) -> bool:
        return not self.permissoes or any(GUARDA.pode(contexto, op, cond) for op, cond in self.permissoes)


# Cada item aparece só para quem pode a operação da tela (AD-20). As telas dos incrementos seguintes entram aqui.
MENU: tuple[ItemMenu, ...] = (
    ItemMenu("Início", "acesso.inicio"),
    ItemMenu("Usuários", "usuarios.lista", (("acesso.usuario.consultar", None),)),
    ItemMenu(
        "Parâmetros",
        "parametros.lista",
        (
            ("config.parametro.alterar", "operacionais"),
            ("config.parametro.alterar", "técnicos"),
        ),
    ),
    ItemMenu("Minha senha", "acesso.senha", (("acesso.senha.trocar_propria", None),)),
)


def contexto_atual() -> Contexto:
    contexto: Contexto | None = g.get("contexto")
    if contexto is None:
        raise AcessoNegado()
    return contexto


def criar_app(servicos: ServicosWeb | None = None, config: ConfigWeb | None = None) -> Flask:
    """Sem serviços, só a página de saúde funciona: é o que os testes de unidade da web usam."""
    config = config or ConfigWeb(origem="https://localhost")
    app = Flask(__name__, template_folder="modelos", static_folder="static")
    app.config["SAR"] = config
    app.config["SAR_SERVICOS"] = servicos
    if config.proxies_confiaveis:
        n = config.proxies_confiaveis
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n, x_host=n)  # type: ignore[method-assign]

    from sar.web.rotas_acesso import bp as acesso
    from sar.web.rotas_parametros import bp as parametros
    from sar.web.rotas_saude import bp as saude
    from sar.web.rotas_usuarios import bp as usuarios

    app.register_blueprint(saude)
    if servicos is not None:
        for blueprint in (acesso, usuarios, parametros):
            app.register_blueprint(blueprint)

    @app.before_request
    def abrir_requisicao() -> None:
        g.requisicao_id = iniciar_requisicao()  # DD-81: liga log técnico e auditoria da mesma requisição
        g.inicio = time.perf_counter()

    @app.before_request
    def conferir_origem() -> None:
        """DD-84: além do cookie SameSite=Strict, todo POST precisa vir de uma página do próprio SAR."""
        if request.method in METODOS_QUE_ALTERAM and request.headers.get("Origin") != config.origem_normalizada:
            log.warning("web.origem_recusada")
            abort(403)

    @app.before_request
    def autenticar() -> RespostaWerkzeug | None:
        if servicos is None or request.endpoint in PUBLICOS:
            return None
        token = request.cookies.get(COOKIE_SESSAO)
        if not token:
            return redirect(url_for("acesso.entrar"))
        automatica = request.headers.get(CABECALHO_AUTOMATICA) == "1"
        try:
            contexto = servicos.sessoes.validar(token, request.remote_addr or "desconhecida", automatica)
        except SessaoEncerrada as erro:
            resposta = redirect(url_for("acesso.entrar", motivo=erro.motivo or "sessao"))
            resposta.delete_cookie(COOKIE_SESSAO, path="/", secure=True, httponly=True, samesite="Strict")
            return resposta
        g.superusuario = config.desenvolvimento and contexto.usuario_id in config.superusuarios
        if g.superusuario:
            escolhido = request.cookies.get(COOKIE_PERFIL_DEV)
            if escolhido in {p.value for p in ROTULOS_PERFIL}:
                contexto = replace(contexto, perfil=Perfil(escolhido))
        g.contexto = contexto
        identificar_usuario(contexto.usuario_id, contexto.perfil.value)  # DD-81: id e perfil, nunca o nome
        return None

    @app.context_processor
    def dados_do_layout() -> dict[str, Any]:
        contexto: Contexto | None = g.get("contexto")
        if contexto is None:
            return {}
        itens = [i for i in MENU if i.visivel(contexto)]
        return {
            "menu": itens,
            "perfil_rotulo": ROTULOS_PERFIL.get(contexto.perfil, contexto.perfil.value),
            "superusuario": g.get("superusuario", False),
            "perfis": ROTULOS_PERFIL,
            "perfil_atual": contexto.perfil,
        }

    @app.after_request
    def cabecalhos_e_registro(resposta: Response) -> Response:
        resposta.headers["Content-Security-Policy"] = POLITICA_CONTEUDO
        resposta.headers["X-Content-Type-Options"] = "nosniff"
        # same-origin, e não no-referrer: com no-referrer o navegador manda "Origin: null" até no formulário da
        # própria página, e a conferência da DD-84 recusaria tudo. Para outros sites, nada vaza.
        resposta.headers["Referrer-Policy"] = "same-origin"
        resposta.headers["Cache-Control"] = "no-store"  # nenhuma tela com dado fica no cache da estação (RNF-616)
        if "requisicao_id" in g:
            resposta.headers[CABECALHO_REQUISICAO] = g.requisicao_id
            # Sem caminho nem parâmetros: o acesso com caminho é registrado pelo Caddy, sem a query (DD-81).
            duracao = (time.perf_counter() - g.inicio) * 1000
            log.info("web.requisicao", extra={"resultado": str(resposta.status_code), "duracao_ms": duracao})
        return resposta

    @app.teardown_request
    def fechar_requisicao(_erro: BaseException | None) -> None:
        encerrar_requisicao()

    @app.errorhandler(AcessoNegado)
    def acesso_negado(_erro: AcessoNegado) -> tuple[str, int]:
        log.warning("web.acesso_negado")
        return render_template("proibido.html"), 403

    @app.errorhandler(NaoEncontrado)
    def nao_encontrado(_erro: NaoEncontrado) -> tuple[str, int]:
        return render_template("erro.html", titulo="Não encontrado"), 404

    @app.errorhandler(Exception)
    def erro_inesperado(erro: Exception) -> Response | HTTPException | tuple[str, int]:
        if isinstance(erro, HTTPException):
            return erro
        # Nunca str(erro) nem traceback: só o tipo e, em erro de banco, a restrição (DD-81, RNF-624).
        log.error("web.erro_inesperado", extra=campos_do_erro(erro))
        return render_template("erro.html"), 500

    return app
