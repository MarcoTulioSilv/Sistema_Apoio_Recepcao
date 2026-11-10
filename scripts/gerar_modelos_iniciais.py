"""Gera os cinco modelos .docx iniciais (DD-103, DEC-76) em sar/modulo_05_emissao/modelos_iniciais/.

Cada modelo reproduz o formulário em branco que a clínica já usa (título, texto e disposição), criado do zero com
python-docx: nada dos arquivos originais é copiado, nem metadado, nem imagem (DC-09). As lacunas viram variáveis da
lista fechada (sar/modulo_05_emissao/variaveis.py); o cabeçalho vem dos dados institucionais (RF-802) e o rodapé leva
o código de integridade (DD-86). Rodar de novo depois de mudar este script:

    python scripts/gerar_modelos_iniciais.py
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from docx import Document
from docx.enum.table import WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

DESTINO = Path(__file__).resolve().parents[1] / "sar" / "modulo_05_emissao" / "modelos_iniciais"
SERIFADA, SEM_SERIFA, CALIBRI = "Times New Roman", "Arial", "Calibri"
LINHA = "_" * 52
EXATA = WD_ROW_HEIGHT_RULE.EXACTLY


# ------------------------------------------------------------------ apoio
def novo() -> Document:
    documento = Document()
    secao = documento.sections[0]
    secao.page_width, secao.page_height = Mm(210), Mm(297)
    secao.top_margin = secao.bottom_margin = Mm(20)
    secao.left_margin = secao.right_margin = Mm(25)
    estilo = documento.styles["Normal"]
    estilo.font.name, estilo.font.size = SERIFADA, Pt(12)
    estilo.paragraph_format.space_after = Pt(0)
    propriedades = documento.core_properties
    propriedades.author = propriedades.last_modified_by = propriedades.comments = ""
    propriedades.title = propriedades.subject = propriedades.keywords = propriedades.category = ""
    propriedades.created = propriedades.modified = datetime(2026, 11, 4, tzinfo=UTC)
    propriedades.revision = 1
    return documento


def fonte(execucao: object, nome: str) -> None:
    """A fonte em todos os alfabetos do Word, para o conversor não trocar por outra."""
    rfonts = execucao._element.get_or_add_rPr().get_or_add_rFonts()  # type: ignore[attr-defined]
    for atributo in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(atributo), nome)


def texto(
    paragrafo: Paragraph,
    conteudo: str,
    tamanho: float = 12,
    negrito: bool = False,
    nome: str = SERIFADA,
    maiusculas: bool = False,
    sublinhado: bool = False,
    cor: RGBColor | None = None,
) -> None:
    execucao = paragrafo.add_run(conteudo)
    execucao.font.size, execucao.font.bold = Pt(tamanho), negrito
    execucao.font.all_caps, execucao.font.underline = maiusculas, sublinhado
    if cor is not None:
        execucao.font.color.rgb = cor
    fonte(execucao, nome)


def paragrafo(
    destino: Document | _Cell,
    conteudo: str = "",
    alinhamento: WD_ALIGN_PARAGRAPH = WD_ALIGN_PARAGRAPH.LEFT,
    entre_linhas: float = 1.0,
    antes: float = 0,
    depois: float = 0,
    recuo: float = 0,
    **formato: object,
) -> Paragraph:
    novo_paragrafo = destino.add_paragraph()
    novo_paragrafo.alignment = alinhamento
    formato_paragrafo = novo_paragrafo.paragraph_format
    formato_paragrafo.line_spacing = entre_linhas
    formato_paragrafo.space_before, formato_paragrafo.space_after = Pt(antes), Pt(depois)
    if recuo:
        formato_paragrafo.first_line_indent = Mm(recuo)
    if conteudo:
        texto(novo_paragrafo, conteudo, **formato)  # type: ignore[arg-type]
    return novo_paragrafo


def bordas(elemento: object, lados: tuple[str, ...] = ("top", "left", "bottom", "right"), espessura: int = 8) -> None:
    """Borda simples num parágrafo (w:pBdr) ou numa tabela (w:tblBorders)."""
    xml = elemento._element if hasattr(elemento, "_element") else elemento  # type: ignore[attr-defined]
    if xml.tag == qn("w:tbl"):
        propriedades, nome = xml.tblPr, "w:tblBorders"
    else:
        propriedades, nome = xml.get_or_add_pPr(), "w:pBdr"
    grupo = OxmlElement(nome)
    for lado in lados:
        borda = OxmlElement(f"w:{lado}")
        for chave, valor in (("w:val", "single"), ("w:sz", str(espessura)), ("w:space", "4"), ("w:color", "000000")):
            borda.set(qn(chave), valor)
        grupo.append(borda)
    propriedades.append(grupo)


def tabela(destino: object, linhas: int, colunas: int, larguras_mm: tuple[float, ...]) -> Table:
    if isinstance(destino, _Cell) or hasattr(destino, "sections"):
        nova = destino.add_table(rows=linhas, cols=colunas)  # type: ignore[union-attr]
    else:  # cabeçalho e rodapé pedem a largura total
        nova = destino.add_table(linhas, colunas, Mm(sum(larguras_mm)))  # type: ignore[attr-defined]
    nova.alignment = WD_TABLE_ALIGNMENT.CENTER
    nova.autofit = False
    # Largura total, grade e leiaute fixo: sem os três, o LibreOffice redistribui as colunas.
    propriedades = nova._tbl.tblPr
    largura_total = OxmlElement("w:tblW")
    largura_total.set(qn("w:w"), str(int(Mm(sum(larguras_mm)).twips)))
    largura_total.set(qn("w:type"), "dxa")
    leiaute = OxmlElement("w:tblLayout")
    leiaute.set(qn("w:type"), "fixed")
    for antigo in propriedades.findall(qn("w:tblW")):
        propriedades.remove(antigo)
    propriedades.append(largura_total)
    propriedades.append(leiaute)
    for coluna, largura in zip(nova._tbl.tblGrid.findall(qn("w:gridCol")), larguras_mm, strict=True):
        coluna.set(qn("w:w"), str(int(Mm(largura).twips)))
    for linha in nova.rows:
        for celula, largura in zip(linha.cells, larguras_mm, strict=True):
            celula.width = Mm(largura)
    return nova


def limpar(celula: _Cell) -> _Cell:
    """A célula nova vem com um parágrafo vazio; os conteúdos entram com add_paragraph."""
    for vazio in list(celula.paragraphs):
        vazio._element.getparent().remove(vazio._element)
    return celula


def rodape(documento: Document) -> None:
    """DD-86: o código de integridade sai no rodapé de todo documento emitido."""
    rodape_ = documento.sections[0].footer
    linha = rodape_.paragraphs[0]
    linha.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    texto(linha, "Código de integridade: {{ codigo_integridade }}", 7, nome=SEM_SERIFA, cor=RGBColor(0x55, 0x55, 0x55))


def endereco_da_clinica() -> str:
    return "{{ clinica_endereco }} - CEP: {{ clinica_cep }} - {{ clinica_municipio }}-{{ clinica_uf }}"


def assinatura(documento: Document, legenda: str, antes: float = 36) -> None:
    paragrafo(documento, LINHA, WD_ALIGN_PARAGRAPH.CENTER, antes=antes)
    paragrafo(documento, legenda, WD_ALIGN_PARAGRAPH.CENTER, antes=4)


# ------------------------------------------------------------------ DOC-02 Termo de cateter
def cateter() -> Document:
    documento = novo()
    caixa = paragrafo(documento, "{{ clinica_nome }}", WD_ALIGN_PARAGRAPH.CENTER, tamanho=16, negrito=True,
                      nome=SEM_SERIFA, maiusculas=True)  # fmt: skip
    texto(caixa, "\n" + endereco_da_clinica(), 8, nome=SEM_SERIFA, maiusculas=True)
    texto(caixa, "\nFONE: {{ clinica_telefone }}", 8, nome=SEM_SERIFA)
    bordas(caixa)
    paragrafo(documento, "TERMO DE RESPONSABILIDADE", WD_ALIGN_PARAGRAPH.CENTER, antes=48, depois=18, tamanho=14,
              negrito=True, sublinhado=True)  # fmt: skip
    corpo = paragrafo(documento, alinhamento=WD_ALIGN_PARAGRAPH.JUSTIFY, recuo=12.5)
    texto(corpo, "EU, ", negrito=True)
    texto(corpo, "{{ nome }}", negrito=True, maiusculas=True, sublinhado=True)
    texto(corpo, ", DECLARO ESTAR CIENTE DE TODOS OS RISCOS E COMPLICAÇÕES POSSÍVEIS ADVINDAS DO IMPLANTE DE "
                 "CATETER DUPLO LÚMEN PARA HEMODIÁLISE.")  # fmt: skip
    for trecho in (
        "DENTRE AS COMPLICAÇÕES DESTACAM-SE: SANGRAMENTO NO PULMÃO (HEMOTÓRAX), PERFURAÇÃO PULMONAR "
        "(PNEUMOTÓRAX), LESÃO DO NERVO RESPONSÁVEL PELA VOZ E DICÇÃO (NERVO LARÍNGEO RECORRENTE), COMPLICAÇÃO DA "
        "PERMANÊNCIA DO CATETER (TROMBOEMBOLISMO PULMONAR), INFECÇÃO E SANGRAMENTOS DIVERSOS COM OUTRAS "
        "CONSEQUÊNCIAS.",
        "ASSIM AUTORIZO OS PROCEDIMENTOS ACIMA CITADOS, ISENTANDO A EQUIPE MÉDICA E O CENTRO DE URO-NEFROLOGIA DE "
        "QUALQUER RESPONSABILIDADE.",
        "E POR FIM FIRMO ESTE.",
    ):
        paragrafo(documento, trecho, WD_ALIGN_PARAGRAPH.JUSTIFY, recuo=12.5)
    paciente = paragrafo(documento, "PACIENTE: ", WD_ALIGN_PARAGRAPH.CENTER, antes=72)
    texto(paciente, "_" * 42)
    paragrafo(documento, "{{ data_extenso }}.", WD_ALIGN_PARAGRAPH.RIGHT, antes=36, maiusculas=True)
    rodape(documento)
    return documento


# ------------------------------------------------------------------ DOC-03 Declaração de troca de turno
def troca() -> Document:
    documento = novo()
    cabecalho = documento.sections[0].header.paragraphs[0]
    cabecalho.alignment = WD_ALIGN_PARAGRAPH.CENTER
    texto(cabecalho, "{{ clinica_nome }}", 9, maiusculas=True)
    texto(cabecalho, "\n" + endereco_da_clinica(), 9, maiusculas=True)
    texto(cabecalho, "\nFONE: {{ clinica_telefone }}", 9)
    paragrafo(documento, "TERMO DE RESPONSABILIDADE", WD_ALIGN_PARAGRAPH.CENTER, antes=48, negrito=True)
    paragrafo(documento, "Troca de Turno", WD_ALIGN_PARAGRAPH.CENTER, antes=12, depois=30, negrito=True)
    corpo = paragrafo(documento, alinhamento=WD_ALIGN_PARAGRAPH.JUSTIFY, entre_linhas=2.0)
    texto(corpo, "Eu, ")
    texto(corpo, "{{ nome }}", sublinhado=True)
    texto(corpo, ", paciente em tratamento hemodialítico neste serviço, solicito troca de turno, referente ao dia "
                 "{{ data_origem }}, turno: {{ turno_origem }}. Declaro para devidos fins que assumo total "
                 "responsabilidade pelos riscos e consequências pela troca de turno. Dessa forma isento a equipe de "
                 "enfermagem, médica e o Centro de Uro-Nefrologia de qualquer responsabilidade.")  # fmt: skip
    paragrafo(documento, "E por fim firmo este.", entre_linhas=2.0)
    assinatura(documento, "Assinatura do Paciente ou Responsável.")
    paragrafo(documento, "Paciente irá realizar tratamento hemodialítico no dia {{ data_destino }}, "
                         "{{ turno_destino }} turno.", WD_ALIGN_PARAGRAPH.JUSTIFY, 2.0, antes=30)  # fmt: skip
    assinatura(documento, "Assinatura da Enfermeira(o) / Carimbo.", antes=24)
    paragrafo(documento, "{{ data_extenso }}.", WD_ALIGN_PARAGRAPH.RIGHT, antes=12)
    rodape(documento)
    return documento


# ------------------------------------------------------------------ DOC-04 Termo de alimentos
def alimentos() -> Document:
    documento = novo()
    caixa = paragrafo(documento, "{{ clinica_nome }}", WD_ALIGN_PARAGRAPH.CENTER, tamanho=20, negrito=True,
                      nome="Cambria")  # fmt: skip
    texto(caixa, "\nFone: {{ clinica_telefone }}", 16, negrito=True, nome="Cambria")
    bordas(caixa)
    paragrafo(documento, "Certificado de Responsabilidade", antes=30, depois=36, negrito=True)
    corpo = paragrafo(documento, alinhamento=WD_ALIGN_PARAGRAPH.JUSTIFY, entre_linhas=1.5, tamanho=11)
    texto(corpo, "Ao paciente, ", 11)
    texto(corpo, "{{ nome }}", 11, sublinhado=True)
    texto(corpo, ", fica sob total responsabilidade do mesmo, familiares ou acompanhantes, a utilização de lanches, "
                 "frutas ou almoço trazidos de casa ou não, bem como a conservação dos mesmos. Se caso o paciente vier "
                 "a ter algum problema relacionado à toxicidade ou contaminação alimentar devido ao uso de alimentos "
                 "fora do Centro de Uro-Nefrologia, situado na " + endereco_da_clinica() + ", o mesmo fica isento de "
                 "qualquer responsabilidade sob qualquer natureza relacionada a esse tipo de problema ao uso de "
                 "alimentos que não fazem parte do serviço de alimentação dessa instituição.", 11)  # fmt: skip
    paragrafo(documento, "{{ data_extenso }}.", antes=36, tamanho=11)
    paragrafo(documento, "_" * 48, antes=48, tamanho=11)
    paragrafo(documento, "Ass. do paciente ou responsável ou digital", antes=2, recuo=12.5, tamanho=11)
    rodape(documento)
    return documento


# ------------------------------------------------------------------ DOC-07 Termo de diálise extra
def _bloco_extra(celula: _Cell) -> None:
    limpar(celula)
    paragrafo(celula, "Data da extra:", tamanho=9, negrito=True, nome=CALIBRI)
    paragrafo(celula, "Motivo da Prescrição de Sessão extra:", tamanho=9, negrito=True, nome=CALIBRI)
    for opcao in ("Hipervolemia – GID: ________", "Hiperfosfatemia", "Pré-transplante", "Outros " + "_" * 30):
        linha = paragrafo(celula, antes=6)
        texto(linha, "O  ", 14, nome=CALIBRI)
        texto(linha, opcao, 9, nome=CALIBRI)
    paragrafo(celula, "_" * 46, antes=8, tamanho=9, nome=CALIBRI)
    paragrafo(celula, "_" * 46, antes=4, depois=6, tamanho=9, nome=CALIBRI)
    assinaturas = tabela(celula, 2, 4, (19, 19, 19, 19))
    assinaturas.style = "Table Grid"
    for coluna, rotulo in enumerate(("Paciente", "Técnico de Enfermagem", "Enfermeira", "Médico(a)")):
        limpar(assinaturas.cell(0, coluna))
        paragrafo(assinaturas.cell(0, coluna), rotulo, tamanho=8, nome=CALIBRI)
    assinaturas.rows[1].height, assinaturas.rows[1].height_rule = Mm(14), EXATA


def extra() -> Document:
    documento = novo()
    secao = documento.sections[0]
    secao.left_margin = secao.right_margin = Mm(15)
    secao.top_margin = Mm(12)
    cabecalho = tabela(secao.header, 1, 2, (25, 155))
    logo = limpar(cabecalho.cell(0, 0))
    paragrafo(logo, "{{ logotipo }}")
    dados = limpar(cabecalho.cell(0, 1))
    paragrafo(dados, "{{ clinica_nome }}", WD_ALIGN_PARAGRAPH.CENTER, antes=4, tamanho=11, nome=SEM_SERIFA,
              maiusculas=True)  # fmt: skip
    paragrafo(dados, endereco_da_clinica(), WD_ALIGN_PARAGRAPH.CENTER, tamanho=9, nome=SEM_SERIFA, maiusculas=True)
    paragrafo(dados, "FONE: {{ clinica_telefone }}", WD_ALIGN_PARAGRAPH.CENTER, tamanho=9, nome=SEM_SERIFA)
    paragrafo(documento, "TERMO DE NECESSIDADE DE DIÁLISE EXTRA", WD_ALIGN_PARAGRAPH.CENTER, antes=6, depois=8,
              tamanho=10, negrito=True, nome=CALIBRI)  # fmt: skip
    identificacao = tabela(documento, 2, 2, (110, 70))
    for linha, (esquerda, direita) in enumerate(
        (("Paciente: {{ nome }}", "Data de Nascimento: {{ data_nascimento }}"),
         ("Mãe: {{ nome_mae }}", "Turno: {{ turno }}"))
    ):  # fmt: skip
        paragrafo(limpar(identificacao.cell(linha, 0)), esquerda, tamanho=10, nome=CALIBRI)
        paragrafo(limpar(identificacao.cell(linha, 1)), direita, tamanho=10, nome=CALIBRI)
    paragrafo(documento, tamanho=8)
    blocos = tabela(documento, 2, 2, (90, 90))
    blocos.style = "Table Grid"
    for celula in (blocos.cell(0, 0), blocos.cell(0, 1), blocos.cell(1, 0), blocos.cell(1, 1)):
        _bloco_extra(celula)
    rodape(documento)
    return documento


# ------------------------------------------------------------------ Crachá
def cracha() -> Document:
    """O crachá em uso (faixa com o logotipo dos dois lados e o nome da clínica; Nome, DN e Nome da Mãe), com a foto
    3 × 4 à esquerda dos dados (RF-808). Cartão de 9,5 × 6,5 cm no alto da folha A4, com borda para recorte."""
    documento = novo()
    cartao = tabela(documento, 2, 1, (95,))
    cartao.alignment = WD_TABLE_ALIGNMENT.LEFT
    bordas(cartao._tbl, ("top", "left", "bottom", "right", "insideH"), espessura=6)
    cartao.rows[0].height, cartao.rows[0].height_rule = Mm(21), EXATA
    cartao.rows[1].height, cartao.rows[1].height_rule = Mm(44), EXATA
    faixa = tabela(limpar(cartao.cell(0, 0)), 1, 3, (19, 53, 19))
    for coluna in (0, 2):
        paragrafo(limpar(faixa.cell(0, coluna)), "{{ logotipo }}", WD_ALIGN_PARAGRAPH.CENTER, antes=1, tamanho=6)
    paragrafo(limpar(faixa.cell(0, 1)), "{{ clinica_nome }}", WD_ALIGN_PARAGRAPH.CENTER, antes=14, tamanho=13)
    corpo = tabela(limpar(cartao.cell(1, 0)), 1, 2, (34, 57))
    paragrafo(limpar(corpo.cell(0, 0)), "{{ foto }}", WD_ALIGN_PARAGRAPH.CENTER, antes=4, tamanho=6)
    dados = limpar(corpo.cell(0, 1))
    for rotulo, variavel in (("Nome: ", "{{ nome }}"), ("DN: ", "{{ data_nascimento }}"),
                             ("Nome da Mãe: ", "{{ nome_mae }}")):  # fmt: skip
        linha = paragrafo(dados, antes=8)
        texto(linha, rotulo, 10, negrito=True, nome=CALIBRI)
        texto(linha, variavel, 10, negrito=True, nome=CALIBRI, maiusculas=True)
    rodape(documento)
    return documento


MODELOS: dict[str, Callable[[], Document]] = {
    "DOC-02": cateter,
    "DOC-03": troca,
    "DOC-04": alimentos,
    "DOC-07": extra,
    "CRACHA": cracha,
}


def main() -> int:
    DESTINO.mkdir(parents=True, exist_ok=True)
    for codigo, gerar in MODELOS.items():
        caminho = DESTINO / f"{codigo}.docx"
        gerar().save(str(caminho))
        print(f"{caminho.relative_to(DESTINO.parents[2])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
