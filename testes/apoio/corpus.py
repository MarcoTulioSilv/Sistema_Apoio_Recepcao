"""Corpus da ingestão (PT §6.2): arquivos válidos e hostis, **montados pelo próprio teste**, nunca baixados. As
páginas válidas trazem só dados fictícios da fábrica.

A sequência EICAR é montada em pedaços em tempo de execução: assim o antivírus da máquina de desenvolvimento não
apaga este arquivo-fonte.
"""

from __future__ import annotations

import io
import struct
import zipfile
import zlib
from dataclasses import dataclass

import pikepdf
from PIL import Image, ImageDraw

from testes.apoio.fabrica import Fabrica


def eicar() -> bytes:
    partes = ("X5O!P%@AP[4\\PZX54(P^)7CC)7}$", "EICAR-STANDARD-", "ANTIVIRUS-TEST-FILE!$H+H*")
    return "".join(partes).encode()


# ------------------------------------------------------------------ páginas válidas
def imagem_pagina(linhas: list[str], tamanho: tuple[int, int] = (850, 1100), cor: bool = False) -> Image.Image:
    """Uma folha pequena (A4 a ~100 dpi, para o teste ser rápido) com as linhas de texto."""
    imagem = Image.new("RGB" if cor else "L", tamanho, "white")
    desenho = ImageDraw.Draw(imagem)
    for indice, linha in enumerate(linhas):
        desenho.text((60, 60 + 40 * indice), linha, fill="black")
    return imagem


def pagina_ficticia(semente: int = 1) -> Image.Image:
    paciente = Fabrica(semente).paciente()
    return imagem_pagina([f"Nome: {paciente.nome}", f"CPF: {paciente.cpf}", "Declaração de comparecimento"])


def em_formato(imagem: Image.Image, formato: str, **opcoes: object) -> bytes:
    saida = io.BytesIO()
    imagem.save(saida, format=formato, **opcoes)
    return saida.getvalue()


def png() -> bytes:
    return em_formato(pagina_ficticia(), "PNG")


def jpeg() -> bytes:
    return em_formato(pagina_ficticia(), "JPEG")


def tiff_varias_paginas(paginas: int = 3) -> bytes:
    folhas = [pagina_ficticia(i) for i in range(1, paginas + 1)]
    return em_formato(folhas[0], "TIFF", save_all=True, append_images=folhas[1:], compression="tiff_deflate")


def pdf_com_texto(paginas: int = 2) -> bytes:
    """Um PDF "de escritório", com camada de texto e fonte: a reconstrução tem de jogá-las fora."""
    pdf = pikepdf.new()
    fonte = pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica)
    for indice in range(paginas):
        texto = f"BT /F1 14 Tf 72 720 Td (Pagina {indice + 1} Maria Ficticia) Tj ET".encode()
        pdf.pages.append(pikepdf.Page(pikepdf.Dictionary(
            Type=pikepdf.Name.Page, MediaBox=[0, 0, 612, 792],
            Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=fonte)),
            Contents=pikepdf.Stream(pdf, texto),
        )))  # fmt: skip
    return _salvar(pdf)


def foto_com_exif() -> bytes:
    """Foto colorida com EXIF (câmera e "localização"): a reconstrução tem de sair sem nada disso."""
    foto = imagem_pagina(["foto"], (640, 480), cor=True)
    exif = Image.Exif()
    exif[0x010F] = "Fabricante Ficticio"  # Make
    exif[0x0110] = "Camera Ficticia"  # Model
    exif[0x8825] = {1: "S", 2: (16.0, 40.0, 0.0)}  # GPSInfo
    return em_formato(foto, "JPEG", exif=exif.tobytes())


def _salvar(pdf: pikepdf.Pdf) -> bytes:
    saida = io.BytesIO()
    pdf.save(saida)
    return saida.getvalue()


