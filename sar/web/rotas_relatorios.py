"""Relatórios (DDS §9.3): a lista do que o perfil vê, a tela de cada relatório com os filtros e a tabela, e a
exportação em PDF ou XLSX pela administração (RF-912, RNF-607). A tela é a terceira saída do mesmo modelo tabular
(DD-44): as mesmas colunas, filtros e marcas do arquivo. Os filtros vão na URL; nenhum é dado de paciente."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from flask import Blueprint, Response, current_app, render_template, request
from werkzeug.datastructures import MultiDict

from sar.modulo_01_acesso.contrato import PermissionGuard
from sar.modulo_02_cadastro.contrato import TipoEvento
from sar.modulo_05_emissao.contrato import Filtros, FormatoExportacao, ModoConvenio, Relatorio
from sar.nucleo.erros import AcessoNegado, NaoEncontrado, RegraViolada
from sar.web import contexto_atual
from sar.web.configuracao import ServicosWeb
from sar.web.formatos import FUSO
from sar.web.rotas_emissao import anexo

bp = Blueprint("relatorios", __name__, url_prefix="/relatorios")
GUARDA = PermissionGuard()

EVENTOS = {TipoEvento.OBITO: "Óbito", TipoEvento.ALTA: "Alta", TipoEvento.TRANSFERENCIA: "Transferência",
           TipoEvento.TRANSPLANTE: "Transplante", TipoEvento.DESISTENCIA: "Desistência"}  # fmt: skip
DESCRICOES = {
    Relatorio.ENTRADAS: "Pacientes que começaram ou retornaram ao tratamento no período.",
    Relatorio.CIDADE: "Pacientes em tratamento por município de residência numa data.",
    Relatorio.EVENTOS: "Altas, óbitos, transferências, transplantes e desistências no período.",
    Relatorio.CONVENIO: "Pacientes por convênio ou SUS, numa data ou no período.",
    Relatorio.FREQUENCIA_MENSAL: "Previstas, realizadas, ausências e extras de cada paciente no mês fechado.",
    Relatorio.BALANCO_MENSAL: "Ausências não compensadas, reposições e extras definitivas no mês fechado.",
    Relatorio.PREVIA: "O balanço do mês em andamento, que ainda muda até o fechamento.",
    Relatorio.OCUPACAO: "Pacientes alocados em cada escala numa data.",
    Relatorio.FAIXA_ETARIA: "Pacientes em tratamento por faixa de idade numa data.",
    Relatorio.SEXO: "Pacientes em tratamento por sexo numa data.",
    Relatorio.RECORTE_LIVRE: "Sessões realizadas por paciente num intervalo qualquer.",
}
ERROS = {
    "relatorio.filtro.periodo": "Informe o período: a data inicial não pode ser depois da final.",
    "relatorio.filtro.data_referencia": "Informe a data de referência.",
    "relatorio.filtro.competencia": "Escolha o mês.",
    "relatorio.filtro.tipo_evento": "Escolha um tipo de evento da lista.",
}


def _servicos() -> ServicosWeb:
    servicos: ServicosWeb = current_app.config["SAR_SERVICOS"]
    return servicos


def _relatorio(codigo: str) -> Relatorio:
    try:
        return Relatorio(codigo)
    except ValueError:
        raise NaoEncontrado() from None


def _data(texto: str | None) -> date | None:
    try:
        return date.fromisoformat(texto) if texto else None
    except ValueError:
        return None


def _filtros(dados: MultiDict[str, str]) -> Filtros:
    modo = dados.get("modo", ModoConvenio.SITUACAO.value)
    return Filtros(
        inicio=_data(dados.get("inicio")), fim=_data(dados.get("fim")), data_referencia=_data(dados.get("data")),
        competencia=dados.get("competencia") or None, tipo_evento=dados.get("tipo_evento") or None,
        modo_convenio=ModoConvenio(modo) if modo in ModoConvenio else ModoConvenio.SITUACAO,
    )  # fmt: skip


def _hoje() -> date:
    return contexto_atual().instante.astimezone(FUSO).date()


@bp.get("")
def lista() -> str:
    contexto = contexto_atual()
    disponiveis = _servicos().relatorios.disponiveis(contexto)
    if not disponiveis:
        raise AcessoNegado()
    return render_template("relatorios.html", disponiveis=disponiveis, descricoes=DESCRICOES)


@bp.get("/<codigo>")
def ver(codigo: str) -> str:
    return _tela(_relatorio(codigo), request.args)


def _tela(relatorio: Relatorio, argumentos: MultiDict[str, str], erro: str | None = None) -> str:
    contexto = contexto_atual()
    hoje = _hoje()
    mes_anterior = (hoje.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    dados: dict[str, Any] = {
        "relatorio": relatorio, "descricao": DESCRICOES[relatorio], "eventos": EVENTOS, "a": argumentos,
        "hoje": hoje.isoformat(), "mes_anterior": mes_anterior,
        "pode_exportar": GUARDA.pode(contexto, "relatorio.exportar"),
    }  # fmt: skip
    if erro is not None or argumentos.get("gerar") != "1":
        return render_template("relatorio.html", tabela=None, erro=erro, **dados)
    try:
        tabela = _servicos().relatorios.gerar(contexto, relatorio, _filtros(argumentos))
    except RegraViolada as violada:
        if violada.codigo == "relatorio.mes_incompleto":
            pendentes = violada.detalhe.get("pendentes", [])
            return render_template("relatorio.html", tabela=None, pendentes=pendentes, **dados)
        mensagem = ERROS.get(violada.codigo, "Confira os filtros.")
        return render_template("relatorio.html", tabela=None, erro=mensagem, **dados)
    return render_template("relatorio.html", tabela=tabela, **dados)


@bp.post("/<codigo>/exportar")
def exportar(codigo: str) -> Response:
    relatorio = _relatorio(codigo)
    formato = request.form.get("formato", "")
    if formato not in FormatoExportacao:
        raise NaoEncontrado()
    try:
        arquivo = _servicos().relatorios.exportar(contexto_atual(), relatorio, _filtros(request.form),
                                                  FormatoExportacao(formato))  # fmt: skip
    except RegraViolada as erro:
        mensagem = ERROS.get(erro.codigo, "O relatório não pode ser exportado com esses filtros.")
        return Response(_tela(relatorio, request.form, mensagem), status=422)
    return anexo(arquivo.conteudo, arquivo.nome_arquivo, arquivo.tipo_mime)
