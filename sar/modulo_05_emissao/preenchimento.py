"""Preenchimento de um modelo .docx (DD-42): docxtpl num ambiente Jinja2 isolado (sandbox), com escape automático
e erro para variável desconhecida. Só recebe modelo já validado (validacao.py) e devolve o .docx em memória; nada
vai a disco (DDS §9.2, Emissão).
"""

from __future__ import annotations

import io
from collections.abc import Mapping

from docx.shared import Mm
from docxtpl import DocxTemplate, InlineImage
from jinja2 import StrictUndefined
from jinja2.sandbox import ImmutableSandboxedEnvironment

# Tamanho fixo de cada imagem no documento: o modelo só marca a posição (variaveis.py descreve na tela de envio).
ALTURA_LOGOTIPO_MM = 15
FOTO_MM = (30, 40)  # 3 × 4


def _ambiente() -> ImmutableSandboxedEnvironment:
    return ImmutableSandboxedEnvironment(autoescape=True, undefined=StrictUndefined)


def preencher(modelo: bytes, valores: Mapping[str, str], imagens: Mapping[str, bytes | None]) -> bytes:
    """O .docx preenchido. `valores` traz todo texto da lista do documento ("" para o que falta: sai em branco);
    `imagens`, as variáveis de imagem (None: sai em branco). As propriedades do arquivo saem vazias."""
    documento = DocxTemplate(io.BytesIO(modelo))
    contexto: dict[str, object] = dict(valores)
    for nome, conteudo in imagens.items():
        if conteudo is None:
            contexto[nome] = ""
        elif nome == "foto":
            contexto[nome] = InlineImage(documento, io.BytesIO(conteudo), width=Mm(FOTO_MM[0]), height=Mm(FOTO_MM[1]))
        else:
            contexto[nome] = InlineImage(documento, io.BytesIO(conteudo), height=Mm(ALTURA_LOGOTIPO_MM))
    documento.render(contexto, jinja_env=_ambiente(), autoescape=True)
    propriedades = documento.docx.core_properties
    propriedades.author = propriedades.last_modified_by = propriedades.title = propriedades.subject = ""
    propriedades.comments = propriedades.keywords = propriedades.category = ""
    saida = io.BytesIO()
    documento.save(saida)
    return saida.getvalue()