# ------------------------------------------------------------------ hostis
def _png_cru(largura: int, altura: int, linhas_zeradas: bool = True) -> bytes:
    """PNG de 1 bit montado à mão, com as linhas comprimidas em fluxo: pequeno no disco, enorme decodificado."""

    def bloco(tipo: bytes, dados: bytes) -> bytes:
        return struct.pack(">I", len(dados)) + tipo + dados + struct.pack(">I", zlib.crc32(tipo + dados))

    compressor = zlib.compressobj(9)
    linha = b"\x00" + b"\x00" * ((largura + 7) // 8)
    idat = b"".join(compressor.compress(linha) for _ in range(altura)) + compressor.flush()
    cabecalho = struct.pack(">IIBBBBB", largura, altura, 1, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + bloco(b"IHDR", cabecalho) + bloco(b"IDAT", idat) + bloco(b"IEND", b"")


def pdf_com_javascript() -> bytes:
    pdf = pikepdf.new()
    pdf.add_blank_page()
    acao = pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS=pikepdf.String("app.alert('x')"))
    pdf.Root.OpenAction = pdf.make_indirect(acao)
    return _salvar(pdf)


def pdf_paginas(total: int) -> bytes:
    pdf = pikepdf.new()
    for _ in range(total):
        pdf.add_blank_page()
    return _salvar(pdf)


def zip_minimo(nome: str = "word/document.xml") -> bytes:
    arquivo = io.BytesIO()
    with zipfile.ZipFile(arquivo, "w") as z:
        z.writestr(nome, "<x/>")
    return arquivo.getvalue()


@dataclass(frozen=True, slots=True)
class Hostil:
    nome: str  # o nome com que chegaria; o servidor ignora nome e extensão (SEG-03)
    conteudo: bytes
    motivo: str  # código da recusa esperado na validação (etapa 3)


def hostis() -> list[Hostil]:
    """Os itens do PT §6.2 que a validação recusa. O EICAR também cai aqui, mas o motivo final é a detecção
    (DD-96, testado com o antimalware); tamanho (recebimento) e token (abertura) são recusados em outras etapas."""
    executavel = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 120 + b"PE\x00\x00"
    return [
        Hostil("laudo.pdf", executavel, "tipo.nao_permitido"),
        Hostil("foto.jpg.exe", executavel, "tipo.nao_permitido"),
        Hostil("documento.pdf", zip_minimo("a.txt"), "tipo.nao_permitido"),
        Hostil(
            "documento.png",
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            "tipo.nao_permitido",
        ),
        Hostil("documento.jpg", zip_minimo(), "tipo.nao_permitido"),  # DOCX é ZIP
        Hostil("javascript.pdf", pdf_com_javascript(), "pdf.conteudo_ativo"),
        Hostil("poliglota.pdf", pdf_paginas(1) + zip_minimo(), "arquivo.poliglota"),
        Hostil("poliglota.jpg", jpeg() + pdf_paginas(1), "arquivo.poliglota"),
        Hostil("bomba.png", _png_cru(12_000, 12_000), "pixels.excedido"),
        Hostil("lado.png", _png_cru(50_000, 1), "pixels.excedido"),
        Hostil("paginas.pdf", pdf_paginas(500), "paginas.excedido"),
        Hostil("vazio.pdf", b"", "arquivo.vazio"),
        Hostil("truncado.png", png()[:200], "imagem.invalida"),
        Hostil("quebrado.pdf", b"%PDF-1.7\n" + b"\x00" * 64, "pdf.invalido"),
    ]


def eicar_com_extensao_permitida() -> list[Hostil]:
    """EICAR com nome de PDF e de JPEG (CT-DOC-02): a validação recusa pelo tipo, e o antimalware detecta (DD-96).
    O EICAR só é reconhecido no início do arquivo, como manda o padrão: por isso vai puro, sem cabeçalho."""
    return [Hostil("eicar.pdf", eicar(), "tipo.nao_permitido"), Hostil("eicar.jpg", eicar(), "tipo.nao_permitido")]
