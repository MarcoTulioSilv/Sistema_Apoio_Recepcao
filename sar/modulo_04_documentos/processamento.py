"""Validação, reconstrução e extração de uma ingestão (DDS §8.3, etapas 3, 5 e 6). Roda **dentro do subprocesso**
isolado (DD-35, SEG-30): recebe os arquivos da quarentena já decifrados, nunca toca o disco e devolve só o documento
reconstruído e os campos candidatos. Toda recusa vira `Recusa` com o código do motivo (SEG-12).

- Tipo real pela assinatura binária, só PDF, JPEG, PNG e TIFF (SEG-02 a SEG-05); vazio, poliglota e PDF com
  conteúdo ativo recusados antes de qualquer decodificação.
- Limites de pixels, de lado e de páginas antes de decodificar (SEG-30).
- Reconstrução (SEG-10, DC-07): cada página vira uma imagem limpa, em tons de cinza a 300 dpi, num PDF/A-2b sem
  camada de texto; a foto vira JPEG colorido reencodado, sem metadados. O original é descartado.
- Extração (DD-40, SEG-31): o Tesseract lê a imagem reconstruída; só os campos candidatos do tipo saem daqui; o
  texto integral morre com o subprocesso.
"""

from __future__ import annotations

import io
import os
import re
import shutil

# Só o Tesseract, com caminho resolvido e argumentos fixos, sem shell.
import subprocess  # nosec B404
import warnings
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

import pikepdf
import pypdfium2 as pdfium
from PIL import Image, ImageCms

DPI = 300
QUALIDADE_JPEG = 85
LADO_MAXIMO = 15_000  # nenhuma página real chega perto: A4 a 300 dpi tem 2480 × 3508
FOTO_BYTES_MAXIMO = 2 * 1024 * 1024  # teto fixo da §10.1
FOTO_PIXELS_MAXIMO = 4_000_000
TEMPO_TESSERACT = 30

ASSINATURAS = {
    "pdf": (b"%PDF-",),
    "jpeg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "tiff": (b"II*\x00", b"MM\x00*"),
}
# Marcas de outro formato dentro do arquivo: poliglota ou contêiner disfarçado (SEG-04).
OUTROS_FORMATOS = (
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"Rar!\x1a\x07",
    b"7z\xbc\xaf\x27\x1c",
    b"<svg",
    b"<SVG",
    b"MZ\x90\x00",
)
# Chaves de PDF que executam algo ao abrir ou carregam outro arquivo: recusadas (SEG-10 elimina, mas avisa antes).
CHAVES_ATIVAS = {"/JavaScript", "/JS", "/Launch", "/EmbeddedFile", "/EmbeddedFiles", "/RichMedia", "/XFA", "/AA"}


class Recusa(Exception):
    """O arquivo não segue; `codigo` é o motivo mostrado ao operador e gravado na ingestão."""

    def __init__(self, codigo: str) -> None:
        super().__init__(codigo)
        self.codigo = codigo


@dataclass(frozen=True, slots=True)
class Limites:
    pixels_por_pagina: int
    paginas: int


@dataclass(frozen=True, slots=True)
class Campo:
    nome: str
    valor: str
    confianca: str  # "alta" (dígito verificador confere ou formato exato) ou "baixa": a tela destaca (RF-704)


@dataclass(frozen=True, slots=True)
class Reconstruido:
    conteudo: bytes  # PDF/A ou JPEG
    formato: str  # "pdf" ou "jpeg"
    paginas: int
    campos: tuple[Campo, ...] = field(default_factory=tuple)


# ------------------------------------------------------------------ validação (etapa 3)
def tipo_real(dados: bytes) -> str:
    """O formato pela assinatura no início do arquivo; extensão e tipo declarado não contam (SEG-03)."""
    if not dados:
        raise Recusa("arquivo.vazio")
    for tipo, marcas in ASSINATURAS.items():
        if dados.startswith(marcas):
            corpo = dados[len(marcas[0]) :]
            if any(m in corpo for m in OUTROS_FORMATOS) or (tipo != "pdf" and b"%PDF-" in corpo):
                raise Recusa("arquivo.poliglota")
            return tipo
    raise Recusa("tipo.nao_permitido")


def _conferir_imagem(imagem: Image.Image, limites: Limites) -> None:
    largura, altura = imagem.size
    if largura > LADO_MAXIMO or altura > LADO_MAXIMO or largura * altura > limites.pixels_por_pagina:
        raise Recusa("pixels.excedido")


def _abrir_imagem(dados: bytes, limites: Limites) -> Image.Image:
    Image.MAX_IMAGE_PIXELS = limites.pixels_por_pagina  # o Pillow também recusa bomba de descompressão
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            imagem = Image.open(io.BytesIO(dados))
            _conferir_imagem(imagem, limites)  # só o cabeçalho foi lido até aqui
            return imagem
    except Recusa:
        raise
    except Image.DecompressionBombError, Image.DecompressionBombWarning:
        raise Recusa("pixels.excedido") from None
    except Exception:
        raise Recusa("imagem.invalida") from None


