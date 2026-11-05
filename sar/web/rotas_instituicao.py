"""Dados da clínica (RF-1201, RF-1202): o cabeçalho de todos os documentos e o logotipo, só pela administração."""

from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, abort, current_app, redirect, render_template, request, url_for
from werkzeug.wrappers import Response as RespostaWerkzeug

from sar.modulo_01_acesso.contrato import PermissionGuard
from sar.modulo_06_configuracao.contrato import DadosInstitucionais
from sar.modulo_06_configuracao.regras import UFS
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import RegraViolada
from sar.web import contexto_atual
from sar.web.configuracao import ServicosWeb

bp = Blueprint("instituicao", __name__, url_prefix="/clinica")
GUARDA = PermissionGuard()
TAMANHO_MAXIMO_LOGOTIPO = 2 * 1024 * 1024
UF_PADRAO = "GO"

ERROS = {
    "instituicao.nome": "Informe o nome da clínica, de 2 a 150 caracteres.",
    "instituicao.endereco": "Informe o endereço, de 5 a 200 caracteres.",
    "instituicao.cep": "Informe o CEP com 8 dígitos.",
    "instituicao.municipio": "Escolha o município.",
    "instituicao.telefone": "Informe o telefone com DDD: 10 ou 11 dígitos.",
    "instituicao.cnpj": "O CNPJ não confere: verifique os dígitos.",
    "instituicao.ausente": "Salve os dados da clínica antes de enviar o logotipo.",
    "logotipo.vazio": "Escolha o arquivo do logotipo.",
    "logotipo.tipo": "O logotipo precisa ser uma imagem PNG ou JPEG.",
    "logotipo.tamanho": "O logotipo passa de 2 MB.",
    "logotipo.invalido": "Não foi possível ler a imagem, ou ela é grande demais (até 4 milhões de pixels).",
    "logotipo.tempo": "A imagem demorou demais para ser processada. Tente uma imagem menor.",
}
RESULTADOS = {"salvo": "Dados da clínica salvos.", "logotipo": "Logotipo atualizado."}


def _servicos() -> ServicosWeb:
    servicos: ServicosWeb = current_app.config["SAR_SERVICOS"]
    return servicos


def _contexto() -> Contexto:
    contexto = contexto_atual()
    GUARDA.exigir(contexto, "config.institucional.alterar")
    return contexto


def _pagina(contexto: Contexto, valores: dict[str, str] | None = None, **dados: Any) -> str:
    atual = _servicos().configuracao.ver_institucional(contexto)
    if valores is None:
        valores = {
            "nome": atual.nome, "endereco": atual.endereco, "cep": atual.cep, "uf": atual.municipio.uf,
            "municipio": atual.municipio.codigo, "telefone": atual.telefone or "", "cnpj": atual.cnpj or "",
        } if atual else {"uf": UF_PADRAO}  # fmt: skip
    uf = request.args.get("uf") or valores.get("uf") or UF_PADRAO
    uf = uf if uf in UFS else UF_PADRAO
    municipios = _servicos().configuracao.listar_municipios(contexto, uf)
    return render_template("instituicao.html", v=valores, uf=uf, ufs=sorted(UFS), municipios=municipios,
                           tem_logotipo=bool(atual and atual.tem_logotipo), cadastrada=atual is not None,
                           **dados)  # fmt: skip


@bp.get("")
def ver() -> str:
    return _pagina(_contexto(), resultado=RESULTADOS.get(request.args.get("resultado", "")))


@bp.post("")
def salvar() -> RespostaWerkzeug | str:
    contexto = _contexto()
    valores = {campo: request.form.get(campo, "") for campo in ("nome", "endereco", "cep", "uf", "municipio",
                                                                 "telefone", "cnpj")}  # fmt: skip
    dados = DadosInstitucionais(valores["nome"], valores["endereco"], valores["cep"], valores["municipio"],
                                valores["telefone"] or None, valores["cnpj"] or None)  # fmt: skip
    try:
        _servicos().configuracao.alterar_institucional(contexto, dados)
    except RegraViolada as erro:
        return _pagina(contexto, valores, erro=ERROS.get(erro.codigo, "Confira os dados."))
    return redirect(url_for("instituicao.ver", resultado="salvo"))


@bp.post("/logotipo")
def enviar_logotipo() -> RespostaWerkzeug | str:
    contexto = _contexto()
    arquivo = request.files.get("logotipo")
    conteudo = arquivo.stream.read(TAMANHO_MAXIMO_LOGOTIPO + 1) if arquivo else b""
    try:
        _servicos().configuracao.enviar_logotipo(contexto, conteudo)
    except RegraViolada as erro:
        return _pagina(contexto, erro=ERROS.get(erro.codigo, "Não foi possível usar a imagem."))
    return redirect(url_for("instituicao.ver", resultado="logotipo"))


@bp.get("/logotipo.png")
def logotipo() -> Response:
    conteudo = _servicos().configuracao.logotipo(_contexto())
    if conteudo is None:
        abort(404)
    return Response(conteudo, mimetype="image/png")
