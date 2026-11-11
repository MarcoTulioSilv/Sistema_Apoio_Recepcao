"""Carga inicial na aplicação (DDS §14.3, RF-1106): o relatório de exceções e avisos com o tratamento, a conferência
amostral lado a lado e o aceite da administração. A simulação e a efetivação são do TI, pela linha de comando (DD-65):
aqui não há botão para elas. Nenhum dado de paciente vai à URL: as rotas levam só o id da linha da carga."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from flask import Blueprint, current_app, redirect, render_template, request, url_for
from werkzeug.wrappers import Response as RespostaWerkzeug

from sar.modulo_01_acesso.contrato import PermissionGuard
from sar.modulo_10_carga.contrato import (
    CAMPOS_CONFERIDOS,
    Amostra,
    LinhaRelatorio,
    Modo,
    Original,
    Relatorio,
    ResultadoConferencia,
    Tratamento,
)
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import ConfirmacaoNecessaria, RegraViolada
from sar.web import contexto_atual
from sar.web.configuracao import ServicosWeb

bp = Blueprint("carga", __name__, url_prefix="/carga")
GUARDA = PermissionGuard()

# Os códigos do MOD-10 em linguagem da recepção: (título, explicação).
EXCECOES: dict[str, tuple[str, str]] = {
    "evento_saida": (
        "Consta na planilha de eventos",
        "O nome aparece numa saída (óbito, alta, transferência ou "
        "transplante). Confira se o paciente ainda está em tratamento: se estiver, cadastre pela tela; se "
        "não, descarte.",
    ),
    "P-03.minimo": (
        "Falta o mínimo do cadastro",
        "Falta o nome, o prontuário ou o início do tratamento. Cadastre pela tela, onde o rascunho ajuda.",
    ),
    "prontuario.repetido": (
        "Prontuário já usado por outra ficha",
        "Duas fichas têm o mesmo prontuário; a primeira entrou.",
    ),
    "cpf.repetido": ("CPF já usado por outra ficha", "Duas fichas têm o mesmo CPF; a primeira entrou."),
    "cns.repetido": ("CNS já usado por outra ficha", "Duas fichas têm o mesmo CNS; a primeira entrou."),
    "p1.rotulo_desconhecido": (
        "Ficha com um campo que a carga não reconhece",
        "A carga não adivinha: confira a ficha e cadastre pela tela, ou descarte.",
    ),
    "p1.rotulo_repetido": ("Ficha com um campo repetido", "O mesmo campo aparece duas vezes na ficha."),
    "p1.celula_ilegivel": ("Ficha com um campo ilegível", "Um campo de texto veio como data, fora do lugar."),
    "p1.ilegivel": ("Ficha ilegível", "Nenhum campo da ficha foi reconhecido."),
}
AVISOS: dict[str, tuple[str, str]] = {
    "convenio.desconhecido": (
        "Convênio não cadastrado: ficou sem cobertura",
        "Cadastre o convênio em Convênios e registre a cobertura na ficha.",
    ),
    "cep.generico": ("CEP genérico do município (termina em 000)", "Entra como pendência; confirme com o paciente."),
    "cep.invalido": ("CEP malformado: ficou vazio", "Vira pendência do cadastro."),
    "cep.ausente": ("Sem CEP na ficha", "Vira pendência do cadastro."),
    "cpf.invalido": ("CPF com dígito inválido: ficou vazio", "Vira pendência do cadastro."),
    "cns.invalido": ("CNS com dígito inválido: ficou vazio", "Vira pendência do cadastro."),
    "data_nascimento.invalida": ("Data de nascimento ilegível: ficou vazia", "Vira pendência do cadastro."),
    "inicio.antes_do_nascimento": ("Início antes do nascimento: o nascimento ficou vazio", "Confira as duas datas."),
    "inicio.invalido": ("Início do tratamento ilegível", "Se a planilha de entradas tinha a data, ela foi usada."),
    "ibge.ausente": ("Sem código do município", "Município ficou vazio; vira pendência."),
    "ibge.sem_correspondencia": (
        "Código do município não encontrado na tabela do IBGE",
        "Município ficou vazio; vira pendência.",
    ),
    "municipio.nome_divergente": ("Nome do município diferente do código", "Vale o código; confira o município."),
    "municipio.fora_de_goias": ("Município fora de Goiás: ficou vazio", "A residência é só em Goiás."),
    "municipio.inexistente": ("Município inexistente: ficou vazio", "Vira pendência do cadastro."),
    "telefone.ddd_presumido": ("Telefone sem DDD: presumido 64", "Confira com o paciente."),
    "telefone.numero": ("Telefone que não é celular nem fixo válido: não entrou", "Confira com o paciente."),
    "telefone.ddd": ("Telefone com DDD inexistente: não entrou", "Confira com o paciente."),
    "telefone.repetido": ("Telefone repetido na ficha", "Entrou uma vez só."),
    "telefone.nenhum": ("Sem telefone reconhecido", "Confira com o paciente."),
    "contato.sem_nome": ("Telefone de parente sem nome", "Entrou como recado do paciente."),
    "contato.parentesco_desconhecido": ("Parentesco fora da lista", "O contato entrou sem parentesco."),
    "endereco.incompleto": ("Endereço que não se separou bem", "Confira logradouro, número e bairro na ficha."),
    "rg.igual_cpf": ("RG igual ao CPF (é a CIN)", "O RG não entrou; o CPF basta."),
    "triade.coincidente": (
        "Possível duplicidade",
        "Nome, nascimento e mãe iguais a outro cadastro; veja nas pendências.",
    ),
    "p4.sem_linha": ("Sem linha na planilha de entradas", "Importado com o início da ficha."),
    "p4.varias_linhas": ("Mais de uma linha na planilha de entradas", "Valeu a entrada mais recente."),
    "p4.completou_inicio": ("Início do tratamento veio da planilha de entradas", "A ficha não tinha a data."),
    "p4.completou_cpf": ("CPF veio da planilha de entradas", "A ficha não tinha o CPF."),
    "p4.completou_cns": ("CNS veio da planilha de entradas", "A ficha não tinha o CNS."),
    "p4.completou_cep": ("CEP veio da planilha de entradas", "A ficha não tinha o CEP."),
    "p4.inicio_divergente": ("Início diferente na planilha de entradas", "Vale o da ficha; confira."),
    "p4.cpf_divergente": ("CPF diferente na planilha de entradas", "Vale o da ficha; confira no documento."),
    "p4.cns_divergente": ("CNS diferente na planilha de entradas", "Vale o da ficha; confira no cartão do paciente."),
}
ERROS = {
    "carga.motivo": "Descreva o motivo do descarte, com pelo menos 5 caracteres.",
    "carga.paciente_nao_encontrado": "Nenhum cadastro com esse prontuário. Cadastre pela tela antes.",
    "carga.paciente_ja_ligado": "Esse cadastro já está ligado a outra linha da carga.",
    "carga.linha_sem_excecao": "Esta linha não é uma exceção.",
    "carga.aceita": "A carga já foi aceita.",
    "carga.sem_efetivacao": "A carga ainda não foi efetivada pelo TI.",
    "carga.amostra_incompleta": "Termine de conferir todos os sorteados antes.",
    "carga.sem_divergencia": "Sem divergência na amostra, não há o que sortear de novo.",
    "carga.excecao_sem_tratamento": "Ainda há exceção sem decisão.",
    "carga.ativos_confirmados": "Informe quantos pacientes estão em tratamento hoje.",
    "carga.campo": "Campo desconhecido.",
}
RESULTADOS = {
    "tratada": "Decisão registrada.",
    "conferencia": "Conferência registrada.",
    "sorteados": "Mais pacientes sorteados para a conferência.",
    "aceita": "Carga aceita. A carga inicial está encerrada.",
}
_PRONTUARIO = re.compile(r"\s*N\s*[ºo°]?\s*\.?\s*PT\b.*$", re.IGNORECASE)


def _servicos() -> ServicosWeb:
    servicos: ServicosWeb = current_app.config["SAR_SERVICOS"]
    return servicos


def nome_da_ficha(original: Original) -> str:
    """O nome como está na célula PACIENTE da planilha, sem o número do prontuário."""
    for rotulo, valor in original.p1:
        if re.sub(r"[^A-Z]", "", rotulo.upper()) == "PACIENTE" and valor:
            return _PRONTUARIO.sub("", valor).strip() or valor
    return "Ficha sem nome"


def _passos(relatorio: Relatorio | None, amostra: Amostra) -> list[tuple[str, bool]]:
    if relatorio is None:
        return []
    if relatorio.modo is Modo.SIMULACAO:
        return [("Simulada pelo TI; a efetivação vem depois", False)]
    excecoes = [li for li in relatorio.linhas if li.excecao]
    tratadas = sum(1 for li in excecoes if li.tratamento)
    conferidos = sum(1 for p in amostra.pacientes if p.completo)
    return [
        ("Efetivada", True),
        (f"Exceções: {tratadas} de {len(excecoes)} tratadas", tratadas == len(excecoes)),
        (f"Amostra: {conferidos} de {len(amostra.pacientes)} conferidos", amostra.completa),
        ("Aceite da administração", relatorio.aceito_em is not None),
    ]


def _amostra(contexto: Contexto, relatorio: Relatorio | None) -> Amostra:
    if relatorio is None or relatorio.modo is not Modo.EFETIVACAO or relatorio.aceito_em is not None:
        return Amostra((), 0)
    return _servicos().carga.amostra(contexto)


def _relatorio(contexto: Contexto, **dados: Any) -> str:
    relatorio = _servicos().carga.relatorio(contexto)
    amostra = _amostra(contexto, relatorio)
    linhas = relatorio.linhas if relatorio else ()
    avisos: dict[str, list[LinhaRelatorio]] = defaultdict(list)
    for linha in linhas:
        if not linha.excecao:
            for codigo in linha.avisos:
                avisos[codigo].append(linha)
    ordem = sorted(avisos, key=lambda c: (-len(avisos[c]), c))
    return render_template(
        "carga_relatorio.html",
        rel=relatorio,
        excecoes=[li for li in linhas if li.excecao],
        avisos=[(codigo, avisos[codigo]) for codigo in ordem],
        textos_excecao=EXCECOES,
        textos_aviso=AVISOS,
        passos=_passos(relatorio, amostra),
        nome_da_ficha=nome_da_ficha,
        aba="relatorio",
        pode_tratar=GUARDA.pode(contexto, "carga.conferencia.registrar")
        and relatorio is not None
        and relatorio.modo is Modo.EFETIVACAO
        and relatorio.aceito_em is None,
        resultado=RESULTADOS.get(request.args.get("resultado", "")),
        **dados,
    )


@bp.get("")
def relatorio() -> str:
    return _relatorio(contexto_atual())


@bp.post("/excecoes/<int:linha_id>")
def tratar(linha_id: int) -> RespostaWerkzeug | tuple[str, int]:
    contexto = contexto_atual()
    escolha = request.form.get("tratamento", "")
    motivo, prontuario = request.form.get("motivo", ""), request.form.get("prontuario", "")
    if escolha not in Tratamento:
        return _relatorio(
            contexto,
            erro_linha=linha_id,
            erro="Escolha o que foi feito com a ficha.",
            digitado={"motivo": motivo, "prontuario": prontuario},
        ), 422
    try:
        _servicos().carga.tratar_excecao(contexto, linha_id, Tratamento(escolha), motivo, prontuario)
    except RegraViolada as erro:
        return _relatorio(
            contexto,
            erro_linha=linha_id,
            erro=ERROS.get(erro.codigo, "Confira os dados."),
            digitado={"motivo": motivo, "prontuario": prontuario, "tratamento": escolha},
        ), 422
    return redirect(url_for("carga.relatorio", resultado="tratada", _anchor=f"linha-{linha_id}"))


def _pagina_amostra(contexto: Contexto, **dados: Any) -> str:
    relatorio = _servicos().carga.relatorio(contexto)
    amostra = _amostra(contexto, relatorio)
    excecoes = [li for li in relatorio.linhas if li.excecao] if relatorio else []
    carregados = sum(
        1 for li in (relatorio.linhas if relatorio else ()) if li.tratamento is Tratamento.IMPORTADA_MANUAL
    )
    return render_template(
        "carga_amostra.html",
        rel=relatorio,
        amostra=amostra,
        passos=_passos(relatorio, amostra),
        aba="amostra",
        total_campos=len(CAMPOS_CONFERIDOS),
        pode_aceitar=GUARDA.pode(contexto, "carga.aceitar"),
        excecoes=len(excecoes),
        tratadas=sum(1 for li in excecoes if li.tratamento),
        importadas_a_mao=carregados,
        descartadas=sum(1 for li in excecoes if li.tratamento is Tratamento.DESCARTADA),
        resultado=RESULTADOS.get(request.args.get("resultado", "")),
        **dados,
    )


@bp.get("/amostra")
def amostra() -> str:
    return _pagina_amostra(contexto_atual())


@bp.post("/amostra/sortear")
def sortear() -> RespostaWerkzeug | tuple[str, int]:
    contexto = contexto_atual()
    try:
        _servicos().carga.sortear_mais(contexto)
    except RegraViolada as erro:
        return _pagina_amostra(contexto, erro=ERROS.get(erro.codigo, "Não foi possível sortear.")), 422
    return redirect(url_for("carga.amostra", resultado="sorteados"))


@bp.post("/aceitar")
def aceitar() -> RespostaWerkzeug | tuple[str, int]:
    contexto = contexto_atual()
    texto = request.form.get("ativos", "").strip()
    confirmar = request.form.get("confirmar") == "sim"
    if not texto.isdigit():
        return _pagina_amostra(contexto, erro_ativos=ERROS["carga.ativos_confirmados"], ativos=texto), 422
    try:
        _servicos().carga.aceitar(contexto, int(texto), confirmar)
    except ConfirmacaoNecessaria as pedido:
        return _pagina_amostra(contexto, diferenca=pedido.dados, ativos=texto), 422
    except RegraViolada as erro:
        return _pagina_amostra(contexto, erro=ERROS.get(erro.codigo, "Não foi possível aceitar."), ativos=texto), 422
    return redirect(url_for("carga.relatorio", resultado="aceita"))


def _pagina_conferencia(contexto: Contexto, linha_id: int, **dados: Any) -> str:
    conferencia = _servicos().carga.conferencia(contexto, linha_id)
    amostra = _servicos().carga.amostra(contexto)
    posicao = next((i for i, p in enumerate(amostra.pacientes, 1) if p.linha_id == linha_id), 0)
    return render_template(
        "carga_conferencia.html",
        c=conferencia,
        nome=nome_da_ficha(conferencia.original),
        posicao=posicao,
        total=len(amostra.pacientes),
        resultado=RESULTADOS.get(request.args.get("resultado", "")),
        **dados,
    )


@bp.get("/amostra/<int:linha_id>")
def conferir(linha_id: int) -> str:
    return _pagina_conferencia(contexto_atual(), linha_id)


@bp.post("/amostra/<int:linha_id>")
def registrar(linha_id: int) -> RespostaWerkzeug | tuple[str, int]:
    """Cada campo marcado vai à conferência; os não marcados ficam como estavam (dá para registrar em partes)."""
    contexto = contexto_atual()
    try:
        for campo, _ in CAMPOS_CONFERIDOS:
            valor = request.form.get(f"campo-{campo}", "")
            if valor in ResultadoConferencia:
                _servicos().carga.registrar_conferencia(contexto, linha_id, campo, ResultadoConferencia(valor))
    except RegraViolada as erro:
        return _pagina_conferencia(contexto, linha_id, erro=ERROS.get(erro.codigo, "Confira os campos.")), 422
    return redirect(url_for("carga.conferir", linha_id=linha_id, resultado="conferencia"))