def _quadros(imagem: Image.Image, limites: Limites) -> Iterator[Image.Image]:
    """As páginas de uma imagem (o TIFF pode ter várias), já decodificadas e conferidas."""
    total = getattr(imagem, "n_frames", 1)
    if total > limites.paginas:
        raise Recusa("paginas.excedido")
    for indice in range(total):
        try:
            imagem.seek(indice)
            _conferir_imagem(imagem, limites)
            imagem.load()
        except Recusa:
            raise
        except Exception:
            raise Recusa("imagem.invalida") from None
        yield imagem.copy()


def _conferir_pdf(dados: bytes, limites: Limites) -> int:
    """Abre o PDF sem renderizar: páginas e conteúdo ativo. Devolve o número de páginas."""
    try:
        with pikepdf.open(io.BytesIO(dados)) as pdf:
            if len(pdf.pages) > limites.paginas:
                raise Recusa("paginas.excedido")
            for objeto in pdf.objects:
                if isinstance(objeto, pikepdf.Dictionary) and CHAVES_ATIVAS.intersection(objeto.keys()):
                    raise Recusa("pdf.conteudo_ativo")
                if isinstance(objeto, pikepdf.Dictionary) and objeto.get("/S") in (
                    pikepdf.Name.JavaScript,
                    pikepdf.Name.Launch,
                ):
                    raise Recusa("pdf.conteudo_ativo")
            return len(pdf.pages)
    except Recusa:
        raise
    except Exception:
        raise Recusa("pdf.invalido") from None


def _paginas_do_pdf(dados: bytes, limites: Limites) -> Iterator[Image.Image]:
    _conferir_pdf(dados, limites)
    try:
        documento = pdfium.PdfDocument(dados)
    except Exception:
        raise Recusa("pdf.invalido") from None
    try:
        for pagina in documento:
            largura, altura = pagina.get_size()  # em pontos (1/72 pol.)
            escala = DPI / 72
            if largura * escala * altura * escala > limites.pixels_por_pagina:
                raise Recusa("pixels.excedido")
            yield pagina.render(scale=escala, grayscale=True).to_pil()
    finally:
        documento.close()


def paginas(arquivos: Sequence[bytes], limites: Limites) -> list[Image.Image]:
    """Todas as páginas da ingestão, validadas e decodificadas, na ordem."""
    resultado: list[Image.Image] = []
    for dados in arquivos:
        tipo = tipo_real(dados)
        novas = _paginas_do_pdf(dados, limites) if tipo == "pdf" else _quadros(_abrir_imagem(dados, limites), limites)
        for imagem in novas:
            resultado.append(imagem)
            if len(resultado) > limites.paginas:
                raise Recusa("paginas.excedido")
    if not resultado:
        raise Recusa("arquivo.vazio")
    return resultado


# ------------------------------------------------------------------ reconstrução (etapa 5)
def _perfil_srgb() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def documento_pdfa(imagens: Sequence[Image.Image]) -> bytes:
    """PDF/A-2b com uma imagem em tons de cinza por página, a 300 dpi, sem texto, fonte, anotação nem ação."""
    pdf = pikepdf.new()
    for imagem in imagens:
        cinza = imagem.convert("L")
        jpeg = io.BytesIO()
        cinza.save(jpeg, format="JPEG", quality=QUALIDADE_JPEG, dpi=(DPI, DPI))
        largura, altura = cinza.size
        objeto = pikepdf.Stream(pdf, jpeg.getvalue())
        objeto.Type, objeto.Subtype = pikepdf.Name.XObject, pikepdf.Name.Image
        objeto.Width, objeto.Height, objeto.BitsPerComponent = largura, altura, 8
        objeto.ColorSpace, objeto.Filter = pikepdf.Name.DeviceGray, pikepdf.Name.DCTDecode
        pontos_l, pontos_a = largura * 72 / DPI, altura * 72 / DPI
        conteudo = pikepdf.Stream(pdf, f"q {pontos_l:.2f} 0 0 {pontos_a:.2f} 0 0 cm /Im0 Do Q".encode())
        pagina = pikepdf.Dictionary(
            Type=pikepdf.Name.Page,
            MediaBox=[0, 0, pontos_l, pontos_a],
            Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=objeto)),
            Contents=conteudo,
        )
        pdf.pages.append(pikepdf.Page(pagina))
    perfil = pikepdf.Stream(pdf, _perfil_srgb())
    perfil.N = 3
    pdf.Root.OutputIntents = pikepdf.Array(
        [
            pikepdf.Dictionary(
                Type=pikepdf.Name.OutputIntent,
                S=pikepdf.Name.GTS_PDFA1,
                OutputConditionIdentifier="sRGB IEC61966-2.1",
                Info="sRGB IEC61966-2.1",
                DestOutputProfile=perfil,
            )
        ]
    )
    with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
        meta["pdfaid:part"] = "2"
        meta["pdfaid:conformance"] = "B"
        meta["dc:title"] = "Documento digitalizado"
        meta["xmp:CreatorTool"] = "SAR"
    saida = io.BytesIO()
    pdf.save(saida, fix_metadata_version=True, deterministic_id=True)
    return saida.getvalue()


