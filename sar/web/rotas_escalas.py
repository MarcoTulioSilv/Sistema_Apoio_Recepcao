"""Escalas da enfermagem (DDS §7.1, §7.7; RF-401 a RF-406, RF-921): distribuição e alocação em lote, a escala de um
paciente com trocas e extras, e a ciência das presenças acrescentadas. Os códigos 1-seg, 1-ter… aparecem só aqui
(DD-75). Quem não registra (recepção, administração, visualizador) só consulta."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for
from werkzeug.wrappers import Response

from sar.modulo_01_acesso.contrato import PermissionGuard
from sar.modulo_03_operacao.contrato import PacienteNaEscala
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import NaoEncontrado, RegraViolada, RequerAutorizacao
from sar.web import contexto_atual
from sar.web.configuracao import ServicosWeb

bp = Blueprint("escalas", __name__)
GUARDA = PermissionGuard()
FUSO = ZoneInfo("America/Sao_Paulo")

MENSAGENS = {
    "INV-03": "O paciente não tem tratamento em andamento nessa data.",
    "INV-04": "O paciente não tem tratamento em andamento nessa data.",
    "INV-01": "Não é possível registrar nada depois do óbito.",
    "P-11": "A troca precisa ficar no mesmo mês. Registre ausência num mês e extra planejada no outro.",
    "troca.origem_fora_da_escala": "Nessa data o paciente não tem sessão na escala dele.",
    "troca.destino_na_propria_escala": "O destino é a própria escala do paciente: não é troca.",
    "troca.origem_repetida": "Já existe troca saindo dessa data.",
    "extra.na_propria_escala": "Essa é a própria escala do paciente: não é extra.",
    "extra.repetida": "Essa extra já está registrada.",
    "sessao.inexistente": "Não há sessão dessa escala nessa data.",
    "escala.inexistente": "Escala inexistente.",
    "paciente.inexistente": "Paciente não encontrado.",
    "motivo.longo": "O motivo pode ter até 300 caracteres.",
    "autorizacao.motivo_obrigatorio": "Informe o motivo do pedido.",
    "ciencia.ja_registrada": "A ciência dessa presença já foi registrada.",
    "ciencia.desnecessaria": "Essa presença não precisa de ciência.",
}
AUTORIZACAO = "Alcança sessão já confirmada: precisa de autorização da administração. Informe o motivo e peça."


def _servicos() -> ServicosWeb:
    servicos: ServicosWeb = current_app.config["SAR_SERVICOS"]
    return servicos


def _hoje(contexto: Contexto) -> date:
    return contexto.instante.astimezone(FUSO).date()


def _data(campo: str, padrao: date | None = None) -> date | None:
    texto = (request.form.get(campo) or request.args.get(campo) or "").strip()
    if not texto:
        return padrao
    try:
        return date.fromisoformat(texto)
    except ValueError:
        return None


def _escala(campo: str) -> int | None:
    """ "" = sem alocação (RF-403)."""
    valor = request.form.get(campo, "")
    if valor == "":
        return None
    if not valor.isdigit():
        abort(400)
    return int(valor)


def _numero(campo: str) -> int:
    valor = request.form.get(campo, "")
    if not valor.isdigit():
        abort(400)
    return int(valor)


# ------------------------------------------------------------------ visão geral (RF-404, RF-405, RF-921)
def _geral(contexto: Contexto, data: date, **extra: Any) -> str:
    """Os seis turnos em duas colunas (segunda, quarta e sexta; terça, quinta e sábado) e, no alto, quem está sem
    alocação. `escolhidas` traz o que foi enviado e não gravou (erro no lote), para nada se perder na volta."""
    servicos = _servicos()
    # Os de segunda, quarta e sexta primeiro, cada grupo pelo turno: 1-seg, 2-seg, 3-seg, 1-ter, 2-ter, 3-ter.
    escalas = sorted(servicos.escalas.escalas(contexto), key=lambda e: (0 not in e.dias, e.turno))
    distribuicao = servicos.escalas.distribuicao(contexto, data)
    escolhidas: dict[int, str] = extra.pop("escolhidas", {})
    atual = {p.paciente_id: str(p.escala.id) if p.escala else "" for p in distribuicao}
    valor = {pid: escolhidas.get(pid, a) for pid, a in atual.items()}
    por_zona: dict[str, list[PacienteNaEscala]] = {}
    for p in distribuicao:
        por_zona.setdefault(valor[p.paciente_id], []).append(p)
    return render_template(
        "escalas.html",
        data=data,
        inicio=extra.pop("inicio", data),
        escalas=escalas,
        colunas=[[e for e in escalas if 0 in e.dias], [e for e in escalas if 1 in e.dias]],
        distribuicao=distribuicao,
        atual=atual,
        valor=valor,
        por_zona=por_zona,
        registra=GUARDA.pode(contexto, "operacao.alocacao.registrar_em_lote"),
        a_cientificar=servicos.frequencia.presencas_sem_registro(contexto)
        if GUARDA.pode(contexto, "operacao.presenca.dar_ciencia")
        else None,
        **extra,
    )


@bp.get("/escalas")
def geral() -> str:
    contexto = contexto_atual()
    data = _data("data", _hoje(contexto)) or _hoje(contexto)
    return _geral(contexto, data, resultado=request.args.get("resultado"))


@bp.post("/escalas/lote")
def lote() -> Response | str:
    """Só as linhas em que a escala escolhida difere da atual; tudo numa transação (RF-405)."""
    contexto = contexto_atual()
    inicio = _data("inicio")
    if inicio is None:
        return _geral(contexto, _hoje(contexto), erro="Informe a data a partir da qual as escalas valem.")
    mudancas: list[tuple[int, int | None]] = []
    for chave in request.form:
        if chave.startswith("escala-"):
            pid = chave.removeprefix("escala-")
            if not pid.isdigit():
                abort(400)
            if request.form.get(chave, "") != request.form.get(f"atual-{pid}", ""):
                mudancas.append((int(pid), _escala(chave)))
    if not mudancas:
        return _geral(contexto, inicio, erro="Nenhuma escala foi mudada.")
    escolhidas = {pid: "" if escala is None else str(escala) for pid, escala in mudancas}
    try:
        _servicos().escalas.alocar_em_lote(contexto, mudancas, inicio)
    except RegraViolada as erro:
        nome = next((p.nome for p in _servicos().escalas.distribuicao(contexto, inicio)
                     if p.paciente_id == erro.detalhe.get("paciente_id")), None)  # fmt: skip
        mensagem = MENSAGENS.get(erro.codigo, "Não foi possível alocar.") + (f" ({nome})" if nome else "")
        return _geral(contexto, inicio, erro=mensagem + " Nada foi gravado.", escolhidas=escolhidas, inicio=inicio)
    except RequerAutorizacao:
        texto = "Alguma mudança alcança sessão já confirmada, e nada foi gravado. Faça essa pela página do paciente, "
        return _geral(contexto, inicio, erro=texto + "que permite pedir autorização.", escolhidas=escolhidas,
                      inicio=inicio)  # fmt: skip
    quantidade = f"{len(mudancas)} {'alocação registrada' if len(mudancas) == 1 else 'alocações registradas'}"
    return redirect(url_for("escalas.geral", data=inicio.isoformat(), resultado=quantidade))


@bp.post("/escalas/ciencia")
def ciencia() -> Response | str:
    contexto = contexto_atual()
    try:
        _servicos().frequencia.dar_ciencia(contexto, _numero("presenca_id"))
    except RegraViolada as erro:
        return _geral(contexto, _hoje(contexto), erro=MENSAGENS.get(erro.codigo, "Não foi possível registrar."))
    except NaoEncontrado:
        abort(404)
    return redirect(url_for("escalas.geral", resultado="Ciência registrada."))


# ------------------------------------------------------------------ escala de um paciente (RF-402, RF-503, RF-504)
def _paciente(contexto: Contexto, paciente_id: int, **extra: Any) -> str:
    servicos = _servicos()
    try:
        escala = servicos.escalas.do_paciente(contexto, paciente_id, _hoje(contexto))
    except NaoEncontrado:
        abort(404)
    return render_template(
        "escalas_paciente.html", p=escala, escalas=servicos.escalas.escalas(contexto), hoje=_hoje(contexto),
        registra=GUARDA.pode(contexto, "operacao.alocacao.registrar"), **extra,
    )  # fmt: skip


@bp.get("/escalas/pacientes/<int:paciente_id>")
def paciente(paciente_id: int) -> str:
    return _paciente(contexto_atual(), paciente_id, resultado=request.args.get("resultado"))


def _registrar(
    paciente_id: int, acao: Callable[[Contexto], object], feito: str, pedido: dict[str, Any]
) -> Response | str:
    """Executa; RegraViolada vira mensagem e RequerAutorizacao abre o pedido com motivo, com os mesmos dados."""
    contexto = contexto_atual()
    try:
        acao(contexto)
    except RegraViolada as erro:
        return _paciente(contexto, paciente_id, erro=MENSAGENS.get(erro.codigo, "Não foi possível registrar."))
    except RequerAutorizacao as erro:
        return _paciente(contexto, paciente_id, erro=AUTORIZACAO, pedido={"tipo": erro.tipo, **pedido})
    except NaoEncontrado:
        abort(404)
    return redirect(url_for("escalas.paciente", paciente_id=paciente_id, resultado=feito))


@bp.post("/escalas/pacientes/<int:paciente_id>/alocar")
def alocar(paciente_id: int) -> Response | str:
    inicio, escala = _data("inicio"), _escala("escala_id")
    if inicio is None:
        return _paciente(contexto_atual(), paciente_id, erro="Informe a data a partir da qual a escala vale.")
    pedido = {"acao": "alocar", "escala_id": "" if escala is None else str(escala), "inicio": inicio.isoformat()}
    return _registrar(
        paciente_id,
        lambda c: _servicos().escalas.alocar(c, paciente_id, escala, inicio),
        "Alocação registrada.",
        pedido,
    )


@bp.post("/escalas/pacientes/<int:paciente_id>/troca")
def troca(paciente_id: int) -> Response | str:
    origem, destino = _data("origem"), _data("destino")
    if origem is None or destino is None:
        return _paciente(contexto_atual(), paciente_id, erro="Informe as datas de origem e de destino.")
    escala = _numero("escala_destino_id")
    return _registrar(
        paciente_id, lambda c: _servicos().escalas.registrar_troca(c, paciente_id, origem, destino, escala),
        "Troca registrada. A declaração (DOC-03) fica pendente para a recepção.", {},
    )  # fmt: skip


@bp.post("/escalas/pacientes/<int:paciente_id>/troca/<int:troca_id>/cancelar")
def cancelar_troca(paciente_id: int, troca_id: int) -> Response | str:
    pedido = {"acao": "cancelar_troca", "troca_id": str(troca_id)}
    return _registrar(
        paciente_id, lambda c: _servicos().escalas.cancelar_troca(c, troca_id), "Troca cancelada.", pedido
    )


@bp.post("/escalas/pacientes/<int:paciente_id>/extra")
def extra(paciente_id: int) -> Response | str:
    data = _data("data")
    if data is None:
        return _paciente(contexto_atual(), paciente_id, erro="Informe a data da extra.")
    escala = _numero("escala_id")
    return _registrar(
        paciente_id, lambda c: _servicos().escalas.registrar_extra(c, paciente_id, data, escala),
        "Extra planejada registrada. O termo (DOC-07) do mês fica pendente para a recepção.", {},
    )  # fmt: skip


@bp.post("/escalas/pacientes/<int:paciente_id>/extra/<int:extra_id>/cancelar")
def cancelar_extra(paciente_id: int, extra_id: int) -> Response | str:
    return _registrar(paciente_id, lambda c: _servicos().escalas.cancelar_extra(c, extra_id), "Extra cancelada.", {})


@bp.post("/escalas/pacientes/<int:paciente_id>/pedir")
def pedir(paciente_id: int) -> Response | str:
    """Pedido à administração, com motivo, do que alcançou sessão confirmada (DEC-42)."""
    contexto = contexto_atual()
    motivo = request.form.get("motivo", "")
    escalas = _servicos().escalas
    acao = request.form.get("acao")
    try:
        if acao == "alocar":
            inicio = _data("inicio")
            if inicio is None:
                abort(400)
            escalas.solicitar_alocacao_retroativa(contexto, paciente_id, _escala("escala_id"), inicio, motivo)
        elif acao == "cancelar_troca":
            escalas.solicitar_cancelamento_troca(contexto, _numero("troca_id"), motivo)
        else:
            abort(400)
    except RegraViolada as erro:
        return _paciente(contexto, paciente_id, erro=MENSAGENS.get(erro.codigo, "Não foi possível pedir."))
    except NaoEncontrado:
        abort(404)
    return redirect(url_for("escalas.paciente", paciente_id=paciente_id, resultado="Pedido enviado à administração."))
