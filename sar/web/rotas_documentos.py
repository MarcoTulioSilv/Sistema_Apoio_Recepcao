"""Telas de documentos (DDS §8.3 a §8.6): digitalizar pelo agente e fotografar pela câmera, acompanhar a ingestão, a
fila e a tela de conferência, os documentos do paciente, as páginas como imagem, o download da administração, a
revinculação e os pedidos de descarte e de desbloqueio.

A página do documento é sempre imagem JPEG, com `no-store` e `nosniff` (SEG-19), que o `after_request` da aplicação
põe em toda resposta. Os campos lidos que a recepcionista confirma vão ao cadastro pelo contrato de atualização do
MOD-02, com a mesma validação da digitação (DD-40): o documento fica guardado mesmo que o campo seja recusado.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import replace
from datetime import date
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, redirect, render_template, request, url_for
from werkzeug.wrappers import Response as RespostaWerkzeug

from sar.modulo_01_acesso.contrato import PermissionGuard
from sar.modulo_02_cadastro.contrato import DadosPaciente
from sar.modulo_04_documentos.contrato import (
    DESBLOQUEAR,
    DESCARTAR,
    FINAIS,
    MOTIVOS_REJEICAO,
    Conferencia,
    DocumentoDoTipo,
    EstadoIngestao,
    SituacaoIngestao,
    VersaoDocumento,
)
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import ConflitoDeVersao, IntegridadeViolada, NaoEncontrado, RegraViolada
from sar.web import contexto_atual
from sar.web.configuracao import ConfigWeb, ServicosWeb
from sar.web.mensagens_cadastro import ERROS_FICHA

bp = Blueprint("documentos", __name__, url_prefix="/documentos")
GUARDA = PermissionGuard()
FOTO = "foto_paciente"

# Motivo gravado na ingestão (SEG-12) → o que a recepcionista lê.
MOTIVOS = {
    "arquivo.vazio": "O arquivo chegou vazio.",
    "arquivo.tamanho": "O arquivo é grande demais.",
    "arquivo.poliglota": "O arquivo mistura formatos e não é aceito.",
    "tipo.nao_permitido": "O arquivo não é uma imagem nem um PDF.",
    "pdf.conteudo_ativo": "O PDF tem conteúdo executável e não é aceito.",
    "pdf.invalido": "O PDF está corrompido.",
    "imagem.invalida": "A imagem está corrompida.",
    "pixels.excedido": "A imagem é grande demais.",
    "paginas.excedido": "Páginas demais para um documento só.",
    "malware.detectado": "O antivírus detectou uma ameaça no arquivo.",
    "antimalware.assinaturas_vencidas": "O antivírus está desatualizado. Avise o TI.",
    "hash.divergente": "O arquivo mudou durante o processamento.",
    "processamento.tempo": "O processamento demorou demais.",
    "processamento.falhou": "Não foi possível processar o arquivo.",
    "reconstrucao.falhou": "Não foi possível preparar o documento.",
    "conferencia.ilegivel": "Rejeitado na conferência: ilegível.",
    "conferencia.paciente_errado": "Rejeitado na conferência: paciente errado.",
    "conferencia.tipo_errado": "Rejeitado na conferência: tipo errado.",
}
ESTADOS = {
    EstadoIngestao.ABERTA: "Esperando as páginas",
    EstadoIngestao.RECEBIDA: "Na fila para conferir o arquivo",
    EstadoIngestao.EM_PROCESSAMENTO: "Conferindo o arquivo",
    EstadoIngestao.AGUARDANDO_CONFERENCIA: "Pronto para conferência",
    EstadoIngestao.INCORPORADA: "Guardado",
    EstadoIngestao.REJEITADA: "Recusado",
    EstadoIngestao.EXPIRADA: "Expirado: não foi concluído a tempo",
    EstadoIngestao.CANCELADA: "Cancelado",
}
NOMES_REJEICAO = {"ilegivel": "Ilegível", "paciente_errado": "Paciente errado", "tipo_errado": "Tipo errado"}
ERROS = {
    "tipo.inexistente": "Escolha o tipo de documento.",
    "tipo.origem": "Este tipo de documento não é capturado assim.",
    "paciente.anulado": "O cadastro deste paciente foi anulado.",
    "versao.substituida": "Só a versão atual do documento pode ser substituída.",
    "versao.motivo": "Informe o motivo da nova versão.",
    "ingestao.estado": "Esta digitalização já foi concluída ou expirou.",
    "ingestao.motivo": "Escolha o motivo da rejeição.",
    "documento.repetido": "Este mesmo documento já está guardado.",
    "documento.bloqueado": "Este documento está bloqueado. A administração foi avisada.",
    "documento.descartado": "Este documento foi descartado ao fim do prazo de guarda.",
    "revinculo.motivo": "Informe o motivo da troca de paciente.",
    "revinculo.mesmo_paciente": "O documento já é deste paciente.",
    "revinculo.destino": "Não há paciente com esse prontuário.",
    "motivo.obrigatorio": "Informe o motivo.",
    "retencao.vigente": "O prazo de guarda deste documento ainda não venceu.",
    "documento.desbloqueio": "Só o bloqueio do antivírus se desfaz assim. Arquivo alterado o TI restaura do backup.",
}
# Campos lidos que vão ao cadastro pela atualização (DD-40). A carteirinha é da cobertura: só é mostrada.
ATUALIZAVEIS = ("cpf", "cns", "cep", "data_nascimento")
NOMES_CAMPOS = {"cpf": "CPF", "cns": "CNS", "cep": "CEP", "data_nascimento": "Nascimento", "carteirinha": "Carteirinha"}


def _servicos() -> ServicosWeb:
    servicos: ServicosWeb = current_app.config["SAR_SERVICOS"]
    return servicos


def _config() -> ConfigWeb:
    config: ConfigWeb = current_app.config["SAR"]
    return config


def _pode(contexto: Contexto) -> dict[str, bool]:
    return {
        "capturar": GUARDA.pode(contexto, "documento.ingestao.abrir"),
        "conferir": GUARDA.pode(contexto, "documento.ingestao.conferir"),
        "nova_versao": GUARDA.pode(contexto, "documento.nova_versao"),
        "ver": GUARDA.pode(contexto, "documento.ver"),
        "baixar": GUARDA.pode(contexto, "documento.baixar"),
        "revincular": GUARDA.pode(contexto, "documento.revincular"),
        "descartar": GUARDA.solicitavel(contexto, DESCARTAR),
        "desbloquear": GUARDA.solicitavel(contexto, DESBLOQUEAR),
    }


def _imagem(conteudo: bytes, tipo_midia: str) -> Response:
    return Response(conteudo, mimetype=tipo_midia)


# ------------------------------------------------------------------ digitalizar e fotografar (§8.3, etapas 1 e 2)
@bp.get("/digitalizar/<int:paciente_id>")
def digitalizar(paciente_id: int) -> str:
    contexto = contexto_atual()
    ficha = _servicos().pacientes.ver_ficha(contexto, paciente_id)
    tipos = [t for t in _servicos().ingestao.tipos(contexto) if t.origem == "scanner"]
    return render_template(
        "documentos_digitalizar.html", ficha=ficha, tipos=tipos, tipo=request.args.get("tipo", ""),
        vinculo=request.args.get("vinculo", ""), substitui=request.args.get("substitui", ""),
        agente=_config().endereco_agente,
    )  # fmt: skip


@bp.get("/foto/<int:paciente_id>")
def foto(paciente_id: int) -> str:
    contexto = contexto_atual()
    ficha = _servicos().pacientes.ver_ficha(contexto, paciente_id)
    _servicos().ingestao.tipos(contexto)  # confere a permissão antes de abrir a câmera
    return render_template("documentos_foto.html", ficha=ficha, substitui=request.args.get("substitui", ""),
                           abrir=request.args.get("abrir") == "1",
                           resultado="Paciente cadastrado." if request.args.get("criado") == "1" else None)  # fmt: skip


@bp.post("/ingestoes")
def abrir() -> tuple[Response, int]:
    """Chamada pelo script da tela: devolve o id e o token, que vão ao agente ou ao envio da foto (§8.5)."""
    contexto = contexto_atual()
    f = request.form
    try:
        aberta = _servicos().ingestao.abrir(
            contexto, int(f.get("paciente_id", "0") or 0), f.get("tipo", ""), f.get("origem", ""),
            vinculo=f.get("vinculo") or None, substitui_id=f.get("substitui") or None, motivo=f.get("motivo") or None,
        )  # fmt: skip
    except RegraViolada as erro:
        return jsonify({"erro": ERROS.get(erro.codigo, "Não foi possível começar a digitalização.")}), 422
    situacao = url_for("documentos.situacao", ingestao_id=aberta.id)
    return jsonify({"id": aberta.id, "token": aberta.token, "situacao": situacao}), 201


def _situacao(situacao: SituacaoIngestao) -> str:
    estado = situacao.estado
    passo = {EstadoIngestao.ABERTA: 0, EstadoIngestao.AGUARDANDO_CONFERENCIA: 2}.get(estado, 1)
    return render_template(
        "_ingestao_situacao.html", s=situacao, estados=ESTADOS, passo=passo,
        final=estado in FINAIS or estado is EstadoIngestao.AGUARDANDO_CONFERENCIA,
        motivo=MOTIVOS.get(situacao.motivo or "", "Não foi possível aproveitar o arquivo."),
        pode=_pode(contexto_atual()),
    )  # fmt: skip


@bp.get("/ingestoes/<ingestao_id>/situacao")
def situacao(ingestao_id: str) -> str:
    return _situacao(_servicos().ingestao.situacao(contexto_atual(), ingestao_id))


@bp.post("/ingestoes/<ingestao_id>/cancelar")
def cancelar(ingestao_id: str) -> str:
    contexto = contexto_atual()
    with suppress(RegraViolada):  # já saiu de "aberta": a situação atual diz o que aconteceu
        _servicos().ingestao.cancelar(contexto, ingestao_id)
    return _situacao(_servicos().ingestao.situacao(contexto, ingestao_id))


# ------------------------------------------------------------------ conferência (§8.3, etapa 7)
@bp.get("/conferencia")
def fila() -> str:
    contexto = contexto_atual()
    itens = _servicos().ingestao.a_conferir(contexto)
    pacientes = _servicos().pacientes.identificar(contexto, sorted({i.paciente_id for i in itens}))
    nomes = {t.codigo: t.nome for t in _servicos().ingestao.tipos(contexto)}
    return render_template("documentos_conferencia_fila.html", itens=itens, pacientes=pacientes, nomes=nomes)


def _linhas_campos(conferencia: Conferencia, dados: DadosPaciente) -> list[dict[str, Any]]:
    linhas = []
    for campo in conferencia.campos:
        atual = getattr(dados, campo.nome, None) if campo.nome in ATUALIZAVEIS else None
        if isinstance(atual, date):
            atual = atual.strftime("%d/%m/%Y")
        lido = campo.valor
        if campo.nome == "data_nascimento":
            ano, mes, dia = lido.split("-")
            lido = f"{dia}/{mes}/{ano}"
        linhas.append({
            "nome": campo.nome, "rotulo": NOMES_CAMPOS.get(campo.nome, campo.nome), "lido": lido,
            "atual": atual or "—", "baixa": campo.confianca != "alta", "atualizavel": campo.nome in ATUALIZAVEIS,
            "igual": atual is not None and str(atual) == lido,
        })  # fmt: skip
    return linhas


def _tela_conferencia(contexto: Contexto, ingestao_id: str, **extra: Any) -> str:
    conferencia = _servicos().ingestao.conferir(contexto, ingestao_id)
    ficha = _servicos().pacientes.ver_ficha(contexto, conferencia.situacao.paciente_id)
    nomes = {t.codigo: t.nome for t in _servicos().ingestao.tipos(contexto)}
    return render_template(
        "documento_conferencia.html", c=conferencia, s=conferencia.situacao, ficha=ficha,
        nome_tipo=nomes.get(conferencia.situacao.tipo, conferencia.situacao.tipo),
        campos=_linhas_campos(conferencia, ficha.dados), motivos=[(m, NOMES_REJEICAO[m]) for m in MOTIVOS_REJEICAO],
        **extra,
    )  # fmt: skip


def _tela_ou_fila(contexto: Contexto, ingestao_id: str, **extra: Any) -> str | RespostaWerkzeug:
    """A tela de conferência; se a ingestão já saiu dela (outra estação concluiu, ou expirou), volta à fila."""
    try:
        return _tela_conferencia(contexto, ingestao_id, **extra)
    except RegraViolada:
        return redirect(url_for("documentos.fila", resultado="encerrada"))


@bp.get("/conferencia/<ingestao_id>")
def conferencia(ingestao_id: str) -> str | RespostaWerkzeug:
    return _tela_ou_fila(contexto_atual(), ingestao_id)


@bp.get("/conferencia/<ingestao_id>/paginas/<int:numero>")
def pagina_em_conferencia(ingestao_id: str, numero: int) -> Response:
    pagina = _servicos().ingestao.pagina_em_conferencia(contexto_atual(), ingestao_id, numero)
    return _imagem(pagina.conteudo, pagina.tipo_midia)


def _aplicar_campos(contexto: Contexto, paciente_id: int, escolhidos: dict[str, str]) -> str | None:
    """Grava no cadastro os campos confirmados; devolve a mensagem de erro, se a validação recusar (DD-40)."""
    if not escolhidos:
        return None
    servico = _servicos().pacientes
    ficha = servico.ver_ficha(contexto, paciente_id)
    valores: dict[str, Any] = dict(escolhidos)
    if "data_nascimento" in valores:
        valores["data_nascimento"] = date.fromisoformat(valores["data_nascimento"])
    try:
        servico.atualizar(contexto, paciente_id, ficha.versao, replace(ficha.dados, **valores))
    except RegraViolada as erro:
        return ERROS_FICHA.get(erro.codigo, "O dado lido não passou na conferência do cadastro.")
    except ConflitoDeVersao:
        return "Outra estação alterou o cadastro ao mesmo tempo. Confira os dados na ficha."
    return None


@bp.post("/conferencia/<ingestao_id>/incorporar")
def incorporar(ingestao_id: str) -> str | RespostaWerkzeug:
    contexto = contexto_atual()
    try:
        conferencia_atual = _servicos().ingestao.conferir(contexto, ingestao_id)  # os candidatos somem ao incorporar
    except RegraViolada:
        return redirect(url_for("documentos.fila", resultado="encerrada"))
    marcados = set(request.form.getlist("usar"))
    escolhidos = {c.nome: c.valor for c in conferencia_atual.campos if c.nome in marcados and c.nome in ATUALIZAVEIS}
    paciente_id = conferencia_atual.situacao.paciente_id
    try:
        _servicos().ingestao.incorporar(contexto, ingestao_id)
    except RegraViolada as erro:
        return _tela_ou_fila(contexto, ingestao_id, erro=ERROS.get(erro.codigo, "Não foi possível guardar."))
    except IntegridadeViolada:
        return _tela_ou_fila(contexto, ingestao_id, erro="O arquivo preparado não confere. Digitalize de novo.")
    recusa = _aplicar_campos(contexto, paciente_id, escolhidos)
    resultado = "documento" if recusa is None else "documento_campo_recusado"
    return redirect(url_for("pacientes.ficha", paciente_id=paciente_id, resultado=resultado, _anchor="documentos"))


@bp.post("/conferencia/<ingestao_id>/rejeitar")
def rejeitar(ingestao_id: str) -> str | RespostaWerkzeug:
    contexto = contexto_atual()
    try:
        _servicos().ingestao.rejeitar(contexto, ingestao_id, request.form.get("motivo", ""))
    except RegraViolada as erro:
        if erro.codigo == "ingestao.motivo":
            return _tela_ou_fila(contexto, ingestao_id, erro=ERROS["ingestao.motivo"])
        return redirect(url_for("documentos.fila", resultado="encerrada"))
    return redirect(url_for("documentos.fila", resultado="rejeitado"))


# ------------------------------------------------------------------ documentos do paciente (§8.6)
def _achar(lista: list[DocumentoDoTipo], documento_id: str) -> tuple[DocumentoDoTipo, VersaoDocumento]:
    for item in lista:
        for versao in (item.vigente, *item.anteriores):
            if versao.id == documento_id:
                return item, versao
    raise NaoEncontrado()


def _tela_documento(contexto: Contexto, paciente_id: int, documento_id: str, **extra: Any) -> str:
    ficha = _servicos().pacientes.ver_ficha(contexto, paciente_id)
    item, versao = _achar(_servicos().documentos.listar(contexto, paciente_id), documento_id)
    return render_template(
        "documento_ver.html", ficha=ficha, item=item, versao=versao, vigente=versao.id == item.vigente.id,
        pode=_pode(contexto), foto=item.tipo == FOTO, resultado=extra.pop("resultado", None), **extra,
    )  # fmt: skip


@bp.get("/paciente/<int:paciente_id>/<documento_id>")
def ver(paciente_id: int, documento_id: str) -> str:
    resultado = {"pedido": "Pedido enviado à administração. Ele aparece em Autorizações até a decisão.",
                 "executado": "Feito. Como o pedido foi da administração, ele foi aprovado na hora."}  # fmt: skip
    return _tela_documento(contexto_atual(), paciente_id, documento_id,
                           resultado=resultado.get(request.args.get("resultado", "")))  # fmt: skip


@bp.get("/<documento_id>/paginas/<int:numero>")
def pagina(documento_id: str, numero: int) -> Response:
    conteudo = _servicos().documentos.pagina(contexto_atual(), documento_id, numero)
    return _imagem(conteudo.conteudo, conteudo.tipo_midia)


@bp.get("/<documento_id>/baixar")
def baixar(documento_id: str) -> Response:
    conteudo, midia = _servicos().documentos.baixar(contexto_atual(), documento_id)
    extensao = "jpg" if midia == "image/jpeg" else "pdf"
    resposta = Response(conteudo, mimetype=midia)
    resposta.headers["Content-Disposition"] = f'attachment; filename="documento-{documento_id[:8]}.{extensao}"'
    return resposta


@bp.post("/paciente/<int:paciente_id>/<documento_id>/revincular")
def revincular(paciente_id: int, documento_id: str) -> str | RespostaWerkzeug:
    contexto = contexto_atual()
    prontuario = request.form.get("prontuario", "").strip()
    motivo = request.form.get("motivo", "")
    destino = next((p for p in _servicos().pacientes.buscar(contexto, prontuario) if p.prontuario == prontuario), None)
    try:
        if destino is None:
            raise RegraViolada("revinculo.destino")
        _servicos().documentos.revincular(contexto, documento_id, destino.paciente_id, motivo)
    except RegraViolada as erro:
        return _tela_documento(contexto, paciente_id, documento_id, erro=ERROS.get(erro.codigo, "Não foi possível."),
                               prontuario=prontuario, motivo=motivo)  # fmt: skip
    return redirect(url_for("pacientes.ficha", paciente_id=destino.paciente_id, resultado="revinculado",
                            _anchor="documentos"))  # fmt: skip


def _pedir(paciente_id: int, documento_id: str, tipo: str) -> str | RespostaWerkzeug:
    contexto = contexto_atual()
    motivo = request.form.get("motivo", "").strip()
    if not motivo:
        return _tela_documento(contexto, paciente_id, documento_id, erro=ERROS["motivo.obrigatorio"])
    try:
        _servicos().autorizacoes.solicitar(contexto, tipo, documento_id, {"documento_id": documento_id}, motivo)
    except RegraViolada as erro:
        return _tela_documento(contexto, paciente_id, documento_id, erro=ERROS.get(erro.codigo, "Não foi possível."))
    resultado = "executado" if GUARDA.pode(contexto, "acesso.autorizacao.decidir") else "pedido"
    return redirect(url_for("documentos.ver", paciente_id=paciente_id, documento_id=documento_id, resultado=resultado))


@bp.post("/paciente/<int:paciente_id>/<documento_id>/descarte")
def pedir_descarte(paciente_id: int, documento_id: str) -> str | RespostaWerkzeug:
    return _pedir(paciente_id, documento_id, DESCARTAR)


@bp.post("/paciente/<int:paciente_id>/<documento_id>/desbloqueio")
def pedir_desbloqueio(paciente_id: int, documento_id: str) -> str | RespostaWerkzeug:
    return _pedir(paciente_id, documento_id, DESBLOQUEAR)
