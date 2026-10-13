"""Tela de parâmetros (DDS §10.1, DD-48): a administração edita os operacionais; o TI, os técnicos."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from flask import Blueprint, current_app, redirect, render_template, request, url_for
from werkzeug.wrappers import Response

from sar.modulo_01_acesso.contrato import PermissionGuard
from sar.modulo_06_configuracao.contrato import ParametroVigente, Valor
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import NaoEncontrado, RegraViolada
from sar.web import contexto_atual
from sar.web.configuracao import ServicosWeb
from sar.web.rotulos import PARAMETROS, PERFIS, UNIDADES

bp = Blueprint("parametros", __name__, url_prefix="/parametros")
GUARDA = PermissionGuard()
_CONDICAO = {Perfil.ADMINISTRACAO: "operacionais", Perfil.TI: "técnicos"}  # linha do DDS §4.6


@dataclass(frozen=True, slots=True)
class LinhaParametro:
    parametro: ParametroVigente
    rotulo: str
    unidade: str
    valor_exibido: str
    padrao_exibido: str
    limites: str
    editor: str
    editavel: bool


def _servicos() -> ServicosWeb:
    servicos: ServicosWeb = current_app.config["SAR_SERVICOS"]
    return servicos


def _exibir(valor: Valor, unidade: str) -> str:
    if isinstance(valor, bool):
        return "Sim" if valor else "Não"
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    if valor is None:
        return "Não definida"
    return f"{valor} {UNIDADES.get(unidade, '')}".strip()


def _linhas(contexto: Contexto) -> list[LinhaParametro]:
    linhas = []
    for p in _servicos().configuracao.listar_parametros(contexto):
        limites = f"de {p.minimo} a {p.maximo} {UNIDADES.get(p.unidade, '')}".strip() if p.minimo is not None else ""
        linhas.append(
            LinhaParametro(
                parametro=p,
                rotulo=PARAMETROS.get(p.nome, p.nome),
                unidade=UNIDADES.get(p.unidade, ""),
                valor_exibido=_exibir(p.valor, p.unidade),
                padrao_exibido=_exibir(p.padrao, p.unidade),
                limites=limites,
                editor=PERFIS.get(p.editor, p.editor.value),
                editavel=GUARDA.pode(contexto, "config.parametro.alterar", _CONDICAO[p.editor]),
            )
        )
    return linhas


def _ler(unidade: str, texto: str) -> Valor:
    """O valor do formulário no tipo da unidade; ValueError se não der para ler."""
    if unidade == "bool":
        if texto not in ("sim", "nao"):
            raise ValueError("sim ou não")
        return texto == "sim"
    if unidade == "data":
        return date.fromisoformat(texto)
    return int(texto)


def _mensagem(erro: RegraViolada) -> str:
    if erro.codigo == "parametro.fora_dos_limites":
        return f"Fora dos limites: use um valor de {erro.detalhe.get('minimo')} a {erro.detalhe.get('maximo')}."
    if erro.codigo == "parametro.imutavel":
        return "A data de implantação não muda depois da primeira sessão confirmada (DD-51)."
    return "Valor em formato inválido."


@bp.get("")
def lista() -> str:
    contexto = contexto_atual()
    alterado = request.args.get("alterado", "")
    resultado = f"{PARAMETROS[alterado]}: valor alterado." if alterado in PARAMETROS else None
    return render_template("parametros.html", linhas=_linhas(contexto), resultado=resultado)


@bp.post("/<nome>")
def alterar(nome: str) -> Response | str:
    contexto = contexto_atual()
    linha = next((li for li in _linhas(contexto) if li.parametro.nome == nome), None)
    if linha is None:
        raise NaoEncontrado()
    try:
        valor = _ler(linha.parametro.unidade, request.form.get("valor", "").strip())
        _servicos().configuracao.alterar_parametro(contexto, nome, valor)
    except ValueError:
        erro = "Valor em formato inválido." if linha.parametro.unidade != "data" else "Informe uma data válida."
        return render_template("parametros.html", linhas=_linhas(contexto), erro=f"{linha.rotulo}: {erro}")
    except RegraViolada as erro:
        return render_template("parametros.html", linhas=_linhas(contexto), erro=f"{linha.rotulo}: {_mensagem(erro)}")
    return redirect(url_for("parametros.lista", alterado=nome))
