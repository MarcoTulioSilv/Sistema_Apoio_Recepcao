"""Autorizações (§5.3), consulta da trilha (RNF-625) e integridade (RF-1011, DD-86)."""

from __future__ import annotations

from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, redirect, render_template, request, url_for
from werkzeug.wrappers import Response

from sar.modulo_01_acesso.contrato import AvisoDiagnostico, Conferencia, FiltroConsulta, PermissionGuard
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import RegraViolada
from sar.web import contexto_atual
from sar.web.configuracao import ServicosWeb

GUARDA = PermissionGuard()
autorizacoes = Blueprint("autorizacoes", __name__, url_prefix="/autorizacoes")
trilha = Blueprint("trilha", __name__, url_prefix="/trilha")
integridade = Blueprint("integridade", __name__, url_prefix="/integridade")
FUSO = ZoneInfo("America/Sao_Paulo")

ESTADOS = {
    "pendente": "Pendente",
    "executada": "Executada",
    "invalidada": "Invalidada: o registro mudou desde o pedido",
    "recusada": "Reprovada",
    "cancelada": "Cancelada",
}
RESULTADOS = {
    "executada": "Solicitação aprovada e executada.",
    "invalidada": (
        "O registro mudou desde o pedido: a solicitação foi invalidada sem executar. "
        "Peça de novo, se ainda for preciso."
    ),
    "recusada": "Solicitação reprovada.",
    "cancelada": "Solicitação cancelada.",
}
ERROS = {
    "autorizacao.ja_decidida": "Esta solicitação já foi decidida.",
    "autorizacao.motivo_obrigatorio": (
        "Informe o motivo, com até 500 caracteres. Para reprovar, o comentário é obrigatório."
    ),
    "autorizacao.motivo": "O motivo pode ter até 500 caracteres.",
    "aviso.explicacao_obrigatoria": "Informe a explicação recebida do TI.",
    "aviso.ja_encerrado": "Este aviso já foi encerrado.",
    "ancora.codigo_invalido": "O código tem 16 caracteres, como 7F3A-91C2-4D0B-E58A.",
}
CONFERENCIAS = {
    Conferencia.CONFERE: ("resultado", "O código confere com a trilha atual."),
    Conferencia.NAO_CONFERE: (
        "erro",
        "O código NÃO confere: a trilha atual difere da que existia quando o documento saiu. Avise o TI.",
    ),
    Conferencia.SEM_REGISTRO: ("erro", "Não há mais registro nem âncora com esse número (a trilha guarda 5 anos)."),
}


def _servicos() -> ServicosWeb:
    servicos: ServicosWeb = current_app.config["SAR_SERVICOS"]
    return servicos


# ------------------------------------------------------------------ autorizações
def _pagina_autorizacoes(contexto: Contexto, **dados: Any) -> str:
    servicos = _servicos()
    decide = GUARDA.pode(contexto, "acesso.autorizacao.decidir")
    pede = GUARDA.pode(contexto, "acesso.autorizacao.solicitar")
    return render_template(
        "autorizacoes.html",
        pendentes=servicos.autorizacoes.pendentes(contexto) if decide else [],
        minhas=servicos.autorizacoes.minhas(contexto) if pede else [],
        decide=decide,
        estados=ESTADOS,
        fuso=FUSO,
        **dados,
    )


def _pagina_analise(contexto: Contexto, solicitacao_id: str, **dados: Any) -> str:
    """Tela de análise de um pedido: a justificativa e, para quem decide, aprovar ou reprovar com comentário."""
    solicitacao = _servicos().autorizacoes.detalhe(contexto, solicitacao_id)
    decide = GUARDA.pode(contexto, "acesso.autorizacao.decidir") and solicitacao.estado == "pendente"
    return render_template(
        "autorizacao.html", s=solicitacao, decide=decide, estados=ESTADOS, fuso=FUSO,
        propria=solicitacao.solicitante_id == contexto.usuario_id, **dados,
    )  # fmt: skip


@autorizacoes.get("")
def lista() -> str:
    return _pagina_autorizacoes(contexto_atual(), resultado=RESULTADOS.get(request.args.get("resultado", "")))


@autorizacoes.get("/<solicitacao_id>")
def analise(solicitacao_id: str) -> str:
    return _pagina_analise(contexto_atual(), solicitacao_id)


