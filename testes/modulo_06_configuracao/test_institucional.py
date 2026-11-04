"""Dados institucionais e logotipo, sem banco (RF-1201, RF-1202, DD-50)."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from sar.modulo_06_configuracao import logotipo
from sar.modulo_06_configuracao.contrato import DadosInstitucionais
from sar.modulo_06_configuracao.regras import cnpj_valido, validar_institucional
from sar.nucleo.erros import RegraViolada

VALIDOS = DadosInstitucionais(
    "  Clínica   Fictícia ", "Rua das Flores, 100 - Centro", "75803-000", "5211909", "(64) 3600-0000", "11.222.333/0001-81"
)


def imagem(formato: str, tamanho: tuple[int, int] = (120, 60), **opcoes: object) -> bytes:
    saida = io.BytesIO()
    Image.new("RGB", tamanho, "navy").save(saida, format=formato, **opcoes)
    return saida.getvalue()


@pytest.mark.requisito("RF-1201")
def test_dados_limpos_com_digitos_e_espacos_normalizados() -> None:
    limpo = validar_institucional(VALIDOS)
    assert (limpo.nome, limpo.cep, limpo.telefone, limpo.cnpj) == (
        "Clínica Fictícia", "75803000", "6436000000", "11222333000181"
    )  # fmt: skip
    opcionais = validar_institucional(DadosInstitucionais("Clínica", "Rua A, 1", "75803000", "5211909", " ", None))
    assert (opcionais.telefone, opcionais.cnpj) == (None, None)


@pytest.mark.requisito("RF-1201")
@pytest.mark.parametrize(
    ("campo", "valor"),
    [("nome", "X"), ("endereco", "Rua"), ("cep", "7580300"), ("municipio", "52119"), ("telefone", "3600-0000"),
     ("cnpj", "11.222.333/0001-80")],
)  # fmt: skip
def test_campo_invalido_e_recusado_pelo_nome(campo: str, valor: str) -> None:
    dados = _com(campo, valor)
    with pytest.raises(RegraViolada) as erro:
        validar_institucional(dados)
    assert erro.value.codigo == f"instituicao.{campo}"


def _com(campo: str, valor: str) -> DadosInstitucionais:
    campos = {c: getattr(VALIDOS, c) for c in ("nome", "endereco", "cep", "municipio", "telefone", "cnpj")}
    return DadosInstitucionais(**{**campos, campo: valor})


@pytest.mark.requisito("RF-1201")
def test_cnpj_pelos_digitos_verificadores() -> None:
    assert cnpj_valido("11222333000181")
    for invalido in ("11222333000180", "11111111111111", "1122233300018", "abcdefghijklmn"):
        assert not cnpj_valido(invalido)


@pytest.mark.requisito("RF-1202", "DD-50")
@pytest.mark.parametrize("formato", ["PNG", "JPEG"])
def test_logotipo_png_ou_jpeg_sai_png_novo_sem_metadados(formato: str) -> None:
    original = imagem(formato, exif=Image.Exif()) if formato == "JPEG" else imagem(formato)
    png = logotipo.processar(original)
    reaberto = Image.open(io.BytesIO(png))
    assert reaberto.format == "PNG" and reaberto.size == (120, 60) and "exif" not in reaberto.info


@pytest.mark.requisito("RF-1202", "DD-50")
@pytest.mark.parametrize(
    ("arquivo", "motivo"),
    [
        (b"", "vazio"),
        (b"GIF89a" + b"\x00" * 20, "tipo"),
        (imagem("PNG") + b"PK\x03\x04conteudo", "tipo"),  # poliglota
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * (logotipo.BYTES_MAXIMO + 1), "tamanho"),
        (b"\x89PNG\r\n\x1a\n" + b"lixo que nao e png", "invalido"),
        (imagem("PNG", (2100, 2000)), "invalido"),  # 4,2 milhões de pixels, acima do teto
    ],
    ids=["vazio", "gif", "poliglota", "grande", "corrompido", "pixels"],
)
def test_logotipo_hostil_e_recusado(arquivo: bytes, motivo: str) -> None:
    with pytest.raises(RegraViolada) as erro:
        logotipo.processar(arquivo)
    assert erro.value.codigo == f"logotipo.{motivo}"
