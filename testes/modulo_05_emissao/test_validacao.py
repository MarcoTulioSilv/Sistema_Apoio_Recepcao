"""Validação do modelo .docx no envio (DD-42, DDS §9.2): o corpus hostil do CT-EMI-01, montado em memória."""

from __future__ import annotations

import io
import zipfile

import pytest

from sar.modulo_05_emissao.contrato import Modelo, Problema
from sar.modulo_05_emissao.validacao import validar
from testes.apoio.modelos import Partes, alterado, inicial, no_texto

TRECHO = '<w:r><w:rPr>{}</w:rPr><w:t xml:space="preserve">{}</w:t></w:r>'
FECHA, ABRE = "</w:t></w:r>", '<w:r><w:t xml:space="preserve">'
EXTERNO = "http://198.51.100.7"  # endereço reservado para documentação (RFC 5737): nunca é buscado


def codigos(arquivo: bytes, modelo: Modelo = Modelo.CATETER) -> set[tuple[str, str | None]]:
    return {(p.codigo, p.detalhe) for p in validar(arquivo, modelo).problemas}


@pytest.mark.requisito("DD-42", "DD-103", "RNF-703")
@pytest.mark.parametrize("modelo", list(Modelo))
def test_modelos_iniciais_passam_na_validacao(modelo: Modelo) -> None:
    resultado = validar(inicial(modelo), modelo)
    assert resultado.aprovado and resultado.avisos == ()


def _macro(conteudo: Partes) -> None:
    tipos = conteudo["[Content_Types].xml"].decode()
    conteudo["[Content_Types].xml"] = tipos.replace(
        "wordprocessingml.document.main+xml", "ms-word.document.macroEnabled.main+xml"
    ).encode()
    conteudo["word/vbaProject.bin"] = b"\xd0\xcf\x11\xe0 sem codigo"  # cabeçalho OLE falso, inerte


def _vinculo_externo(conteudo: Partes) -> None:
    relacoes = conteudo["word/_rels/document.xml.rels"].decode()
    externa = (
        '<Relationship Id="rIdX" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        f'Target="{EXTERNO}/rastreio.png" TargetMode="External"/>'
    )
    conteudo["word/_rels/document.xml.rels"] = relacoes.replace(
        "</Relationships>", externa + "</Relationships>"
    ).encode()


def _campo_externo(conteudo: Partes) -> None:
    documento = conteudo["word/document.xml"].decode()
    campo = f'<w:r><w:instrText xml:space="preserve"> INCLUDEPICTURE "{EXTERNO}/x.png" </w:instrText></w:r>'
    conteudo["word/document.xml"] = documento.replace("</w:p>", campo + "</w:p>", 1).encode()


def _entidade_externa(conteudo: Partes) -> None:
    documento = conteudo["word/document.xml"].decode()
    dtd = '<!DOCTYPE w:document [<!ENTITY x SYSTEM "file:///etc/hostname">]>'
    conteudo["word/document.xml"] = documento.replace("?>", "?>" + dtd, 1).replace("{{ nome }}", "&x;").encode()


def _jinja_nas_propriedades(conteudo: Partes) -> None:
    propriedades = conteudo["docProps/core.xml"].decode()
    conteudo["docProps/core.xml"] = propriedades.replace("</cp:coreProperties>", "<dc:title>{{ cpf }}</dc:title>"
                                                         "</cp:coreProperties>").encode()  # fmt: skip


def _fonte(conteudo: Partes) -> None:
    documento = conteudo["word/document.xml"].decode()
    conteudo["word/document.xml"] = documento.replace('w:ascii="Arial"', 'w:ascii="Comic Sans MS"', 1).encode()


@pytest.mark.requisito("DD-42", "DD-46", "CT-EMI-01")
@pytest.mark.parametrize(
    ("arquivo", "esperado"),
    [
        (alterado(_macro), ("arquivo.macro", None)),
        (no_texto("{% for x in range(9) %}{{ x }}{% endfor %}"), ("estrutura.proibida", "for")),
        (no_texto("{% if nome %}{{ nome }}{% endif %}"), ("estrutura.proibida", "if")),
        (no_texto("{{ nome|upper }}"), ("estrutura.proibida", "filter")),
        (no_texto("{{ nome.__class__ }}"), ("estrutura.proibida", "getattr")),
        (no_texto("{{ lipsum.__globals__ }}"), ("estrutura.proibida", "getattr")),
        (no_texto("{{ cycler() }}"), ("estrutura.proibida", "call")),
        (no_texto("{# nota #}{{ nome }}"), ("estrutura.proibida", "comentario")),
        (no_texto("{{ cpf }}"), ("variavel.desconhecida", "cpf")),
        (no_texto("{{ nome "), ("variavel.sintaxe", None)),
        (alterado(_vinculo_externo), ("referencia.externa", None)),
        (alterado(_campo_externo), ("referencia.externa", None)),
        (alterado(_entidade_externa), ("xml.dtd", None)),
        (alterado(_jinja_nas_propriedades), ("variavel.fora_do_texto", "docProps/core.xml")),
        (alterado(_fonte), ("fonte.indisponivel", "Comic Sans MS")),
        (b"%PDF-1.7 nao e docx", ("arquivo.tipo", None)),
        (b"PK\x03\x04 zip quebrado", ("arquivo.tipo", None)),
        (b"PK\x03\x04" + b"\x00" * (5 * 1024 * 1024), ("arquivo.tamanho", None)),
    ],
    ids=["macro", "laco", "condicao", "filtro", "atributo", "globais", "chamada", "comentario", "desconhecida",
         "sintaxe", "vinculo", "campo", "entidade", "propriedades", "fonte", "pdf", "zip_quebrado", "grande"],
)  # fmt: skip
def test_modelo_hostil_e_recusado_no_envio(arquivo: bytes, esperado: tuple[str, str | None]) -> None:
    assert esperado in codigos(arquivo)


@pytest.mark.requisito("DD-42", "CT-EMI-01")
def test_bomba_de_descompressao_recusada_antes_de_ler() -> None:
    def bomba(conteudo: Partes) -> None:
        conteudo["word/media/zeros.bin"] = b"\x00" * (30 * 1024 * 1024)  # comprime para ~30 KB

    assert codigos(alterado(bomba)) == {("arquivo.partes", None)}


@pytest.mark.requisito("DD-42")
def test_variavel_de_outro_documento_e_desconhecida() -> None:
    assert ("variavel.desconhecida", "foto") in codigos(no_texto("{{ foto }}"), Modelo.CATETER)
    assert validar(no_texto("{{ foto }}", Modelo.CRACHA), Modelo.CRACHA).aprovado


@pytest.mark.requisito("DD-42")
def test_variavel_partida_com_formatos_diferentes_vira_aviso_com_o_nome() -> None:
    partida = FECHA + TRECHO.format("<w:b/>", "{{ no") + TRECHO.format("<w:i/>", "me }}") + ABRE
    resultado = validar(no_texto(partida), Modelo.CATETER)
    assert resultado.aprovado and resultado.avisos == (Problema("variavel.partida", "nome"),)
    mesma_formatacao = FECHA + TRECHO.format("<w:b/>", "{{ no") + TRECHO.format("<w:b/>", "me }}") + ABRE
    assert validar(no_texto(mesma_formatacao), Modelo.CATETER).avisos == ()


@pytest.mark.requisito("DD-42")
def test_zip_que_nao_e_docx_e_recusado() -> None:
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w") as pacote:
        pacote.writestr("leia.txt", "nada")
    assert codigos(saida.getvalue()) == {("arquivo.tipo", None)}
