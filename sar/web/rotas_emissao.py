"""Emissão de documentos a partir da ficha (DDS §9.1) e o ciclo dos modelos .docx da administração (§9.2, DD-42).

O PDF vai inline, para imprimir pelo navegador, com no-store (RNF-206, RNF-405); nada fica guardado (DD-43). Os
formulários da ficha abrem o documento numa aba nova; aviso ou recusa aparecem nessa aba, com o caminho de volta.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, current_app, redirect, render_template, request, url_for
from werkzeug.wrappers import Response as RespostaWerkzeug

from sar.modulo_01_acesso.contrato import PermissionGuard
from sar.modulo_05_emissao.contrato import Documento, Modelo, Problema
from sar.nucleo.erros import ConfirmacaoNecessaria, IndisponivelExterno, NaoEncontrado, RegraViolada
from sar.web import contexto_atual
from sar.web.configuracao import ServicosWeb

bp = Blueprint("emissao", __name__)
GUARDA = PermissionGuard()

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TAMANHO_MAXIMO_MODELO = 5 * 1024 * 1024
CRACHA = "cracha"

ERROS_EMISSAO = {
    "instituicao.ausente": "Os dados da clínica ainda não foram cadastrados. A administração cadastra em Dados da "
    "clínica; sem eles, o documento não sai.",
    "cracha.sem_foto": "O paciente não tem foto. Tire a foto em Editar dados, na ficha, e emita o crachá de novo.",
}
CONVERSOR_FORA = "O gerador de documentos não respondeu. Tente de novo em instantes; se continuar, avise o TI."

# §9.2: cada problema do modelo enviado, em linguagem simples.
PROBLEMAS = {
    "arquivo.tipo": "O arquivo não é um documento do Word (.docx) válido.",
    "arquivo.macro": 'O arquivo tem macro, controle ou objeto embutido. Salve como "Documento do Word (.docx)".',
    "arquivo.tamanho": "O arquivo passa de 5 MB.",
    "arquivo.partes": "O arquivo tem conteúdo demais ou compactado de forma suspeita.",
    "xml.dtd": "O arquivo tem uma estrutura interna que não é aceita.",
    "referencia.externa": "O documento aponta para um endereço de fora (imagem vinculada, hiperlink ou campo). Use "
    "só imagens inseridas no próprio documento.",
    "variavel.desconhecida": "A variável {{{{ {detalhe} }}}} não existe para este documento. Confira o nome na lista.",
    "variavel.sintaxe": "Há chaves {{ }} incompletas ou fora do padrão {{ nome_da_variavel }}.",
    "variavel.fora_do_texto": "Há chaves {{ }} fora do texto do documento (nas propriedades ou em comentários).",
    "estrutura.proibida": "O documento usa um recurso que não é aceito ({detalhe}): só variáveis no formato "
    "{{ nome_da_variavel }}.",
    "fonte.indisponivel": 'A fonte "{detalhe}" não está disponível no gerador. Use Arial, Times New Roman, Calibri, '
    "Cambria ou Courier New.",
    "preenchimento.falhou": "O modelo passou na conferência, mas não foi possível preenchê-lo.",
}
RESULTADOS_MODELO = {
    "enviado": "Modelo enviado. Confira a prévia e ative quando estiver certo.",
    "ativado": "Versão ativada: as próximas emissões já usam este modelo.",
}
AVISOS = {"variavel.partida": "A variável {{{{ {detalhe} }}}} ficou com partes em formatação diferente. Apague e "
          "digite de novo a variável inteira no Word."}  # fmt: skip


def _servicos() -> ServicosWeb:
    servicos: ServicosWeb = current_app.config["SAR_SERVICOS"]
    return servicos


def explicar(problema: Problema, textos: dict[str, str] = PROBLEMAS) -> str:
    modelo = textos.get(problema.codigo, "Problema no arquivo ({codigo}).")
    return modelo.format(detalhe=problema.detalhe or "", codigo=problema.codigo)


def pdf_inline(conteudo: bytes, nome: str) -> Response:
    """DDS §9.1: o PDF abre no navegador para imprimir; nunca fica no cache da estação."""
    resposta = Response(conteudo, mimetype="application/pdf")
    resposta.headers["Content-Disposition"] = f'inline; filename="{nome}"'
    return resposta


def anexo(conteudo: bytes, nome: str, tipo: str) -> Response:
    resposta = Response(conteudo, mimetype=tipo)
    resposta.headers["Content-Disposition"] = f'attachment; filename="{nome}"'
    return resposta


# ------------------------------------------------------------------ emissão (§9.1)
def _aviso(paciente_id: int, mensagem: str, status: int = 422, **extra: Any) -> tuple[str, int]:
    return render_template("emissao_aviso.html", paciente_id=paciente_id, mensagem=mensagem, **extra), status


@bp.post("/pacientes/<int:paciente_id>/emitir/<documento>")
def emitir(paciente_id: int, documento: str) -> Response | tuple[str, int]:
    contexto = contexto_atual()
    try:
        if documento == CRACHA:
            emitido = _servicos().emissao.emitir_cracha(contexto, paciente_id)
        else:
            try:
                escolhido = Documento(documento)
            except ValueError:
                raise NaoEncontrado() from None
            troca = request.form.get("troca", "")
            emitido = _servicos().emissao.emitir(
                contexto, escolhido, paciente_id, int(troca) if troca.isdigit() else None,
                confirmar_reemissao=request.form.get("confirmar") == "1",
            )  # fmt: skip
    except ConfirmacaoNecessaria as aviso:  # RF-805: o termo de extra já saiu neste mês
        vezes = aviso.dados.get("emissoes", 1)
        mensagem = f"O termo de diálise extra deste paciente já foi emitido {vezes} vez(es) neste mês."
        return _aviso(paciente_id, mensagem, 200, confirmar=documento)
    except RegraViolada as erro:
        return _aviso(paciente_id, ERROS_EMISSAO.get(erro.codigo, "Não foi possível emitir o documento."))
    except IndisponivelExterno:
        return _aviso(paciente_id, CONVERSOR_FORA, 503)
    return pdf_inline(emitido.pdf, emitido.nome_arquivo)


# ------------------------------------------------------------------ modelos (§9.2)
def _modelo(codigo: str) -> Modelo:
    try:
        return Modelo(codigo)
    except ValueError:
        raise NaoEncontrado() from None


def _pagina_modelos(**dados: Any) -> str:
    contexto = contexto_atual()
    resumos = _servicos().modelos.listar(contexto)
    return render_template("modelos.html", resumos=resumos, **dados)


@bp.get("/modelos")
def modelos() -> str:
    resultado = RESULTADOS_MODELO.get(request.args.get("resultado", ""))
    return _pagina_modelos(resultado=resultado, versao_enviada=request.args.get("versao"),
                           modelo_enviado=request.args.get("modelo"))  # fmt: skip


@bp.get("/modelos/<codigo>/<int:versao>/arquivo")
def baixar_modelo(codigo: str, versao: int) -> Response:
    modelo = _modelo(codigo)
    arquivo = _servicos().modelos.baixar(contexto_atual(), modelo, versao)
    return anexo(arquivo, f"{modelo.value}-v{versao}.docx", DOCX)


@bp.get("/modelos/<codigo>/<int:versao>/previa")
def previa_modelo(codigo: str, versao: int) -> Response | tuple[str, int]:
    try:
        pdf = _servicos().modelos.previa(contexto_atual(), _modelo(codigo), versao)
    except IndisponivelExterno:
        return render_template("erro.html", titulo="Gerador fora do ar", mensagem=CONVERSOR_FORA), 503
    return pdf_inline(pdf, f"previa-{codigo.lower()}-v{versao}.pdf")


@bp.post("/modelos/<codigo>")
def enviar_modelo(codigo: str) -> RespostaWerkzeug | str:
    contexto = contexto_atual()
    modelo = _modelo(codigo)
    GUARDA.exigir(contexto, "emissao.modelo.enviar")
    arquivo = request.files.get("arquivo")
    conteudo = arquivo.stream.read(TAMANHO_MAXIMO_MODELO + 1) if arquivo else b""
    try:
        envio = _servicos().modelos.enviar(contexto, modelo, conteudo)
    except RegraViolada as erro:
        problemas = [explicar(Problema(c, d)) for c, d in erro.detalhe.get("problemas", [])] or [
            "Não foi possível conferir o arquivo."
        ]
        return _pagina_modelos(problemas=problemas, modelo_com_problema=modelo.value)
    except IndisponivelExterno:
        return _pagina_modelos(erro=CONVERSOR_FORA)
    if envio.avisos:
        return _pagina_modelos(resultado="Modelo enviado, com avisos. Confira a prévia antes de ativar.",
                               avisos=[explicar(a, AVISOS) for a in envio.avisos], versao_enviada=str(envio.versao),
                               modelo_enviado=modelo.value)  # fmt: skip
    return redirect(url_for("emissao.modelos", resultado="enviado", modelo=modelo.value, versao=envio.versao))


@bp.post("/modelos/<codigo>/<int:versao>/ativar")
def ativar_modelo(codigo: str, versao: int) -> RespostaWerkzeug:
    _servicos().modelos.ativar(contexto_atual(), _modelo(codigo), versao)
    return redirect(url_for("emissao.modelos", resultado="ativado"))
