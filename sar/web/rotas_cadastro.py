"""Tela de novo cadastro (DDS §6.6, RF-101, RF-102, RF-919, AD-04). Funciona sem JavaScript (o formulário
envia para o servidor, que decide); com ele, o htmx salva o rascunho a cada alteração, preenche o endereço pelo
CEP e confere CPF e CNS na hora, e o script local acrescenta linhas de telefone e de contato."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, redirect, render_template, request, url_for
from werkzeug.wrappers import Response

from sar.modulo_01_acesso.contrato import PermissionGuard
from sar.modulo_02_cadastro.contrato import Identificacao
from sar.modulo_06_configuracao.contrato import Municipio
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import ConfirmacaoNecessaria, IndisponivelExterno, NaoEncontrado, RegraViolada
from sar.web import contexto_atual
from sar.web.configuracao import ServicosWeb
from sar.web.formulario_cadastro import (
    PARENTESCOS,
    TIPOS_TELEFONE,
    Cadastro,
    contatos,
    ler,
    telefones_do_paciente,
    valores,
)

bp = Blueprint("cadastro", __name__, url_prefix="/cadastro")
GUARDA = PermissionGuard()
FUSO = ZoneInfo("America/Sao_Paulo")
UF_RESIDENCIA = "GO"
UFS = ("AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR",
       "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO")  # fmt: skip

# Código do MOD-02 → (campo do formulário, mensagem). O campo None vai para o aviso geral.
ERROS: dict[str, tuple[str | None, str]] = {
    "cpf.invalido": ("cpf", "CPF inválido: confira os dígitos. Deixe em branco se o paciente não trouxe o documento."),
    "cns.invalido": ("cns", "CNS inválido: confira os 15 dígitos do cartão. Deixe em branco se não houver."),
    "cep.invalido": ("cep", "O CEP tem 8 dígitos."),
    "data_nascimento.invalida": ("nascimento", "Data de nascimento fora do possível."),
    "data_nascimento.formato": ("nascimento", "Informe uma data válida."),
    "inicio.formato": ("inicio", "Informe uma data válida."),
    "inicio.antes_do_nascimento": ("inicio", "O início do tratamento é anterior ao nascimento."),
    "municipio.fora_de_goias": ("municipio", "A residência precisa ser em município de Goiás."),
    "municipio.inexistente": ("municipio", "Escolha o município na lista."),
    "naturalidade_municipio.inexistente": ("naturalidade", "Escolha o município na lista."),
    "cobertura.convenio": ("convenio", "Escolha o convênio."),
    "cobertura.convenio_inativo": ("convenio", "Este convênio foi inativado. Escolha outro."),
    "cobertura.sus_sem_convenio": ("carteirinha", "Carteirinha só para convênio."),
    "convenio.formato": ("convenio", "Escolha o convênio na lista."),
    "telefone.ddd": (None, "DDD inválido."),
    "telefone.numero": (None, "Celular tem 9 dígitos começando por 9; fixo tem 8, começando de 2 a 5."),
    "telefone.repetido": (None, "Este número já está na lista do mesmo dono."),
    "contato.nome": (None, "Informe o nome do contato, ou remova o contato."),
}
REPETIDOS = {"prontuario.repetido": "prontuario", "cpf.repetido": "cpf", "cns.repetido": "cns"}
NOMES_REPETIDOS = {"prontuario": "Este prontuário", "cpf": "Este CPF", "cns": "Este CNS"}
CAMPO_DO_FORMULARIO = {"nome_mae": "mae", "data_nascimento": "nascimento", "naturalidade_municipio": "naturalidade"}
FALTAM = {"nome": "nome", "prontuario": "prontuário", "inicio": "início do tratamento"}


def _servicos() -> ServicosWeb:
    servicos: ServicosWeb = current_app.config["SAR_SERVICOS"]
    return servicos


def _contexto() -> Contexto:
    contexto = contexto_atual()
    GUARDA.exigir(contexto, "cadastro.paciente.criar")
    return contexto


def _hora(instante: datetime) -> str:
    return instante.astimezone(FUSO).strftime("%H:%M")


def _municipios(contexto: Contexto, uf: str) -> list[Municipio]:
    return _servicos().configuracao.listar_municipios(contexto, uf)


def _pagina(contexto: Contexto, v: dict[str, str], **dados: Any) -> str:
    uf_naturalidade = v.get("naturalidade_uf") or UF_RESIDENCIA
    configuracao = _servicos().configuracao
    return render_template(
        "cadastro_novo.html",
        v=v,
        telefones=telefones_do_paciente(v),
        contatos=contatos(v),
        municipios_go=_municipios(contexto, UF_RESIDENCIA),
        ufs=UFS,
        uf_naturalidade=uf_naturalidade if uf_naturalidade in UFS else UF_RESIDENCIA,
        municipios_naturalidade=_municipios(contexto, uf_naturalidade if uf_naturalidade in UFS else UF_RESIDENCIA),
        convenios=[c for c in configuracao.listar_convenios(contexto) if c.ativo],
        parentescos=PARENTESCOS,
        tipos_telefone=TIPOS_TELEFONE,
        erros=dados.pop("erros", {}),
        **dados,
    )


def _identificacao(contexto: Contexto, paciente_id: int) -> Identificacao | None:
    try:
        ficha = _servicos().pacientes.ver_ficha(contexto, paciente_id)
    except NaoEncontrado:
        return None  # anulado: o número ficou com o cadastro anulado até a migração 0005
    d = ficha.dados
    return Identificacao(ficha.paciente_id, d.nome or "", d.prontuario or "", d.data_nascimento, d.nome_mae)


def _erro(contexto: Contexto, erro: RegraViolada, cadastro: Cadastro | None) -> tuple[dict[str, str], str | None]:
    """Os erros por campo e o aviso geral, para a pessoa saber o que corrigir e onde."""
    if erro.codigo == "P-03.minimo":
        faltam = [FALTAM[c] for c in erro.detalhe.get("faltam", []) if c in FALTAM]
        campos = {c: "Obrigatório para salvar o paciente." for c in erro.detalhe.get("faltam", [])}
        return campos, f"Para salvar o paciente falta: {', '.join(faltam)}. Sem isso, salve como rascunho."
    if erro.codigo in REPETIDOS:
        campo = REPETIDOS[erro.codigo]
        dono = _identificacao(contexto, erro.detalhe["paciente_id"]) if "paciente_id" in erro.detalhe else None
        quem = f" por {dono.nome}, prontuário {dono.prontuario}" if dono else ""
        return {campo: f"{NOMES_REPETIDOS[campo]} já está em uso{quem}."}, None
    if erro.codigo.endswith(".tamanho"):
        tamanho = erro.codigo.removesuffix(".tamanho")
        return {CAMPO_DO_FORMULARIO.get(tamanho, tamanho): f"No máximo {erro.detalhe.get('maximo')} caracteres."}, None
    alvo, mensagem = ERROS.get(erro.codigo, (None, "Não foi possível salvar. Confira os dados."))
    if alvo is None and cadastro is not None:
        alvo = cadastro.campo_do_erro(erro.detalhe)
    return ({alvo: mensagem}, None) if alvo else ({}, mensagem)


# ------------------------------------------------------------------ tela
@bp.get("/novo")
def novo() -> str:
    contexto = _contexto()
    criado = request.args.get("criado", "")
    resultado = f"Paciente cadastrado: prontuário {criado}." if criado else None
    retomado = _servicos().rascunhos.retomar(contexto) if not criado else None
    if retomado is None:
        return _pagina(contexto, {}, resultado=resultado)
    aviso = (
        f"Rascunho retomado, salvo às {_hora(retomado.atualizado_em)}"
        f" de {retomado.atualizado_em.astimezone(FUSO):%d/%m}."
        f" Ele é descartado em {retomado.descarte_em:%d/%m/%Y} se não for salvo."
    )
    return _pagina(contexto, retomado.conteudo, aviso=aviso, tem_rascunho=True)


@bp.post("/novo")
def salvar() -> Response | str:
    contexto = _contexto()
    v = valores(request.form)
    acao = request.form.get("acao", "paciente")
    if acao == "descartar":
        _servicos().rascunhos.descartar(contexto)
        return redirect(url_for("cadastro.novo"))
    if acao == "rascunho":
        try:
            salvo = _servicos().rascunhos.salvar(contexto, v)
        except RegraViolada:
            return _pagina(contexto, v, erro="O rascunho passou do tamanho permitido.")
        return _pagina(contexto, v, resultado=f"Rascunho salvo às {_hora(salvo.atualizado_em)}.", tem_rascunho=True)
    cadastro: Cadastro | None = None
    try:
        cadastro = ler(v)
        _servicos().pacientes.criar(
            contexto, cadastro.dados, cadastro.inicio, confirmar_duplicidade=acao == "confirmar",
            cobertura=cadastro.cobertura, telefones=cadastro.telefones, contatos=cadastro.contatos,
        )  # fmt: skip
    except ConfirmacaoNecessaria as alerta:
        candidatos = [i for pid in alerta.dados.get("candidatos", []) if (i := _identificacao(contexto, pid))]
        return _pagina(contexto, v, candidatos=candidatos)
    except RegraViolada as erro:
        campos, geral = _erro(contexto, erro, cadastro)
        return _pagina(contexto, v, erros=campos, erro=geral or "Confira os campos marcados.")
    return redirect(url_for("cadastro.novo", criado=(cadastro.dados.prontuario or "").strip()))


# ------------------------------------------------------------------ fragmentos do htmx
@bp.post("/rascunho")
def rascunho() -> str:
    """Salvamento automático (RF-919): só o texto do estado volta para a tela."""
    contexto = _contexto()
    try:
        salvo = _servicos().rascunhos.salvar(contexto, valores(request.form))
    except RegraViolada:
        return render_template("_rascunho_estado.html", mensagem="Rascunho não salvo: passou do tamanho permitido.")
    return render_template(
        "_rascunho_estado.html", mensagem=f"Rascunho salvo automaticamente às {_hora(salvo.atualizado_em)}."
    )


@bp.post("/cep")
def cep() -> str:
    """Preenche logradouro, bairro e município pelo CEP (AD-23); o número e o complemento ficam como estão."""
    contexto = _contexto()
    v = valores(request.form)
    try:
        sugerido = _servicos().cep.consultar(contexto, v.get("cep", ""))
    except RegraViolada:
        mensagem = "O CEP tem 8 dígitos."
    except IndisponivelExterno:
        mensagem = "Consulta de CEP fora do ar: preencha o endereço. O CEP fica para verificar depois."
    else:
        if sugerido is None:
            mensagem = "CEP não encontrado na base. Confira o número ou preencha o endereço."
        else:
            v.update(cep=sugerido.cep, logradouro=sugerido.logradouro or v.get("logradouro", ""),
                     bairro=sugerido.bairro or v.get("bairro", ""))  # fmt: skip
            if sugerido.municipio is not None and sugerido.municipio.uf == UF_RESIDENCIA:
                v["municipio"] = sugerido.municipio.codigo
                mensagem = "Endereço preenchido pelo CEP. Confira e complete o número."
            else:
                mensagem = "Este CEP não é de Goiás: a residência precisa ser em município de Goiás."
    return render_template(
        "_endereco_campos.html",
        v=v,
        municipios_go=_municipios(contexto, UF_RESIDENCIA),
        erros={},
        cep_mensagem=mensagem,
    )


@bp.post("/conferir/<campo>")
def conferir(campo: str) -> str:
    """Conferência imediata do CPF ou do CNS (DD-22). Quem decide de novo é o serviço, ao salvar."""
    contexto = _contexto()
    if campo not in ("cpf", "cns"):
        raise NaoEncontrado()
    documento: Literal["cpf", "cns"] = "cpf" if campo == "cpf" else "cns"
    try:
        dono = _servicos().pacientes.conferir_documento(contexto, documento, request.form.get(campo, ""))
    except RegraViolada as erro:
        return ERROS.get(erro.codigo, (None, ""))[1]
    if dono is None:
        return ""
    quem = _identificacao(contexto, dono)
    complemento = f" por {quem.nome}, prontuário {quem.prontuario}" if quem else ""
    return f"{NOMES_REPETIDOS[campo]} já está em uso{complemento}."


@bp.get("/municipios")
def municipios() -> str:
    contexto = _contexto()
    uf = request.args.get("naturalidade_uf", UF_RESIDENCIA)
    if uf not in UFS:
        raise NaoEncontrado()
    return render_template("_opcoes_municipios.html", municipios=_municipios(contexto, uf), selecionado="")
