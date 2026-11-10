"""Jobs (DDS §13, DD-112): a situação de cada job do catálogo e as últimas execuções, só para leitura do TI. Executar
é no servidor, pela linha de comando."""

from __future__ import annotations

from flask import Blueprint, current_app, render_template

from sar.modulo_09_agendamento.contrato import Execucao, Resultado
from sar.web import contexto_atual
from sar.web.configuracao import ServicosWeb
from sar.web.formatos import data_hora

bp = Blueprint("agendamento", __name__, url_prefix="/agendamento")
RESULTADOS = {Resultado.SUCESSO: "Sucesso", Resultado.FALHA: "Falha", Resultado.SEM_TRABALHO: "Sem trabalho",
              Resultado.EM_ANDAMENTO: "Em andamento"}  # fmt: skip
EXECUCOES = 30
DISCO = "ocupacao_disco"


def _servicos() -> ServicosWeb:
    servicos: ServicosWeb = current_app.config["SAR_SERVICOS"]
    return servicos


def itens(execucao: Execucao) -> str:
    if execucao.itens is None:
        return ""
    return f"{execucao.itens}%" if execucao.job == DISCO else f"{execucao.itens:,}".replace(",", ".")


def resumo(execucao: Execucao | None) -> str:
    """A última execução em poucas palavras: falha com a data, sucesso com os itens, ou a passada parcial."""
    if execucao is None:
        return "Nunca executado"
    texto = RESULTADOS[execucao.resultado]
    if execucao.resultado is Resultado.FALHA:
        return f"{texto} em {data_hora(execucao.inicio)}"
    if execucao.parcial:
        return f"{texto}, parou no limite de horário e continua"
    quantidade = itens(execucao)
    if quantidade and execucao.resultado is Resultado.SUCESSO:
        return f"{texto}, {quantidade}" if execucao.job == DISCO else f"{texto}, {quantidade} itens"
    return texto


def intervalo(segundos: float) -> str:
    horas = int(segundos // 3600)
    if horas < 24:
        return f"{horas} h" if horas else f"{int(segundos // 60)} min"
    dias = horas // 24
    return f"{dias} {'dia' if dias == 1 else 'dias'}"


@bp.get("")
def lista() -> str:
    contexto = contexto_atual()
    servico = _servicos().agendamento
    situacao = servico.situacao(contexto)
    rotulos = {s.nome: s.rotulo for s in situacao}
    return render_template(
        "agendamento.html", situacao=situacao, execucoes=servico.execucoes(contexto, limite=EXECUCOES),
        rotulos=rotulos, resultados=RESULTADOS, resumo=resumo, itens=itens, intervalo=intervalo,
        atrasados=sum(1 for s in situacao if s.atrasado),
    )  # fmt: skip
