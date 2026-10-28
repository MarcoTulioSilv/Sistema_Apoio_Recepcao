"""Quarentena e cofre (DDS §8.3): CT-DOC-04 e CT-DOC-06 na parte do disco; DD-34, DD-37, DD-38, SEG-06 a SEG-08,
SEG-15, SEG-29."""

from __future__ import annotations

import io
import os
import uuid
from pathlib import Path

import pytest

from sar.modulo_04_documentos.armazenamento import Cofre, Pastas, Quarentena, hash_das_paginas, ler_limitado, sha256
from sar.modulo_08_dados.cifra import CifraAesGcm
from sar.nucleo.erros import IntegridadeViolada, RegraViolada

CIFRA = CifraAesGcm(bytes(range(32)))
PAGINA = b"\x89PNG pagina ficticia com o nome Maria Ficticia" * 50


@pytest.fixture
def quarentena(tmp_path: Path) -> Quarentena:
    return Quarentena(tmp_path / "quarentena", CIFRA)


@pytest.fixture
def cofre(tmp_path: Path) -> Cofre:
    return Cofre(tmp_path / "cofre", CIFRA)


# ------------------------------------------------------------------ quarentena
@pytest.mark.requisito("CT-DOC-06", "DD-34", "SEG-08", "SEG-07")
def test_quarentena_guarda_cifrado_com_nome_aleatorio_e_apaga(quarentena: Quarentena, tmp_path: Path) -> None:
    ingestao = uuid.uuid4().bytes
    hash_pagina = quarentena.gravar(ingestao, "p0001", PAGINA)
    assert hash_pagina == sha256(PAGINA)
    [arquivo] = (tmp_path / "quarentena" / ingestao.hex()).iterdir()
    assert b"Maria" not in arquivo.read_bytes() and b"PNG" not in arquivo.read_bytes()  # nada em claro no disco
    assert quarentena.ler(ingestao, "p0001") == PAGINA
    assert quarentena.nomes(ingestao) == ["p0001"] and quarentena.ingestoes() == [ingestao]
    quarentena.apagar(ingestao)
    assert quarentena.nomes(ingestao) == [] and quarentena.ingestoes() == []


@pytest.mark.requisito("SEG-08", "DD-07")
def test_cifrado_de_uma_pagina_nao_serve_em_outra(quarentena: Quarentena, tmp_path: Path) -> None:
    ingestao = uuid.uuid4().bytes
    quarentena.gravar(ingestao, "p0001", PAGINA)
    quarentena.gravar(ingestao, "p0002", b"outra")
    pasta = tmp_path / "quarentena" / ingestao.hex()
    (pasta / "p0002").write_bytes((pasta / "p0001").read_bytes())  # troca de arquivos no disco
    with pytest.raises(IntegridadeViolada):
        quarentena.ler(ingestao, "p0002")
    with pytest.raises(IntegridadeViolada):
        quarentena.ler(ingestao, "p0003")


@pytest.mark.requisito("SEG-06")
def test_leitura_do_envio_para_no_limite() -> None:
    assert ler_limitado(io.BytesIO(b"x" * 1000), 1000) == b"x" * 1000
    with pytest.raises(RegraViolada) as erro:
        ler_limitado(io.BytesIO(b"x" * 1001), 1000)
    assert erro.value.codigo == "arquivo.tamanho"


@pytest.mark.requisito("SEG-27")
def test_hash_de_entrada_depende_da_ordem_das_paginas() -> None:
    assert hash_das_paginas(["a", "b"]) != hash_das_paginas(["b", "a"])


@pytest.mark.requisito("CT-DOC-06", "SEG-29")
def test_quarentena_fora_da_pasta_do_cofre(tmp_path: Path) -> None:
    Pastas(tmp_path / "cofre", tmp_path / "quarentena")
    for cofre, quarentena in ((tmp_path / "a", tmp_path / "a" / "q"), (tmp_path / "b" / "c", tmp_path / "b")):
        with pytest.raises(ValueError):
            Pastas(cofre, quarentena)


# ------------------------------------------------------------------ cofre
@pytest.mark.requisito("DD-37", "SEG-15", "RNF-604")
def test_cofre_guarda_com_chave_propria_e_le_conferindo_o_hash(cofre: Cofre, tmp_path: Path) -> None:
    documento = uuid.uuid4().bytes
    guardado = cofre.guardar(documento, PAGINA)
    assert guardado.hash_sha256 == sha256(PAGINA) and len(guardado.chave_cifrada) <= 128
    [arquivo] = [p for p in (tmp_path / "cofre").rglob("*") if p.is_file()]
    assert arquivo.name == guardado.arquivo and b"Maria" not in arquivo.read_bytes()
    assert (
        cofre.ler(documento, guardado.arquivo, guardado.chave_cifrada, guardado.nonce, guardado.hash_sha256) == PAGINA
    )
    outro = uuid.uuid4().bytes  # a chave e o arquivo só servem ao próprio documento (dado associado)
    with pytest.raises(IntegridadeViolada):
        cofre.ler(outro, guardado.arquivo, guardado.chave_cifrada, guardado.nonce, guardado.hash_sha256)


@pytest.mark.requisito("CT-DOC-04", "DD-38", "SEG-15")
def test_arquivo_alterado_ou_ausente_no_disco_nao_e_lido(cofre: Cofre, tmp_path: Path) -> None:
    documento = uuid.uuid4().bytes
    g = cofre.guardar(documento, PAGINA)
    with pytest.raises(IntegridadeViolada):
        cofre.ler(documento, g.arquivo, g.chave_cifrada, g.nonce, sha256(b"outro"))  # hash gravado diverge
    [arquivo] = [p for p in (tmp_path / "cofre").rglob("*") if p.is_file()]
    bruto = bytearray(arquivo.read_bytes())
    bruto[10] ^= 0xFF
    arquivo.write_bytes(bytes(bruto))
    with pytest.raises(IntegridadeViolada):
        cofre.ler(documento, g.arquivo, g.chave_cifrada, g.nonce, g.hash_sha256)
    cofre.destruir(g.arquivo)
    with pytest.raises(IntegridadeViolada):
        cofre.ler(documento, g.arquivo, g.chave_cifrada, g.nonce, g.hash_sha256)


@pytest.mark.requisito("DD-37", "R-41")
def test_orfaos_e_temporarios_sao_encontrados_e_removidos(cofre: Cofre, tmp_path: Path) -> None:
    conhecido = cofre.guardar(uuid.uuid4().bytes, PAGINA).arquivo
    orfao = cofre.guardar(uuid.uuid4().bytes, PAGINA).arquivo
    sobra = tmp_path / "cofre" / "zz" / ".abc.tmp"
    sobra.parent.mkdir(parents=True)
    sobra.write_bytes(b"x")
    achados = cofre.orfaos({conhecido})
    assert {Path(a).name for a in achados} == {orfao, ".abc.tmp"}
    for relativo in achados:
        cofre.remover_orfao(relativo)
    assert cofre.orfaos({conhecido}) == []
    with pytest.raises(ValueError):
        cofre.remover_orfao("../fora")
    assert os.listdir(tmp_path / "cofre")
