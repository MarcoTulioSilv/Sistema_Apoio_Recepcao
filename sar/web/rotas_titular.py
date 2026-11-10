"""Pedidos do titular (DDS §15, RF-1009): a lista com o prazo, o registro a partir da ficha e o atendimento pela
administração: a cópia ao titular num PDF só, concluir e negar com o fundamento."""

from __future__ import annotations

from datetime import date
from typing import Any

from flask import Blueprint, Response, current_app, redirect, render_template, request, url_for
from werkzeug.wrappers import Response as RespostaWerkzeug

from sar.modulo_01_acesso.contrato import PermissionGuard
from sar.modulo_11_titular.contrato import (
    FUNDAMENTO_GUARDA,
    Canal,
    FormaEntrega,
    SituacaoRequisicao,
    TipoRequisicao,
)
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import IndisponivelExterno, NaoEncontrado, RegraViolada
from sar.web import contexto_atual
from sar.web.configuracao import ServicosWeb
from sar.web.formatos import FUSO
from sar.web.rotas_emissao import CONVERSOR_FORA, ERROS_EMISSAO, anexo

bp = Blueprint("titular", __name__, url_prefix="/titular")
GUARDA = PermissionGuard()

TIPOS = {
    TipoRequisicao.CONFIRMACAO_ACESSO: "Confirmação e acesso aos dados",
    TipoRequisicao.CORRECAO: "Correção de dados",
    TipoRequisicao.INFORMACAO: "Informação sobre uso e compartilhamento",
    TipoRequisicao.ELIMINACAO: "Eliminação, anonimização ou bloqueio",
    TipoRequisicao.OUTROS: "Outros",
}
CANAIS = {Canal.PRESENCIAL: "Presencial", Canal.TELEFONE: "Telefone", Canal.EMAIL: "E-mail", Canal.CARTA: "Carta",
          Canal.OUTRO: "Outro"}  # fmt: skip
ENTREGAS = {FormaEntrega.EM_MAOS: "Em mãos ao titular", FormaEntrega.REPRESENTANTE: "A representante ou procurador",
            FormaEntrega.EMAIL: "Por e-mail", FormaEntrega.CORREIO: "Pelo correio"}  # fmt: skip
SITUACOES = {SituacaoRequisicao.ABERTA: "Aberto", SituacaoRequisicao.ATENDIDA: "Atendido",
             SituacaoRequisicao.NEGADA: "Negado"}  # fmt: skip
ERROS = {
    "titular.recebida_no_futuro": "A data de recebimento não pode ser depois de hoje.",
    "titular.desfecho": "Descreva o desfecho, com pelo menos 10 caracteres.",
    "titular.negativa_sem_fundamento": "A negativa precisa do fundamento, com pelo menos 10 caracteres.",
    "titular.encerrada": "Este pedido já foi encerrado.",
    "titular.nao_e_acesso": "A cópia ao titular é só para pedido de confirmação e acesso.",
    **ERROS_EMISSAO,
}
RESULTADOS = {
    "registrado": "Pedido registrado. O prazo de resposta aparece aqui e na lista de pedidos.",
    "concluido": "Pedido concluído.",
    "negado": "Pedido negado, com o fundamento registrado.",
}


def _servicos() -> ServicosWeb:
    servicos: ServicosWeb = current_app.config["SAR_SERVICOS"]
    return servicos


def _rotulos() -> dict[str, Any]:
    return {"tipos": TIPOS, "canais": CANAIS, "entregas": ENTREGAS, "situacoes": SITUACOES}


@bp.get("")
def lista() -> str:
    contexto = contexto_atual()
    filtro = request.args.get("situacao", SituacaoRequisicao.ABERTA.value)
    situacao = SituacaoRequisicao(filtro) if filtro in SituacaoRequisicao else None
    pedidos = _servicos().titular.consultar(contexto, situacao)
    return render_template("titular_lista.html", pedidos=pedidos, situacao=filtro if situacao else "todas",
                           resultado=RESULTADOS.get(request.args.get("resultado", "")), **_rotulos())  # fmt: skip


