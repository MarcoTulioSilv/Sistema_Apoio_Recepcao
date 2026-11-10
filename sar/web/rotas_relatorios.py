"""Relatórios (DDS §9.3): a lista do que o perfil vê, a tela de cada relatório com os filtros e a tabela, e a
exportação em PDF ou XLSX pela administração (RF-912, RNF-607). A tela é a terceira saída do mesmo modelo tabular
(DD-44): as mesmas colunas, filtros e marcas do arquivo. Os filtros vão na URL; nenhum é dado de paciente."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

from flask import Blueprint, Response, current_app, render_template, request, url_for
from werkzeug.datastructures import MultiDict

from sar.modulo_01_acesso.contrato import PermissionGuard
from sar.modulo_02_cadastro.contrato import TipoEvento
from sar.modulo_05_emissao.contrato import CADASTRAIS, Filtros, FormatoExportacao, ModoConvenio, Relatorio
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
    Relatorio.EVENTOS: "Altas, óbitos, transferências, transplantes e desistências no período.",
    Relatorio.FREQUENCIA_MENSAL: "Previstas, realizadas, ausências, reposições e extras de cada paciente no mês.",
    Relatorio.PREVIA: "A frequência mensal do mês em andamento, que ainda muda até o fechamento.",
    Relatorio.OCUPACAO: "Os pacientes de cada escala numa data, turno a turno.",
    Relatorio.RECORTE_LIVRE: "Sessões realizadas por paciente num intervalo qualquer.",
}
ERROS = {
    "relatorio.filtro.periodo": "Informe o período: a data inicial não pode ser depois da final.",
    "relatorio.filtro.data_referencia": "Informe a data de referência.",
    "relatorio.filtro.competencia": "Escolha o mês.",
    "relatorio.filtro.tipo_evento": "Escolha um tipo de evento da lista.",
    "relatorio.selecao.vazia": "Marque pelo menos um dado para incluir no relatório.",
    "relatorio.selecao.invalida": "Escolha os dados pela lista.",
}
# Os dados de cadastro escolhidos na caixa de seleção (DD-109): o que cada um traz, para a lista.
EXPLICACOES = {Relatorio.CIDADE: "Município de residência", Relatorio.CONVENIO: "Convênio ou SUS",
               Relatorio.FAIXA_ETARIA: "Idade na data de referência",
               Relatorio.SEXO: "Feminino, masculino e não informado"}  # fmt: skip


def _servicos() -> ServicosWeb:
    servicos: ServicosWeb = current_app.config["SAR_SERVICOS"]
    return servicos


def _relatorio(codigo: str) -> Relatorio:
    """Os de cadastro não têm tela própria: só saem juntos, em /relatorios/cadastro (DD-109)."""
    try:
        relatorio = Relatorio(codigo)
    except ValueError:
        raise NaoEncontrado() from None
    if relatorio in CADASTRAIS:
        raise NaoEncontrado()
    return relatorio


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


def _padroes() -> dict[str, str]:
    """Os filtros já preenchidos: o mês corrente até hoje no período, a data de hoje e o mês anterior na competência."""
    hoje = _hoje()
    return {"inicio": hoje.replace(day=1).isoformat(), "fim": hoje.isoformat(), "data": hoje.isoformat(),
            "competencia": (hoje.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")}  # fmt: skip


@bp.get("")
def lista() -> str:
    return _lista(request.args)


def _lista(argumentos: MultiDict[str, str], erro: str | None = None) -> str:
    """Em cima, os relatórios de frequência e escalas, com as entradas e os eventos; embaixo, o formulário dos dados
    de cadastro, com a caixa de seleção (DD-109). Cada perfil vê só o que pode (§4.5)."""
    contexto = contexto_atual()
    disponiveis = _servicos().relatorios.disponiveis(contexto)
    if not disponiveis:
        raise AcessoNegado()
    cadastrais = [r for r in CADASTRAIS if r in disponiveis]
    cima = [r for r in disponiveis if r not in CADASTRAIS]  # os de frequência primeiro; entradas e eventos depois
    # Formulário já enviado (o campo "escolha" vai junto): as caixas como estavam, inclusive todas desmarcadas.
    enviado = "escolha" in argumentos
    marcados = set(argumentos.getlist("incluir")) if enviado else {r.value for r in cadastrais}
    return render_template(
        "relatorios.html", relatorios=sorted(cima, key=lambda r: not r.operacional), cadastrais=cadastrais,
        descricoes=DESCRICOES, explicacoes=EXPLICACOES, marcados=marcados, a=argumentos, hoje=_hoje().isoformat(),
        erro=erro, padrao=_padroes(), eventos=EVENTOS,
    )  # fmt: skip


def _escolhidos(dados: MultiDict[str, str]) -> list[Relatorio]:
    escolhidos = []
    for codigo in dados.getlist("incluir"):
        try:
            escolhidos.append(Relatorio(codigo))
        except ValueError:
            raise RegraViolada("relatorio.selecao.invalida") from None
    return escolhidos


@bp.get("/cadastro")
def cadastro() -> str:
    """Os dados de cadastro escolhidos, num relatório só: as tabelas de sempre, em sequência (DD-109)."""
    contexto = contexto_atual()
    try:
        composto = _servicos().relatorios.gerar_cadastrais(contexto, _escolhidos(request.args), _filtros(request.args))
    except RegraViolada as violada:
        return _lista(request.args, ERROS.get(violada.codigo, "Confira os filtros."))
    voltar = f"{url_for('relatorios.lista')}?{urlencode(list(request.args.items(multi=True)))}"
    return render_template("relatorio_cadastro.html", composto=composto, a=request.args, voltar=voltar,
                           pode_exportar=GUARDA.pode(contexto, "relatorio.exportar"))  # fmt: skip


@bp.post("/cadastro/exportar")
def exportar_cadastro() -> Response:
    formato = request.form.get("formato", "")
    if formato not in FormatoExportacao:
        raise NaoEncontrado()
    try:
        arquivo = _servicos().relatorios.exportar_cadastrais(
            contexto_atual(), _escolhidos(request.form), _filtros(request.form), FormatoExportacao(formato)
        )
    except RegraViolada as erro:
        mensagem = ERROS.get(erro.codigo, "O relatório não pode ser exportado com esses filtros.")
        return Response(_lista(request.form, mensagem), status=422)
    return anexo(arquivo.conteudo, arquivo.nome_arquivo, arquivo.tipo_mime)


@bp.get("/<codigo>")
def ver(codigo: str) -> str:
    return _tela(_relatorio(codigo), request.args)


def _tela(relatorio: Relatorio, argumentos: MultiDict[str, str], erro: str | None = None) -> str:
    contexto = contexto_atual()
    padrao = _padroes()
    dados: dict[str, Any] = {
        "relatorio": relatorio, "descricao": DESCRICOES[relatorio], "eventos": EVENTOS, "a": argumentos,
        "padrao": padrao, "pode_exportar": GUARDA.pode(contexto, "relatorio.exportar"),
    }  # fmt: skip
    if erro is not None:
        return render_template("relatorio.html", tabela=None, erro=erro, **dados)
    if argumentos.get("gerar") != "1":
        # Aberto sem filtros (a prévia, pelo card, ou um endereço direto): gerado com os filtros padrão, que ficam
        # na tela para mudar.
        argumentos = MultiDict({**padrao, **argumentos.to_dict()})
        dados["a"] = argumentos
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