def foto_jpeg(imagem: Image.Image) -> bytes:
    """A foto da webcam, reencodada em JPEG colorido sem nenhum metadado (sem EXIF, sem localização)."""
    largura, altura = imagem.size
    if largura * altura > FOTO_PIXELS_MAXIMO:
        raise Recusa("pixels.excedido")
    limpa = Image.new("RGB", imagem.size)
    limpa.paste(imagem.convert("RGB"))
    saida = io.BytesIO()
    limpa.save(saida, format="JPEG", quality=QUALIDADE_JPEG)
    if saida.tell() > FOTO_BYTES_MAXIMO:
        raise Recusa("arquivo.tamanho")
    return saida.getvalue()


# ------------------------------------------------------------------ extração (etapa 6)
def _digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto)


def _cpf_valido(cpf: str) -> bool:
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for n in (9, 10):
        soma = sum(int(cpf[i]) * (n + 1 - i) for i in range(n))
        if (soma * 10) % 11 % 10 != int(cpf[n]):
            return False
    return True


def _cns_valido(cns: str) -> bool:
    return len(cns) == 15 and cns[0] in "126789" and sum(int(d) * (15 - i) for i, d in enumerate(cns)) % 11 == 0


def campos_do_texto(texto: str, campos: Sequence[str]) -> list[Campo]:
    """Só os campos pedidos pelo tipo; o primeiro achado de cada. Valor bruto: quem confere é a recepcionista, e o
    MOD-02 valida de novo como digitação (SEG-26)."""
    achados: list[Campo] = []
    for nome in campos:
        if nome == "cep" and (m := re.search(r"\b\d{5}-?\d{3}\b", texto)):
            achados.append(Campo("cep", _digitos(m.group()), "alta"))
        elif nome == "cpf" and (m := re.search(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", texto)):
            cpf = _digitos(m.group())
            achados.append(Campo("cpf", cpf, "alta" if _cpf_valido(cpf) else "baixa"))
        elif nome == "cns" and (m := re.search(r"\b\d{3}\s?\d{4}\s?\d{4}\s?\d{4}\b", texto)):
            cns = _digitos(m.group())
            achados.append(Campo("cns", cns, "alta" if _cns_valido(cns) else "baixa"))
        elif nome == "data_nascimento" and (m := re.search(r"\b(\d{2})/(\d{2})/(\d{4})\b", texto)):
            achados.append(Campo("data_nascimento", f"{m.group(3)}-{m.group(2)}-{m.group(1)}", "baixa"))
        elif nome == "carteirinha" and (m := re.search(r"\b\d[\d .-]{7,24}\d\b", texto)):
            achados.append(Campo("carteirinha", _digitos(m.group()), "baixa"))
    return achados


def tesseract() -> str | None:
    """O executável do Tesseract: `SAR_TESSERACT` (instalação fora do PATH, comum no Windows) ou o do PATH."""
    return shutil.which(os.environ.get("SAR_TESSERACT") or "tesseract")


def ler_texto(imagens: Sequence[Image.Image], programa: str) -> str:
    """O texto das páginas pelo Tesseract, em português; só em memória, pela entrada e saída padrão."""
    partes = []
    for imagem in imagens:
        png = io.BytesIO()
        imagem.convert("L").save(png, format="PNG")
        saida = subprocess.run(  # noqa: S603 # nosec B603
            [programa, "stdin", "stdout", "-l", "por", "--psm", "6"],
            input=png.getvalue(), capture_output=True, timeout=TEMPO_TESSERACT, check=False,
        )  # fmt: skip
        partes.append(saida.stdout.decode("utf-8", errors="replace"))
    return "\n".join(partes)


def processar(
    arquivos: Sequence[bytes], origem: str, campos: Sequence[str], limites: Limites, extrair: bool
) -> Reconstruido:
    """As etapas 3, 5 e 6 de uma ingestão. `Recusa` em qualquer problema das etapas 3 e 5; a extração nunca recusa
    (RNF-702)."""
    imagens = paginas(arquivos, limites)
    if origem == "webcam":
        if len(imagens) != 1:
            raise Recusa("paginas.excedido")
        return Reconstruido(foto_jpeg(imagens[0]), "jpeg", 1)
    try:
        conteudo = documento_pdfa(imagens)
    except Exception:
        raise Recusa("reconstrucao.falhou") from None
    achados: list[Campo] = []
    programa = tesseract()
    if extrair and campos and programa:
        try:
            achados = campos_do_texto(ler_texto(imagens, programa), campos)
        except Exception:  # sem extração, a conferência segue manual (RNF-702)
            achados = []
    return Reconstruido(conteudo, "pdf", len(imagens), tuple(achados))