def _decidir(acao: str, solicitacao_id: str) -> Response | str:
    contexto = contexto_atual()
    servico = _servicos().autorizacoes
    motivo = request.form.get("motivo", "")
    try:
        if acao == "aprovar":
            estado = servico.aprovar(contexto, solicitacao_id, motivo or None)
        elif acao == "recusar":
            servico.recusar(contexto, solicitacao_id, motivo)
            estado = "recusada"
        else:
            servico.cancelar(contexto, solicitacao_id)
            estado = "cancelada"
    except RegraViolada as erro:
        return _pagina_analise(contexto, solicitacao_id, erro=ERROS.get(erro.codigo, erro.codigo), comentario=motivo)
    return redirect(url_for("autorizacoes.lista", resultado=estado))


@autorizacoes.post("/<solicitacao_id>/aprovar")
def aprovar(solicitacao_id: str) -> Response | str:
    return _decidir("aprovar", solicitacao_id)


@autorizacoes.post("/<solicitacao_id>/recusar")
def recusar(solicitacao_id: str) -> Response | str:
    return _decidir("recusar", solicitacao_id)


@autorizacoes.post("/<solicitacao_id>/cancelar")
def cancelar(solicitacao_id: str) -> Response | str:
    return _decidir("cancelar", solicitacao_id)


# ------------------------------------------------------------------ trilha
def _inteiro(texto: str | None) -> int | None:
    return int(texto) if texto and texto.strip().isdigit() else None


def _data(texto: str | None) -> date | None:
    return date.fromisoformat(texto) if texto else None


@trilha.get("")
def consulta() -> str:
    contexto = contexto_atual()
    args = request.args
    try:
        filtro = FiltroConsulta(
            de=_data(args.get("de")),
            ate=_data(args.get("ate")),
            usuario_id=_inteiro(args.get("usuario_id")),
            operacao=args.get("operacao", "").strip() or None,
            entidade=args.get("entidade", "").strip() or None,
            entidade_id=args.get("entidade_id", "").strip() or None,
            antes_de_id=_inteiro(args.get("antes_de_id")),
        )
    except ValueError:
        return render_template(
            "trilha.html", pagina=None, filtros=args, erro="Informe as datas no formato do calendário."
        )
    pagina = _servicos().auditoria.consultar(contexto, filtro)
    proxima = {**args.to_dict(), "antes_de_id": pagina.proximo_antes_de_id} if pagina.proximo_antes_de_id else None
    return render_template("trilha.html", pagina=pagina, filtros=args, proxima=proxima)


# ------------------------------------------------------------------ integridade
def _pagina_integridade(contexto: Contexto, **dados: Any) -> str:
    servicos = _servicos()
    ve = GUARDA.pode(contexto, "acesso.aviso_integridade.ver")
    avisos = servicos.integridade.ver_avisos(contexto) if ve else []
    return render_template(
        "integridade.html",
        avisos=avisos,
        diagnostico=any(isinstance(a, AvisoDiagnostico) for a in avisos),
        encerra=GUARDA.pode(contexto, "acesso.aviso_integridade.encerrar"),
        confere=GUARDA.pode(contexto, "acesso.ancora.conferir"),
        **dados,
    )


@integridade.get("")
def painel() -> str:
    resultado = "Aviso encerrado." if request.args.get("resultado") == "encerrado" else None
    return _pagina_integridade(contexto_atual(), resultado=resultado)


@integridade.post("/avisos/<int:aviso_id>/encerrar")
def encerrar(aviso_id: int) -> Response | str:
    contexto = contexto_atual()
    try:
        _servicos().integridade.encerrar_aviso(contexto, aviso_id, request.form.get("explicacao", ""))
    except RegraViolada as erro:
        return _pagina_integridade(contexto, erro=ERROS.get(erro.codigo, erro.codigo))
    return redirect(url_for("integridade.painel", resultado="encerrado"))


@integridade.post("/conferir")
def conferir() -> str:
    contexto = contexto_atual()
    registro = _inteiro(request.form.get("registro"))
    codigo = request.form.get("codigo", "")
    if registro is None:
        return _pagina_integridade(contexto, erro="Informe o número do registro, que aparece no rodapé do documento.")
    try:
        conferencia = _servicos().integridade.conferir_codigo(contexto, registro, codigo)
    except RegraViolada as erro:
        return _pagina_integridade(contexto, erro=ERROS.get(erro.codigo, erro.codigo))
    tipo, mensagem = CONFERENCIAS[conferencia]
    return _pagina_integridade(contexto, **{tipo: mensagem})
