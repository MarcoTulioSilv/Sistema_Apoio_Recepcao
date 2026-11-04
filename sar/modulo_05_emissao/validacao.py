"""Validação de um modelo .docx no envio (DD-42, DDS §9.2). Função pura: recebe o arquivo e o documento e devolve
cada problema encontrado, para a tela listar em linguagem simples. Nada do arquivo é executado nem buscado fora.

- Arquivo .docx real (assinatura e estrutura); .docm, macro, controle ActiveX e objeto embutido recusados.
- Tamanho, número de partes e descompressão limitados antes de ler; XML sem DTD nem entidade (sem resolução).
- Nenhuma referência externa: relação com destino de fora e campos que buscam arquivo ou endereço.
- Só `{{ variável }}` da lista do documento, no texto, nos cabeçalhos, nos rodapés e nas notas; nada de laço,
  condição, filtro, atributo, chamada ou comentário do Jinja.
- Variável partida pelo Word em trechos com formatação diferente vira aviso, com o nome dela.
- Fontes: só as que o conversor tem, ou que têm substituta métrica nele.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass

from docxtpl import DocxTemplate
from jinja2 import TemplateSyntaxError, nodes
from jinja2.sandbox import ImmutableSandboxedEnvironment
from lxml import etree

from sar.modulo_05_emissao.contrato import Modelo, Problema
from sar.modulo_05_emissao.variaveis import nomes

TAMANHO_MAXIMO = 5 * 1024 * 1024
PARTES_MAXIMO = 300
DESCOMPACTADO_MAXIMO = 40 * 1024 * 1024
TAXA_MAXIMA = 100  # descompactado / compactado de cada parte: acima disso, bomba de descompressão
TIPO_PRINCIPAL = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
PARTES_COM_TEXTO = re.compile(r"^word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$")
PROIBIDAS = re.compile(r"(^|/)(vbaProject\.bin|vbaData\.xml)$|^word/(activeX|embeddings)/", re.IGNORECASE)
CAMPO_EXTERNO = re.compile(r"\b(INCLUDEPICTURE|INCLUDETEXT|HYPERLINK|LINK|DDE|DDEAUTO|IMPORT)\b", re.IGNORECASE)
MARCAS_JINJA = ("{{", "{%", "{#", "%}", "}}", "#}")
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"

# Fonte do modelo → disponível no conversor ou com substituta métrica nele (DDS §9.2).
FONTES = {
    nome.casefold()
    for nome in (
        "Times New Roman", "Arial", "Courier New", "Calibri", "Cambria", "Liberation Serif", "Liberation Sans",
        "Liberation Mono", "Carlito", "Caladea", "DejaVu Sans", "DejaVu Serif", "DejaVu Sans Mono", "Noto Sans",
        "Noto Serif", "Symbol", "Wingdings", "Courier", "Helvetica", "Times",
    )
}  # fmt: skip


@dataclass(frozen=True, slots=True)
class Validacao:
    problemas: tuple[Problema, ...]  # impedem o envio
    avisos: tuple[Problema, ...]  # aparecem na tela, sem impedir

    @property
    def aprovado(self) -> bool:
        return not self.problemas


class _Recusa(Exception):
    def __init__(self, problema: Problema) -> None:
        self.problema = problema


def _parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False,
                           huge_tree=False, remove_comments=False)  # fmt: skip


def _abrir(arquivo: bytes) -> zipfile.ZipFile:
    if len(arquivo) > TAMANHO_MAXIMO:
        raise _Recusa(Problema("arquivo.tamanho"))
    if not arquivo.startswith(b"PK\x03\x04"):
        raise _Recusa(Problema("arquivo.tipo"))
    try:
        pacote = zipfile.ZipFile(io.BytesIO(arquivo))
        partes = pacote.infolist()
    except zipfile.BadZipFile:
        raise _Recusa(Problema("arquivo.tipo")) from None
    if len(partes) > PARTES_MAXIMO or sum(p.file_size for p in partes) > DESCOMPACTADO_MAXIMO:
        raise _Recusa(Problema("arquivo.partes"))
    for parte in partes:
        if parte.file_size > TAXA_MAXIMA * max(parte.compress_size, 1) and parte.file_size > 1024 * 1024:
            raise _Recusa(Problema("arquivo.partes"))
        if parte.flag_bits & 0x1:  # cifrada
            raise _Recusa(Problema("arquivo.tipo"))
    return pacote


def _xml(pacote: zipfile.ZipFile, nome: str) -> etree._Element:
    conteudo = pacote.read(nome)
    if b"<!DOCTYPE" in conteudo or b"<!ENTITY" in conteudo:
        raise _Recusa(Problema("xml.dtd"))
    try:
        return etree.fromstring(conteudo, _parser())
    except etree.XMLSyntaxError:
        raise _Recusa(Problema("arquivo.tipo")) from None


def _estrutura(pacote: zipfile.ZipFile) -> None:
    nomes_partes = set(pacote.namelist())
    if "[Content_Types].xml" not in nomes_partes or "word/document.xml" not in nomes_partes:
        raise _Recusa(Problema("arquivo.tipo"))
    if any(PROIBIDAS.search(nome) for nome in nomes_partes):
        raise _Recusa(Problema("arquivo.macro"))
    tipos = _xml(pacote, "[Content_Types].xml")
    principal = [e.get("ContentType", "") for e in tipos if e.get("PartName") == "/word/document.xml"]
    if principal != [TIPO_PRINCIPAL]:  # o .docm declara macroEnabled.main
        raise _Recusa(Problema("arquivo.macro"))


def _referencias_externas(pacote: zipfile.ZipFile) -> Iterator[Problema]:
    for nome in pacote.namelist():
        if nome.endswith(".rels"):
            for relacao in _xml(pacote, nome):
                if relacao.get("TargetMode", "").lower() == "external":
                    yield Problema("referencia.externa")
                    return
    for nome in pacote.namelist():
        if PARTES_COM_TEXTO.match(nome):
            raiz = _xml(pacote, nome)
            instrucoes = [t.text or "" for t in raiz.iter(f"{{{W}}}instrText")]
            instrucoes += [c.get(f"{{{W}}}instr", "") for c in raiz.iter(f"{{{W}}}fldSimple")]
            if any(CAMPO_EXTERNO.search(i) for i in instrucoes):
                yield Problema("referencia.externa")
                return


def _nos_permitidos(no: nodes.Node, permitidas: frozenset[str]) -> Iterator[Problema]:
    """Só Template → Output → (TemplateData | Name de leitura) é aceito (DD-42)."""
    for filho in no.iter_child_nodes():
        if isinstance(filho, nodes.Output | nodes.TemplateData):
            yield from _nos_permitidos(filho, permitidas)
        elif isinstance(filho, nodes.Name) and filho.ctx == "load" and isinstance(no, nodes.Output):
            if filho.name not in permitidas:
                yield Problema("variavel.desconhecida", filho.name)
        else:
            yield Problema("estrutura.proibida", type(filho).__name__.lower())


def _variaveis(pacote: zipfile.ZipFile, permitidas: frozenset[str]) -> Iterator[Problema]:
    ambiente = ImmutableSandboxedEnvironment()
    tradutor = DocxTemplate.__new__(DocxTemplate)  # só o patch_xml, que não usa estado
    for nome in sorted(pacote.namelist()):
        bruto = pacote.read(nome).decode("utf-8", errors="replace")
        if PARTES_COM_TEXTO.match(nome):
            fonte = tradutor.patch_xml(bruto)
            if "{#" in fonte:
                yield Problema("estrutura.proibida", "comentario")
                continue
            try:
                arvore = ambiente.parse(fonte)
            except TemplateSyntaxError:
                yield Problema("variavel.sintaxe")
                continue
            yield from _nos_permitidos(arvore, permitidas)
            yield from _partidas(bruto)
        elif nome.endswith((".xml", ".rels")) and any(m in bruto for m in MARCAS_JINJA):
            yield Problema("variavel.fora_do_texto", nome)  # propriedades, comentários, estilos...


def _partidas(bruto: str) -> Iterator[Problema]:
    """A variável que o Word dividiu em trechos com formatação diferente: o preenchimento junta e perde parte da
    formatação. Mesmo formato em todos os trechos não é problema."""
    for achado in re.finditer(r"\{(?:<[^>]*>)*\{(.*?)\}(?:<[^>]*>)*\}", bruto, flags=re.DOTALL):
        if "</w:r>" not in achado.group(0):
            continue
        inicio = max(bruto.rfind("<w:r>", 0, achado.start()), bruto.rfind("<w:r ", 0, achado.start()), 0)
        trecho = bruto[inicio : achado.end()]  # desde a execução em que a variável começa
        formatos = set(re.findall(r"<w:rPr>.*?</w:rPr>", trecho, flags=re.DOTALL))
        if len(formatos) > 1:
            yield Problema("variavel.partida", re.sub(r"<[^>]*>|\s", "", achado.group(1)) or None)


def _fontes(pacote: zipfile.ZipFile) -> Iterator[Problema]:
    """As fontes nomeadas no texto, nos estilos e na numeração; as do tema só se algum texto usa o tema."""
    usadas: set[str] = set()
    temas: set[str] = set()  # "major" e/ou "minor"
    for nome in pacote.namelist():
        if PARTES_COM_TEXTO.match(nome) or nome in ("word/styles.xml", "word/numbering.xml"):
            for rfonts in _xml(pacote, nome).iter(f"{{{W}}}rFonts"):
                usadas.update(rfonts.get(f"{{{W}}}{a}") or "" for a in ("ascii", "hAnsi"))
                for atributo in ("asciiTheme", "hAnsiTheme"):
                    referencia = rfonts.get(f"{{{W}}}{atributo}") or ""
                    temas.update(grupo for grupo in ("major", "minor") if referencia.startswith(grupo))
    for nome in pacote.namelist():
        if nome.startswith("word/theme/") and nome.endswith(".xml"):
            for grupo in temas:
                for fonte in _xml(pacote, nome).iter(f"{{{A}}}{grupo}Font"):
                    latina = fonte.find(f"{{{A}}}latin")
                    usadas.add(latina.get("typeface", "") if latina is not None else "")
    for fonte in sorted(f for f in usadas if f and f.casefold() not in FONTES):
        yield Problema("fonte.indisponivel", fonte)


def validar(arquivo: bytes, modelo: Modelo) -> Validacao:
    """Todos os problemas que o arquivo tem; recusa de estrutura para na primeira (o resto não é confiável)."""
    try:
        pacote = _abrir(arquivo)
        with pacote:
            _estrutura(pacote)
            problemas = [*_referencias_externas(pacote), *_fontes(pacote)]
            achados = list(_variaveis(pacote, nomes(modelo)))
    except _Recusa as recusa:
        return Validacao((recusa.problema,), ())
    except zipfile.BadZipFile, KeyError, OSError, ValueError:
        return Validacao((Problema("arquivo.tipo"),), ())
    problemas += [p for p in achados if p.codigo != "variavel.partida"]
    avisos = tuple(dict.fromkeys(p for p in achados if p.codigo == "variavel.partida"))
    return Validacao(tuple(dict.fromkeys(problemas)), avisos)
