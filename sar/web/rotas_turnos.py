"""Sessões de turno na tela inicial (DDS §7.3, DD-76): os quadros de presentes e faltantes, o acréscimo, a confirmação
e a sessão não realizada. Cada ação devolve o painel inteiro; com o htmx, só o painel é trocado; sem script, a tela
inteira volta."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, current_app, render_template, request

from sar.modulo_01_acesso.contrato import PermissionGuard
from sar.modulo_03_operacao.contrato import EstadoSessao, Origem, ResumoSessao
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import AcessoNegado, ConflitoDeVersao, NaoEncontrado, RegraViolada, RequerAutorizacao
from sar.web import contexto_atual
from sar.web.configuracao import ServicosWeb

bp = Blueprint("turnos", __name__)
GUARDA = PermissionGuard()
FUSO = ZoneInfo("America/Sao_Paulo")
MAXIMO_QUADROS_ANTERIORES = 2  # sessões de dias anteriores com quadro; as demais, em lista

MENSAGENS = {
    "sessao.fora_da_marcacao": "A marcação abre uma hora antes do início do turno.",
    "sessao.confirmacao_nao_liberada": "A confirmação é liberada na última hora do turno.",
    "sessao.confirmada": "Esta sessão já foi confirmada.",
    "sessao.nao_realizada": "Esta sessão foi registrada como não realizada.",
    "sessao.inexistente": "Não há sessão nesta data e turno.",
    "sessao.futura": "A sessão só pode ser registrada como não realizada depois do início do turno.",
    "implantacao.indefinida": "A data de implantação ainda não foi definida. O TI define a data em Parâmetros.",
    "paciente.fora_da_lista": "Este paciente não está na lista desta sessão.",
    "paciente.ja_na_lista": "Este paciente já está na lista desta sessão.",
    "paciente.nao_acrescentado": "Só é possível retirar quem foi acrescentado nesta sessão.",
    "INV-04": "O paciente não tem tratamento em andamento nesta data.",
    "INV-01": "Não é possível registrar presença depois do óbito.",
    "ligacao.invalida": "A ausência escolhida não pode ser ligada a esta presença. Escolha outra ou nenhuma.",
    "motivo.obrigatorio": "Informe o motivo.",
    "motivo.longo": "O motivo pode ter até 300 caracteres.",
}
AUTORIZACAO = "Esta sessão já foi confirmada. A mudança precisa de autorização da administração."
CONFLITO = "Outra estação mudou esta sessão enquanto você a via. Confira a lista atualizada e confirme de novo."

# Estado do contrato → atributo que o CSS e o protótipo usam (data-estado), rótulo do selo e etapa.
ESTADOS: dict[EstadoSessao, tuple[str, str, str | None]] = {
    EstadoSessao.FUTURA: ("futura", "Em breve", None),
    EstadoSessao.EM_PREPARACAO: ("preparacao", "Em preparação", "preparacao"),
    EstadoSessao.DEVIDA: ("aberta", "Aberta", "aberta"),
    EstadoSessao.CONFIRMACAO_LIBERADA: ("liberada", "Confirmação liberada", "aberta"),
    EstadoSessao.URGENCIA: ("vencida", "Aguardando confirmação", "aberta"),
    EstadoSessao.CONFIRMADA: ("confirmada", "Confirmada", "confirmada"),
    EstadoSessao.NAO_REALIZADA: ("confirmada", "Não realizada", "confirmada"),
}
ORIGENS = {
    Origem.TROCA_SAINDO: "Troca: vai em outra sessão",
    Origem.TROCA_CHEGANDO: "Troca: vem de outra sessão",
    Origem.EXTRA_PLANEJADA: "Extra planejada",
    Origem.ACRESCENTADO: "Acrescentado pela recepção",
}


def _servicos() -> ServicosWeb:
    servicos: ServicosWeb = current_app.config["SAR_SERVICOS"]
    return servicos


def hoje(contexto: Contexto) -> date:
    return contexto.instante.astimezone(FUSO).date()


def _data(texto: str) -> date:
    try:
        return date.fromisoformat(texto)
    except ValueError:
        abort(404)


def _numero(campo: str) -> int:
    valor = request.form.get(campo, "")
    if not valor.isdigit():
        abort(400)
    return int(valor)


@dataclass(frozen=True, slots=True)
class Permissoes:
    marcar: bool
    acrescentar: bool
    confirmar: bool
    nao_realizada: bool

    @classmethod
    def de(cls, contexto: Contexto) -> Permissoes:
        return cls(
            GUARDA.pode(contexto, "operacao.frequencia.marcar_ausencia"),
            GUARDA.pode(contexto, "operacao.frequencia.acrescentar_paciente"),
            GUARDA.pode(contexto, "operacao.sessao.confirmar"),
            GUARDA.pode(contexto, "operacao.sessao.registrar_nao_realizada"),
        )


def dados_do_painel(contexto: Contexto, mensagem: str | None = None, foco: str | None = None) -> dict[str, Any]:
    """O que o painel mostra; vazio para quem não vê sessão (o TI nunca recebe dado de paciente)."""
    if not GUARDA.pode(contexto, "operacao.sessao.ver"):
        return {"ve_turnos": False}
    servicos = _servicos()
    painel = servicos.turnos.painel(contexto)
    anteriores = [s for s in painel.sessoes if s.data < hoje(contexto)]
    com_quadro = anteriores[:MAXIMO_QUADROS_ANTERIORES] + [s for s in painel.sessoes if s.data >= hoje(contexto)]
    em_lista: list[ResumoSessao] = anteriores[MAXIMO_QUADROS_ANTERIORES:]
    telas = [servicos.turnos.tela_do_turno(contexto, s.data, s.escala.id) for s in com_quadro]
    return {
        "ve_turnos": True,
        "implantacao_definida": painel.implantacao_definida,
        "telas": telas,
        "em_lista": em_lista,
        "pode": Permissoes.de(contexto),
        "estados": ESTADOS,
        "origens": ORIGENS,
        "hoje": hoje(contexto),
        "mensagem": mensagem,
        "foco": foco,
    }


def _resposta(contexto: Contexto, mensagem: str | None = None, foco: str | None = None) -> str:
    """Com o htmx, só o painel; sem script, a tela inicial inteira."""
    dados = dados_do_painel(contexto, mensagem, foco)
    if request.headers.get("HX-Request"):
        return render_template("_turnos.html", **dados)
    return render_template("inicio.html", aniversariantes=aniversariantes(contexto), **dados)


def aniversariantes(contexto: Contexto) -> list[str] | None:
    if not GUARDA.pode(contexto, "relatorio.aniversariantes.ver"):
        return None
    return _servicos().relatorios.aniversariantes(contexto, hoje(contexto))


def _executar(
    contexto: Contexto,
    acao: Callable[[], Any],
    sucesso: str | Callable[[Any], str] | None = None,
    foco: str | None = None,
) -> str:
    try:
        retorno = acao()
    except RegraViolada as erro:
        return _resposta(contexto, MENSAGENS.get(erro.codigo, "Não foi possível fazer a mudança."), foco)
    except RequerAutorizacao:
        return _resposta(contexto, AUTORIZACAO, foco)
    except ConflitoDeVersao:
        return _resposta(contexto, CONFLITO, foco)
    mensagem = sucesso(retorno) if callable(sucesso) else sucesso
    return _resposta(contexto, mensagem, foco)


# ------------------------------------------------------------------ painel e sessão avulsa
@bp.get("/turnos/painel")
def painel() -> str:
    """Atualização automática a cada minuto, com a marca de requisição automática (DD-57)."""
    return render_template("_turnos.html", **dados_do_painel(contexto_atual()))


@bp.get("/turnos/<data>/<int:escala>")
def sessao(data: str, escala: int) -> str:
    """Uma sessão anterior que ficou sem confirmação, aberta a partir da lista do painel."""
    contexto = contexto_atual()
    try:
        tela = _servicos().turnos.tela_do_turno(contexto, _data(data), escala)
    except RegraViolada:
        abort(404)
    return render_template(
        "sessao_turno.html", tela=tela, pode=Permissoes.de(contexto), estados=ESTADOS, origens=ORIGENS,
        hoje=hoje(contexto),
    )  # fmt: skip


# ------------------------------------------------------------------ marcações (P-13, DD-24)
@bp.post("/turnos/<data>/<int:escala>/presenca")
def presenca(data: str, escala: int) -> str:
    contexto, dia = contexto_atual(), _data(data)
    paciente_id = _numero("paciente_id")
    presente = request.form.get("presente") == "1"
    turnos = _servicos().turnos
    acao = turnos.desmarcar if presente else turnos.marcar_ausencia
    foco = f"paciente-{data}-{escala}-{paciente_id}"
    return _executar(contexto, lambda: acao(contexto, dia, escala, paciente_id), foco=foco)


@bp.post("/turnos/<data>/<int:escala>/retirar")
def retirar(data: str, escala: int) -> str:
    contexto, dia = contexto_atual(), _data(data)
    paciente_id = _numero("paciente_id")
    turnos = _servicos().turnos
    return _executar(
        contexto,
        lambda: turnos.retirar_acrescentado(contexto, dia, escala, paciente_id),
        "Paciente retirado da sessão.",
    )


# ------------------------------------------------------------------ acréscimo (RF-917, RF-506, DD-25)
@bp.post("/turnos/<data>/<int:escala>/candidatos")
def candidatos(data: str, escala: int) -> str:
    """Busca enquanto se digita, a partir de 3 caracteres; sem registro na trilha a cada tecla (DD-90)."""
    contexto = contexto_atual()
    if not GUARDA.pode(contexto, "operacao.frequencia.acrescentar_paciente"):
        raise AcessoNegado()
    termo = request.form.get("termo", "").strip()
    pagina = _servicos().pacientes.listar(contexto, termo, 0, 8, registrar_na_trilha=False) if len(termo) >= 3 else None
    return render_template("_candidatos.html", pagina=pagina, data=data, escala=escala, termo=termo)


@bp.post("/turnos/<data>/<int:escala>/escolher")
def escolher(data: str, escala: int) -> str:
    """As ausências do mês, para ligar a presença a uma delas (RF-917), e as extras (RF-506). O nome vem no corpo,
    nunca na URL (DD-81)."""
    contexto, dia = contexto_atual(), _data(data)
    paciente_id = _numero("paciente_id")
    try:
        frequencia = _servicos().turnos.frequencia_ao_acrescentar(contexto, paciente_id, dia)
    except NaoEncontrado:
        abort(404)
    return render_template(
        "_acrescentar.html", frequencia=frequencia, data=data, escala=escala, paciente_id=paciente_id,
        nome=request.form.get("nome", ""),
    )  # fmt: skip


@bp.post("/turnos/<data>/<int:escala>/acrescentar")
def acrescentar(data: str, escala: int) -> str:
    contexto, dia = contexto_atual(), _data(data)
    paciente_id = _numero("paciente_id")
    ausencia = request.form.get("ausencia_id", "")
    ausencia_id = int(ausencia) if ausencia.isdigit() else None

    def sucesso(frequencia: Any) -> str:
        texto = "Paciente acrescentado à sessão."
        if frequencia.aviso_extra:
            texto += f" Atenção: são {frequencia.extras_no_mes} sessões extras no mês (limite de 4, RN-01)."
        return texto

    turnos = _servicos().turnos
    return _executar(
        contexto, lambda: turnos.acrescentar_paciente(contexto, dia, escala, paciente_id, ausencia_id), sucesso,
        foco=f"paciente-{data}-{escala}-{paciente_id}",
    )  # fmt: skip


# ------------------------------------------------------------------ confirmação e não realizada (DD-32, P-12)
@bp.post("/turnos/<data>/<int:escala>/confirmar")
def confirmar(data: str, escala: int) -> str:
    contexto, dia = contexto_atual(), _data(data)
    versao = _numero("versao")
    turnos = _servicos().turnos
    mensagem = "Sessão confirmada. Depois de confirmada, só muda com autorização da administração."
    return _executar(contexto, lambda: turnos.confirmar(contexto, dia, escala, versao), mensagem)


@bp.post("/turnos/<data>/<int:escala>/nao-realizada")
def nao_realizada(data: str, escala: int) -> str:
    contexto, dia = contexto_atual(), _data(data)
    motivo = request.form.get("motivo", "")
    turnos = _servicos().turnos
    mensagem = "Sessão registrada como não realizada: sai das previstas e não gera ausências."
    return _executar(contexto, lambda: turnos.registrar_nao_realizada(contexto, dia, escala, motivo), mensagem)