def _novo(contexto: Contexto, paciente_id: int, **dados: Any) -> str:
    identificacao = _servicos().pacientes.identificar(contexto, [paciente_id]).get(paciente_id)
    if identificacao is None:
        raise NaoEncontrado()
    hoje = contexto.instante.astimezone(FUSO).date().isoformat()
    return render_template("titular_novo.html", paciente=identificacao, hoje=hoje, **_rotulos(), **dados)


@bp.get("/novo/<int:paciente_id>")
def novo(paciente_id: int) -> str:
    contexto = contexto_atual()
    GUARDA.exigir(contexto, "titular.requisicao.registrar")
    return _novo(contexto, paciente_id)


@bp.post("/novo/<int:paciente_id>")
def registrar(paciente_id: int) -> RespostaWerkzeug | str:
    contexto = contexto_atual()
    tipo, canal, recebida = (
        request.form.get("tipo", ""),
        request.form.get("canal", ""),
        request.form.get("recebida", ""),
    )
    try:
        data = date.fromisoformat(recebida)
    except ValueError:
        return _novo(contexto, paciente_id, erro="Informe a data em que o pedido chegou.")
    if tipo not in TipoRequisicao or canal not in Canal:
        return _novo(contexto, paciente_id, erro="Escolha o tipo do pedido e o canal.")
    try:
        pedido = _servicos().titular.registrar(contexto, paciente_id, TipoRequisicao(tipo), Canal(canal), data)
    except RegraViolada as erro:
        return _novo(contexto, paciente_id, erro=ERROS.get(erro.codigo, "Confira os dados."))
    return redirect(url_for("titular.ver", requisicao_id=pedido, resultado="registrado"))


def _detalhe(contexto: Contexto, requisicao_id: int, **dados: Any) -> str:
    pedido = _servicos().titular.ver(contexto, requisicao_id)
    sugestao = FUNDAMENTO_GUARDA if pedido.tipo is TipoRequisicao.ELIMINACAO else ""
    return render_template("titular_pedido.html", p=pedido, sugestao_fundamento=sugestao,
                           pode_atender=GUARDA.pode(contexto, "titular.requisicao.atender"),
                           pode_copia=GUARDA.pode(contexto, "titular.copia.gerar"), **_rotulos(), **dados)  # fmt: skip


@bp.get("/<int:requisicao_id>")
def ver(requisicao_id: int) -> str:
    return _detalhe(contexto_atual(), requisicao_id, resultado=RESULTADOS.get(request.args.get("resultado", "")))


@bp.post("/<int:requisicao_id>/copia")
def copia(requisicao_id: int) -> Response | tuple[str, int]:
    contexto = contexto_atual()
    entrega = request.form.get("entrega", "")
    try:
        if entrega not in FormaEntrega:
            raise RegraViolada("titular.entrega")
        pacote = _servicos().titular.atender_acesso(contexto, requisicao_id, FormaEntrega(entrega))
    except RegraViolada as erro:
        mensagem = ERROS.get(erro.codigo, "Escolha como a cópia será entregue.")
        return _detalhe(contexto, requisicao_id, erro=mensagem), 422
    except IndisponivelExterno:
        return _detalhe(contexto, requisicao_id, erro=CONVERSOR_FORA), 503
    return anexo(pacote.pdf, pacote.nome_arquivo, "application/pdf")


def _encerrar(requisicao_id: int, negar: bool) -> RespostaWerkzeug | tuple[str, int]:
    contexto = contexto_atual()
    texto = request.form.get("desfecho", "")
    try:
        if negar:
            _servicos().titular.negar(contexto, requisicao_id, texto)
        else:
            _servicos().titular.concluir(contexto, requisicao_id, texto)
    except RegraViolada as erro:
        return _detalhe(contexto, requisicao_id, erro=ERROS.get(erro.codigo, "Confira o texto."), texto=texto), 422
    return redirect(url_for("titular.ver", requisicao_id=requisicao_id, resultado="negado" if negar else "concluido"))


@bp.post("/<int:requisicao_id>/concluir")
def concluir(requisicao_id: int) -> RespostaWerkzeug | tuple[str, int]:
    return _encerrar(requisicao_id, negar=False)


@bp.post("/<int:requisicao_id>/negar")
def negar(requisicao_id: int) -> RespostaWerkzeug | tuple[str, int]:
    return _encerrar(requisicao_id, negar=True)
