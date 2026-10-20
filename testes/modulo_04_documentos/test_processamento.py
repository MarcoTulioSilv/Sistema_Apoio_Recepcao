"""Validação, reconstrução e extração (DDS §8.3, etapas 3, 5 e 6): CT-DOC-01 na parte da validação, CT-DOC-03,
CT-DOC-07 na parte do texto integral e CT-DOC-08; isolamento em subprocesso (DD-35)."""

from __future__ import annotations

import io
import os
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path

import pikepdf
import pytest
from PIL import Image

from sar.modulo_04_documentos import isolamento
from sar.modulo_04_documentos.isolamento import executar
from sar.modulo_04_documentos.processamento import (
    Limites,
    Recusa,
    campos_do_texto,
    processar,
    tipo_real,
)
from testes.apoio import corpus
from testes.apoio.fabrica import Fabrica

LIMITES = Limites(pixels_por_pagina=12_000_000, paginas=30)
CAMPOS = ("cpf", "cns", "data_nascimento")


def _recusa(funcao: object, *args: object) -> str:
    with pytest.raises(Recusa) as erro:
        funcao(*args)  # type: ignore[operator]
    return erro.value.codigo


@pytest.fixture
def tesseract_falso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Um "Tesseract" que devolve sempre o mesmo texto: CPF válido, CNS e uma frase que nunca pode ser guardada."""
    paciente = Fabrica(7).paciente()
    texto = f"Paciente {paciente.nome}\nCPF {paciente.cpf}\nCNS {paciente.cns}\nDIAGNOSTICO SIGILOSO\n"
    script = tmp_path / "tesseract_falso.py"
    script.write_text(f"import sys\nsys.stdin.buffer.read()\nsys.stdout.write({texto!r})\n", encoding="utf-8")
    if sys.platform == "win32":
        programa = tmp_path / "tesseract.cmd"
        programa.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        programa = tmp_path / "tesseract"
        programa.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        programa.chmod(0o755)
    monkeypatch.setenv("SAR_TESSERACT", str(programa))
    return paciente.cpf


@pytest.fixture
def sem_tesseract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SAR_TESSERACT", str(tmp_path / "nao-existe"))


# ------------------------------------------------------------------ validação
@pytest.mark.requisito("CT-DOC-01", "SEG-02", "SEG-03", "SEG-04", "SEG-05", "SEG-10", "SEG-12", "SEG-30", "QAS-05")
@pytest.mark.parametrize("hostil", corpus.hostis(), ids=lambda h: h.nome)
def test_corpus_hostil_recusado_com_o_motivo(hostil: corpus.Hostil) -> None:
    assert _recusa(processar, [hostil.conteudo], "scanner", CAMPOS, LIMITES, False) == hostil.motivo


@pytest.mark.requisito("SEG-03")
def test_tipo_real_pela_assinatura() -> None:
    assert tipo_real(corpus.png()) == "png" and tipo_real(corpus.jpeg()) == "jpeg"
    assert tipo_real(corpus.tiff_varias_paginas(1)) == "tiff" and tipo_real(corpus.pdf_com_texto()) == "pdf"


@pytest.mark.requisito("SEG-30")
def test_paginas_somadas_entre_arquivos_respeitam_o_limite() -> None:
    limites = Limites(pixels_por_pagina=12_000_000, paginas=3)
    assert processar([corpus.png()] * 3, "scanner", (), limites, False).paginas == 3
    assert _recusa(processar, [corpus.png()] * 2 + [corpus.tiff_varias_paginas(2)], "scanner", (), limites,
                   False) == "paginas.excedido"  # fmt: skip


# ------------------------------------------------------------------ reconstrução
def _conferir_pdfa(conteudo: bytes, paginas: int) -> None:
    with pikepdf.open(io.BytesIO(conteudo)) as pdf:
        assert len(pdf.pages) == paginas
        with pdf.open_metadata() as meta:
            assert meta["pdfaid:part"] == "2" and meta["pdfaid:conformance"] == "B"
        assert pdf.Root.OutputIntents[0].S == pikepdf.Name.GTS_PDFA1
        for objeto in pdf.objects:
            if isinstance(objeto, pikepdf.Dictionary):
                assert objeto.get("/Type") not in (pikepdf.Name.Font, pikepdf.Name.Annot, pikepdf.Name.Action)
                assert "/OpenAction" not in objeto and "/AA" not in objeto and "/Names" not in objeto
        for pagina in pdf.pages:
            [(_, imagem)] = pagina.Resources.XObject.items()
            assert imagem.ColorSpace == pikepdf.Name.DeviceGray and imagem.Filter == pikepdf.Name.DCTDecode
            assert b"BT" not in pagina.Contents.read_bytes()  # nenhuma camada de texto


@pytest.mark.requisito("CT-DOC-03", "SEG-10", "DC-07")
@pytest.mark.parametrize(
    ("arquivos", "paginas"),
    [([corpus.png()], 1), ([corpus.jpeg(), corpus.png()], 2), ([corpus.tiff_varias_paginas(3)], 3),
     ([corpus.pdf_com_texto(2)], 2)],
    ids=["png", "jpeg+png", "tiff", "pdf-com-texto"],
)  # fmt: skip
def test_reconstrucao_gera_pdfa_em_cinza_sem_texto(arquivos: list[bytes], paginas: int, sem_tesseract: None) -> None:
    feito = processar(arquivos, "scanner", CAMPOS, LIMITES, True)
    assert feito.formato == "pdf" and feito.paginas == paginas and feito.campos == ()
    assert b"Maria Ficticia" not in feito.conteudo and b"Helvetica" not in feito.conteudo
    _conferir_pdfa(feito.conteudo, paginas)


@pytest.mark.requisito("CT-DOC-03", "SEG-10", "DC-07")
def test_pdfa_aprovado_pelo_verapdf(tmp_path: Path, sem_tesseract: None) -> None:
    verapdf = shutil.which(os.environ.get("SAR_VERAPDF") or "verapdf")
    if not verapdf:
        pytest.skip("veraPDF ausente nesta máquina; o CI roda este teste (PT §6.2)")
    arquivo = tmp_path / "saida.pdf"
    arquivo.write_bytes(processar([corpus.png()], "scanner", (), LIMITES, False).conteudo)
    relatorio = subprocess.run(  # noqa: S603
        [verapdf, "--flavour", "2b", "--format", "text", str(arquivo)], capture_output=True, text=True, check=False
    )
    assert relatorio.stdout.startswith("PASS"), relatorio.stdout


@pytest.mark.requisito("CT-DOC-03", "SEG-10", "DC-07")
def test_foto_reencodada_sem_metadados() -> None:
    original = corpus.foto_com_exif()
    assert Image.open(io.BytesIO(original)).getexif()  # o original tem EXIF
    feito = processar([original], "webcam", (), LIMITES, True)
    foto = Image.open(io.BytesIO(feito.conteudo))
    assert feito.formato == "jpeg" and foto.mode == "RGB" and foto.size == (640, 480)
    assert not foto.getexif() and b"Ficticia" not in feito.conteudo and "exif" not in foto.info


@pytest.mark.requisito("SEG-30")
def test_foto_tem_uma_imagem_so() -> None:
    assert _recusa(processar, [corpus.jpeg(), corpus.jpeg()], "webcam", (), LIMITES, False) == "paginas.excedido"


# ------------------------------------------------------------------ extração
@pytest.mark.requisito("DD-40", "RF-704")
def test_campos_do_texto_com_confianca_pelo_digito() -> None:
    fabrica = Fabrica(3)
    cpf, cns = fabrica.cpf(), fabrica.cns()
    errado = cpf[:-1] + str((int(cpf[-1]) + 1) % 10)
    texto = f"CPF {cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]} CNS {cns} nascido em 05/03/1961 CEP 74000-100"
    achados = {c.nome: c for c in campos_do_texto(texto, ("cpf", "cns", "data_nascimento", "cep"))}
    assert achados["cpf"].valor == cpf and achados["cpf"].confianca == "alta"
    assert achados["cns"].valor == cns and achados["cns"].confianca == "alta"
    assert achados["data_nascimento"].valor == "1961-03-05" and achados["cep"].valor == "74000100"
    assert campos_do_texto(f"CPF {errado}", ("cpf",))[0].confianca == "baixa"
    assert campos_do_texto(texto, ("cep",)) == [c for c in achados.values() if c.nome == "cep"]  # só os do tipo


@pytest.mark.requisito("CT-DOC-07", "SEG-31", "P-18", "DD-40")
def test_so_os_campos_do_tipo_saem_da_extracao(tesseract_falso: str) -> None:
    feito = processar([corpus.png()], "scanner", ("cpf",), LIMITES, True)
    assert [(c.nome, c.valor) for c in feito.campos] == [("cpf", tesseract_falso)]
    assert b"SIGILOSO" not in feito.conteudo  # o texto integral não vai nem para o documento


@pytest.mark.requisito("CT-DOC-08", "QAS-08", "RNF-702")
def test_extracao_desligada_ou_sem_tesseract_nao_impede(tesseract_falso: str, monkeypatch: pytest.MonkeyPatch,
                                                        tmp_path: Path) -> None:  # fmt: skip
    desligada = processar([corpus.png()], "scanner", ("cpf",), LIMITES, False)
    assert desligada.campos == () and desligada.formato == "pdf"
    monkeypatch.setenv("SAR_TESSERACT", str(tmp_path / "nao-existe"))
    ausente = processar([corpus.png()], "scanner", ("cpf",), LIMITES, True)
    assert ausente.campos == () and ausente.formato == "pdf"


# ------------------------------------------------------------------ isolamento
@pytest.mark.requisito("DD-35", "SEG-30", "CT-DOC-07")
def test_processamento_no_subprocesso(tesseract_falso: str) -> None:
    feito = executar([corpus.png()], "scanner", ("cpf",), LIMITES, True, tempo_maximo=60)
    assert feito.formato == "pdf" and feito.paginas == 1 and feito.campos[0].valor == tesseract_falso
    _conferir_pdfa(feito.conteudo, 1)
    with pytest.raises(Recusa) as erro:
        executar([corpus.pdf_com_javascript()], "scanner", (), LIMITES, False, tempo_maximo=60)
    assert erro.value.codigo == "pdf.conteudo_ativo"


@pytest.mark.requisito("DD-35", "SEG-30")
def test_subprocesso_que_passa_do_tempo_e_recusado() -> None:
    with pytest.raises(Recusa) as erro:
        executar([corpus.png()], "scanner", (), LIMITES, False, tempo_maximo=0.05)
    assert erro.value.codigo == "processamento.tempo"


@pytest.mark.requisito("DD-35", "SEG-30")
def test_resposta_do_filho_fora_do_protocolo_e_falha() -> None:
    def quadro(cabecalho: dict[str, object], partes: list[bytes]) -> bytes:
        saida = io.BytesIO()
        isolamento.escrever_quadro(saida, cabecalho, partes)
        return saida.getvalue()

    valido = {"ok": True, "formato": "pdf", "paginas": 1, "campos": []}
    assert isolamento._interpretar(quadro(valido, [b"x"]), (), 10).conteudo == b"x"
    estranhos = [
        b"lixo",
        quadro({**valido, "formato": "html"}, [b"x"]),
        quadro({**valido, "campos": [{"nome": "nome_mae", "valor": "x", "confianca": "alta"}]}, [b"x"]),
        quadro(valido, [b"x" * 11]),  # passa do máximo
    ]
    for saida in estranhos:
        with pytest.raises(ValueError):
            isolamento._interpretar(saida, ("cpf",), 10)


@pytest.mark.requisito("SEG-30")
def test_filho_nao_herda_credenciais(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAR_BANCO_SENHA", "segredo")
    monkeypatch.setenv("SAR_CHAVE_MESTRA", "segredo")
    ambiente = isolamento._ambiente()
    assert (
        "SAR_BANCO_SENHA" not in ambiente
        and "SAR_CHAVE_MESTRA" not in ambiente
        and "PATH" in {k.upper() for k in ambiente}
    )
