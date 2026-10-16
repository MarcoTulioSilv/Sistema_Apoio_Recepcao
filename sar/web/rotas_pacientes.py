"""Busca e ficha do paciente (DDS §6.7, RF-107, RF-109): dados, pendências, períodos com cobertura e evento,
telefones e contatos, e as ações de cada perfil. Correção e remoção de evento e anulação são pedidas à
administração (DEC-42), que as aprova na tela de autorizações, onde vê o impacto (§6.9)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from flask import Blueprint, current_app, redirect, render_template, request, url_for
from werkzeug.wrappers import Response

from sar.modulo_01_acesso.contrato import PermissionGuard
from sar.modulo_02_cadastro.contrato import DadosCobertura, Ficha, TipoCobertura, TipoEvento, TipoTelefone
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import ConflitoDeVersao, IndisponivelExterno, RegraViolada
from sar.web import contexto_atual
from sar.web.configuracao import ServicosWeb
from sar.web.formulario_cadastro import ler, valores
from sar.web.mensagens_cadastro import (
    COBERTURAS,
    ERROS_FICHA,
    EVENTOS,
    EVENTOS_COM_LOCAL,
    PENDENCIAS,
    SITUACOES,
    TELEFONES,
)
from sar.web.rotas_cadastro import (
    UF_RESIDENCIA,
    UFS,
    erro_do_formulario,
    municipios_da_uf,
    municipios_para_codigos,
    municipios_para_nomes,
)

bp = Blueprint("pacientes", __name__, url_prefix="/pacientes")
TELEFONES_VALORES = {t.value for t in TipoTelefone}
GUARDA = PermissionGuard()

RESULTADOS = {
    "criado": "Paciente cadastrado.",
    "atualizado": "Dados do paciente atualizados.",
    "cep_verificado": "CEP verificado.",
    "cep_desconhecido": "O CEP não foi encontrado na base. Confira o número e corrija nos dados do paciente.",
    "duplicidade": "Registrado: não é a mesma pessoa.",
    "telefone": "Telefone incluído.",
    "telefone_removido": "Telefone removido.",
    "telefone_alterado": "Telefone alterado.",
    "contato_alterado": "Contato alterado.",
    "contato": "Contato incluído.",
    "contato_removido": "Contato removido, com os telefones dele.",
    "periodo": "Novo período de tratamento aberto.",
    "cobertura": "Cobertura registrada.",
    "evento": "Evento registrado. O período foi encerrado; o comprovante fica pendente até ser digitalizado.",
    "pedido": "Pedido enviado à administração. Ele aparece em Autorizações até a decisão.",
    "executado": "Feito. Como o pedido foi da administração, ele foi aprovado na hora.",
    "anulado": "Cadastro anulado: os dados pessoais foram apagados e os números ficaram livres.",
}


def _servicos() -> ServicosWeb:
    servicos: ServicosWeb = current_app.config["SAR_SERVICOS"]
    return servicos


def _permissoes(contexto: Contexto) -> dict[str, bool]:
    def pode(operacao: str) -> bool:
        return GUARDA.pode(contexto, operacao)

    return {
        "ficha": pode("cadastro.paciente.ver_ficha"),
        "atualizar": pode("cadastro.paciente.atualizar"),
        "duplicidade": pode("cadastro.paciente.descartar_duplicidade"),
        "contatos": pode("cadastro.contato.gerir"),
        "periodo": pode("cadastro.periodo.abrir"),
        "cobertura": pode("cadastro.cobertura.registrar"),
        "evento": pode("cadastro.evento.registrar"),
        "corrigir_evento": GUARDA.solicitavel(contexto, "cadastro.evento.corrigir"),
        "anular": GUARDA.solicitavel(contexto, "cadastro.paciente.anular"),
    }


def _data(texto: str) -> date:
    try:
        return date.fromisoformat(texto.strip())
    except ValueError:
        raise RegraViolada("data.formato") from None


def _cobertura(formulario: dict[str, str]) -> DadosCobertura | None:
    tipo = formulario.get("cobertura", "")
    if tipo not in (TipoCobertura.SUS.value, TipoCobertura.CONVENIO.value):
        return None
    convenio = formulario.get("convenio", "").strip()
    if tipo == TipoCobertura.SUS.value:
        return DadosCobertura(TipoCobertura.SUS)
    return DadosCobertura(TipoCobertura.CONVENIO, int(convenio) if convenio.isdigit() else None,
                          formulario.get("carteirinha"))  # fmt: skip


def _ficha(contexto: Contexto, paciente_id: int, **extra: Any) -> str:
    ficha = _servicos().pacientes.ver_ficha(contexto, paciente_id)
    pode = _permissoes(contexto)
    convenios = _servicos().configuracao.listar_convenios(contexto) if pode["cobertura"] or pode["periodo"] else []
    return render_template(
        "paciente_ficha.html",
        ficha=ficha,
        pode=pode,
        convenios=[c for c in convenios if c.ativo],
        situacoes=SITUACOES,
        eventos=EVENTOS,
        eventos_com_local=EVENTOS_COM_LOCAL,
        coberturas=COBERTURAS,
        telefones=TELEFONES,
        pendencias=PENDENCIAS,
        aberto=next((p for p in ficha.periodos if p.evento_tipo is None), None),
        ultimo=ficha.periodos[-1] if ficha.periodos else None,
        resultado=RESULTADOS.get(request.args.get("resultado", "")),
        **extra,
    )


def _acao(paciente_id: int, acao: Callable[[Contexto], str | None]) -> Response | str:
    """Executa a ação da ficha e volta a ela com o resultado; regra violada volta com o aviso de erro."""
    contexto = contexto_atual()
    try:
        resultado = acao(contexto)
    except RegraViolada as erro:
        impedimentos = erro.detalhe.get("impedimentos", []) if erro.codigo == "evento.impedimentos" else []
        mensagem = ERROS_FICHA.get(erro.codigo, "Não foi possível concluir. Confira os dados.")
        return _ficha(contexto, paciente_id, erro=mensagem, impedimentos=impedimentos)
    except IndisponivelExterno:
        return _ficha(contexto, paciente_id, erro="Consulta de CEP fora do ar. Tente de novo mais tarde.")
    return redirect(url_for("pacientes.ficha", paciente_id=paciente_id, resultado=resultado))


def _pedido(contexto: Contexto) -> str:
    return "executado" if GUARDA.pode(contexto, "acesso.autorizacao.decidir") else "pedido"


def _form() -> dict[str, str]:
    return {chave: str(valor) for chave, valor in request.form.items()}


# ------------------------------------------------------------------ lista e busca (RF-107)
PAGINA = 30


MINIMO_FILTRO = 3  # DD-90: com 1 ou 2 caracteres, a filtragem enquanto se digita não roda


def _lista(contexto: Contexto, termo: str, deslocamento: int, registrar: bool) -> dict[str, Any]:
    pagina = _servicos().pacientes.listar(contexto, termo, deslocamento, PAGINA, registrar_na_trilha=registrar)
    return {
        "termo": termo, "pacientes": pagina.itens, "tem_mais": pagina.tem_mais,
        "proximo": deslocamento + len(pagina.itens), "pode": _permissoes(contexto),
    }  # fmt: skip


@bp.get("")
def busca() -> str:
    """A lista de todos, em ordem de nome, página a página; o filtro anda enquanto a pessoa digita."""
    contexto = contexto_atual()
    resultado = RESULTADOS["anulado"] if request.args.get("anulado") else None
    return render_template("pacientes_busca.html", resultado=resultado, **_lista(contexto, "", 0, registrar=True))


@bp.post("/buscar")
def buscar() -> str:
    """Sem JavaScript: o formulário envia o termo e a tela volta com a primeira página filtrada. Por POST, o termo
    (nome ou CPF) não vai para a URL nem para o log de acesso (DD-81)."""
    contexto = contexto_atual()
    termo = request.form.get("termo", "")
    return render_template("pacientes_busca.html", **_lista(contexto, termo, 0, registrar=True))  # busca confirmada


@bp.post("/lista")
def lista() -> Response | str:
    """Fragmento do htmx: as linhas de uma página, com a linha que pede a próxima quando aparece na rolagem. Não
    entra na trilha: filtragem enquanto se digita e página da rolagem não são ações da pessoa (DD-90)."""
    contexto = contexto_atual()
    termo = request.form.get("termo", "")
    if 0 < len(termo.strip()) < MINIMO_FILTRO:
        return Response(status=204)  # o htmx não troca nada com 204: a lista fica como está
    deslocamento = request.args.get("deslocamento", "0")
    inicio = int(deslocamento) if deslocamento.isdigit() else 0
    return render_template("_linhas_pacientes.html", **_lista(contexto, termo, inicio, registrar=False))


# ------------------------------------------------------------------ ficha
@bp.get("/<int:paciente_id>")
def ficha(paciente_id: int) -> str:
    return _ficha(contexto_atual(), paciente_id)


def _valores_da_ficha(f: Ficha) -> dict[str, str]:
    d = f.dados
    pares = {
        "prontuario": d.prontuario, "nome": d.nome,
        "nascimento": d.data_nascimento.isoformat() if d.data_nascimento else "",
        "sexo": d.sexo.value if d.sexo else "", "mae": d.nome_mae, "cpf": d.cpf, "cns": d.cns, "rg": d.rg,
        "rg_orgao": d.rg_orgao, "naturalidade_uf": f.naturalidade.uf if f.naturalidade else UF_RESIDENCIA,
        "naturalidade": d.naturalidade_municipio, "cep": d.cep, "logradouro": d.logradouro, "numero": d.numero,
        "complemento": d.complemento, "bairro": d.bairro, "municipio": d.municipio,
    }  # fmt: skip
    return {chave: valor or "" for chave, valor in pares.items()}


def _edicao(contexto: Contexto, paciente_id: int, versao: int, v: dict[str, str], **extra: Any) -> str:
    uf = v.get("naturalidade_uf") or UF_RESIDENCIA
    uf = uf if uf in UFS else UF_RESIDENCIA
    return render_template(
        "paciente_editar.html", paciente_id=paciente_id, versao=versao, v=municipios_para_nomes(contexto, v), ufs=UFS,
        uf_naturalidade=uf,
        municipios_naturalidade=municipios_da_uf(contexto, uf), municipios_go=municipios_da_uf(contexto, UF_RESIDENCIA),
        erros=extra.pop("erros", {}), **extra,
    )  # fmt: skip


@bp.get("/<int:paciente_id>/editar")
def editar(paciente_id: int) -> str:
    contexto = contexto_atual()
    GUARDA.exigir(contexto, "cadastro.paciente.atualizar")
    f = _servicos().pacientes.ver_ficha(contexto, paciente_id)
    return _edicao(contexto, paciente_id, f.versao, _valores_da_ficha(f))


@bp.post("/<int:paciente_id>/editar")
def editar_enviar(paciente_id: int) -> Response | str:
    contexto = contexto_atual()
    v = valores(request.form)
    versao = int(request.form.get("versao", "0") or 0)
    try:
        cadastro = ler(municipios_para_codigos(contexto, v))
        _servicos().pacientes.atualizar(contexto, paciente_id, versao, cadastro.dados)
    except ConflitoDeVersao:
        f = _servicos().pacientes.ver_ficha(contexto, paciente_id)
        aviso = (
            "Outra pessoa alterou este cadastro enquanto você editava. Os dados abaixo são os atuais; refaça a mudança."
        )
        return _edicao(contexto, paciente_id, f.versao, _valores_da_ficha(f), erro=aviso)
    except RegraViolada as erro:
        campos, geral = erro_do_formulario(contexto, erro, None)
        return _edicao(contexto, paciente_id, versao, v, erros=campos, erro=geral or "Confira os campos marcados.")
    return redirect(url_for("pacientes.ficha", paciente_id=paciente_id, resultado="atualizado"))


@bp.post("/<int:paciente_id>/cep")
def verificar_cep(paciente_id: int) -> Response | str:
    def acao(c: Contexto) -> str:
        return "cep_verificado" if _servicos().pacientes.verificar_cep(c, paciente_id) else "cep_desconhecido"

    return _acao(paciente_id, acao)


@bp.post("/<int:paciente_id>/duplicidade/<int:outro_id>")
def descartar_duplicidade(paciente_id: int, outro_id: int) -> Response | str:
    def acao(c: Contexto) -> str:
        _servicos().pacientes.descartar_duplicidade(c, paciente_id, outro_id)
        return "duplicidade"

    return _acao(paciente_id, acao)


# ------------------------------------------------------------------ telefones e contatos (RF-201, RF-202)
@bp.post("/<int:paciente_id>/telefones")
def incluir_telefone(paciente_id: int) -> Response | str:
    f = _form()
    contato = f.get("contato_id", "")

    def acao(c: Contexto) -> str:
        tipo = TipoTelefone(f["tipo"]) if f.get("tipo") in TELEFONES_VALORES else TipoTelefone.CELULAR
        _servicos().contatos.incluir_telefone(
            c, paciente_id, f.get("ddd", ""), f.get("numero", ""), tipo, int(contato) if contato.isdigit() else None
        )
        return "telefone"

    return _acao(paciente_id, acao)


@bp.post("/<int:paciente_id>/telefones/<int:telefone_id>/alterar")
def alterar_telefone(paciente_id: int, telefone_id: int) -> Response | str:
    """Número e tipo; o dono continua o mesmo (INV-12)."""
    f = _form()

    def acao(c: Contexto) -> str:
        tipo = TipoTelefone(f["tipo"]) if f.get("tipo") in TELEFONES_VALORES else TipoTelefone.CELULAR
        _servicos().contatos.alterar_telefone(c, telefone_id, f.get("ddd", ""), f.get("numero", ""), tipo)
        return "telefone_alterado"

    return _acao(paciente_id, acao)


@bp.post("/<int:paciente_id>/telefones/<int:telefone_id>/remover")
def remover_telefone(paciente_id: int, telefone_id: int) -> Response | str:
    def acao(c: Contexto) -> str:
        _servicos().contatos.remover_telefone(c, telefone_id)
        return "telefone_removido"

    return _acao(paciente_id, acao)


@bp.post("/<int:paciente_id>/contatos")
def incluir_contato(paciente_id: int) -> Response | str:
    f = _form()

    def acao(c: Contexto) -> str:
        _servicos().contatos.incluir_contato(c, paciente_id, f.get("nome", ""), f.get("parentesco") or None)
        return "contato"

    return _acao(paciente_id, acao)


@bp.post("/<int:paciente_id>/contatos/<int:contato_id>/alterar")
def alterar_contato(paciente_id: int, contato_id: int) -> Response | str:
    f = _form()

    def acao(c: Contexto) -> str:
        _servicos().contatos.alterar_contato(c, contato_id, f.get("nome", ""), f.get("parentesco") or None)
        return "contato_alterado"

    return _acao(paciente_id, acao)


@bp.post("/<int:paciente_id>/contatos/<int:contato_id>/remover")
def remover_contato(paciente_id: int, contato_id: int) -> Response | str:
    def acao(c: Contexto) -> str:
        _servicos().contatos.remover_contato(c, contato_id)
        return "contato_removido"

    return _acao(paciente_id, acao)


# ------------------------------------------------------------------ períodos, coberturas e evento
@bp.post("/<int:paciente_id>/periodos")
def abrir_periodo(paciente_id: int) -> Response | str:
    f = _form()

    def acao(c: Contexto) -> str:
        _servicos().pacientes.abrir_periodo(c, paciente_id, _data(f.get("inicio", "")), _cobertura(f))
        return "periodo"

    return _acao(paciente_id, acao)


@bp.post("/<int:paciente_id>/periodos/<int:periodo_id>/coberturas")
def registrar_cobertura(paciente_id: int, periodo_id: int) -> Response | str:
    f = _form()

    def acao(c: Contexto) -> str:
        cobertura = _cobertura(f)
        if cobertura is None:
            raise RegraViolada("cobertura.convenio")
        _servicos().pacientes.registrar_cobertura(c, periodo_id, cobertura, _data(f.get("inicio", "")))
        return "cobertura"

    return _acao(paciente_id, acao)


def _tipo_evento(f: dict[str, str]) -> TipoEvento:
    try:
        return TipoEvento(f.get("tipo", ""))
    except ValueError:
        raise RegraViolada("evento.tipo") from None


@bp.post("/<int:paciente_id>/evento")
def registrar_evento(paciente_id: int) -> Response | str:
    f = _form()

    def acao(c: Contexto) -> str:
        _servicos().eventos.registrar(c, paciente_id, _tipo_evento(f), _data(f.get("data", "")), f.get("local") or None)
        return "evento"

    return _acao(paciente_id, acao)


@bp.post("/<int:paciente_id>/periodos/<int:periodo_id>/evento/corrigir")
def corrigir_evento(paciente_id: int, periodo_id: int) -> Response | str:
    f = _form()

    def acao(c: Contexto) -> str:
        tipo, data = _tipo_evento(f), _data(f.get("data", ""))
        _servicos().eventos.solicitar_correcao(c, periodo_id, tipo, data, f.get("local") or None, f.get("motivo", ""))
        return _pedido(c)

    return _acao(paciente_id, acao)


@bp.post("/<int:paciente_id>/periodos/<int:periodo_id>/evento/remover")
def remover_evento(paciente_id: int, periodo_id: int) -> Response | str:
    f = _form()

    def acao(c: Contexto) -> str:
        _servicos().eventos.solicitar_remocao(c, periodo_id, f.get("motivo", ""))
        return _pedido(c)

    return _acao(paciente_id, acao)


# ------------------------------------------------------------------ anulação (RF-1008, §6.9)
@bp.get("/<int:paciente_id>/anular")
def anular(paciente_id: int) -> str:
    contexto = contexto_atual()
    ficha = _servicos().pacientes.ver_ficha(contexto, paciente_id)
    impacto = _servicos().anulacao.impacto(contexto, paciente_id)
    return render_template(
        "paciente_anular.html", ficha=ficha, impacto=impacto, decide=_pedido(contexto) == "executado"
    )


@bp.post("/<int:paciente_id>/anular")
def anular_enviar(paciente_id: int) -> Response | str:
    contexto = contexto_atual()
    motivo = request.form.get("motivo", "")
    try:
        _servicos().anulacao.solicitar(contexto, paciente_id, motivo)
    except RegraViolada as erro:
        ficha = _servicos().pacientes.ver_ficha(contexto, paciente_id)
        impacto = _servicos().anulacao.impacto(contexto, paciente_id)
        return render_template(
            "paciente_anular.html", ficha=ficha, impacto=impacto, decide=_pedido(contexto) == "executado",
            erro=ERROS_FICHA.get(erro.codigo, "Não foi possível pedir a anulação."), motivo=motivo,
        )  # fmt: skip
    if _pedido(contexto) == "executado":
        return redirect(url_for("pacientes.busca", anulado="1"))
    return redirect(url_for("pacientes.ficha", paciente_id=paciente_id, resultado="pedido"))
