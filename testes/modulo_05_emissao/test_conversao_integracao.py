"""Preenchimento e conversão (DD-42, DD-46, DD-104): o valor entra como texto, nunca como modelo nem marcação
(CT-EMI-02), e o conversor não alcança nada fora da rede interna (CT-EMI-03)."""

from __future__ import annotations

import os
import shutil

# Só o docker do próprio ambiente de teste, com argumentos fixos.
import subprocess  # nosec B404

import pytest
from weasyprint.urls import FatalURLFetchingError

from sar.modulo_05_emissao import pdf
from sar.modulo_05_emissao.contrato import Modelo
from sar.modulo_05_emissao.ficha import Secao
from sar.modulo_05_emissao.preenchimento import preencher
from sar.modulo_05_emissao.variaveis import FICTICIOS, nomes
from testes.apoio.modelos import EXTERNO_INERTE, conversor_no_ar, inicial, montar, partes, texto_do_pdf

pytestmark = pytest.mark.integracao

HOSTIL = "{{ cpf }} {% for x in y %}<b>negrito</b> & Cia {# fim #}"
COMUNS = {nome: "" for nome in nomes(Modelo.CATETER)} | {"clinica_nome": "Clínica"}


@pytest.mark.requisito("DD-42", "CT-EMI-02")
def test_valor_com_chaves_e_marcacao_sai_literal_no_pdf_do_modelo() -> None:
    conversor = conversor_no_ar()
    valores = COMUNS | {"nome": HOSTIL}
    texto = texto_do_pdf(conversor.para_pdf(preencher(inicial(Modelo.CATETER), valores, {"logotipo": None})))
    assert "{{ CPF }} {% FOR X IN Y %}<B>NEGRITO</B> & CIA {# FIM #}" in texto  # o modelo põe o nome em maiúsculas


@pytest.mark.requisito("DD-106", "CT-EMI-02")
def test_valor_com_chaves_e_marcacao_sai_literal_no_leiaute_fixo() -> None:
    conteudo = pdf.html("ficha.html", {
        "titulo": "Ficha", "logotipo": None, "clinica_nome": HOSTIL, "clinica_endereco": "Rua A", "clinica_cep": "",
        "clinica_municipio": "Jataí", "clinica_uf": "GO", "clinica_telefone": "", "data_extenso": "Jataí",
        "codigo_integridade": "<i>x</i>", "secoes": [Secao("Identificação", (("Nome", HOSTIL),))],
    })  # fmt: skip
    assert "<b>negrito" not in conteudo and "&lt;b&gt;negrito" in conteudo
    texto = texto_do_pdf(pdf.para_pdf(conteudo))
    assert "{{ cpf }} {% for x in y %}<b>negrito</b> & Cia {# fim #}" in texto and "<i>x</i>" in texto


@pytest.mark.requisito("DD-46", "CT-EMI-03")
def test_leiaute_fixo_nao_busca_endereco_externo() -> None:
    with pytest.raises(FatalURLFetchingError):  # para a geração; nada é buscado
        pdf.para_pdf(f'<html><body><img src="{EXTERNO_INERTE}/rastreio.png"></body></html>')


def _conteiner_do_conversor() -> str:
    if shutil.which("docker") is None:
        pytest.skip("docker ausente nesta máquina")
    nome = os.environ.get("SAR_CONVERSOR_CONTEINER")
    if nome:
        return nome
    listados = subprocess.run(  # nosec B603 B607
        ["docker", "ps", "--filter", "name=conversor", "--format", "{{.Names}}"],
        capture_output=True, text=True, check=False,
    ).stdout.split()  # fmt: skip
    candidatos = [n for n in listados if "ponte" not in n]
    if not candidatos:
        pytest.skip("conversor fora do ar (docker compose up -d conversor conversor-ponte)")
    return candidatos[0]


@pytest.mark.requisito("DD-46", "DD-104", "CT-EMI-03")
def test_conversor_nao_tem_saida_para_fora() -> None:
    """Do próprio contêiner do conversor, qualquer conexão de fora da rede interna falha."""
    conteiner = _conteiner_do_conversor()
    for destino in ("http://1.1.1.1", "https://www.google.com", EXTERNO_INERTE):
        resultado = subprocess.run(  # noqa: S603 # nosec B603 B607
            ["docker", "exec", conteiner, "curl", "-s", "-m", "5", "-o", "/dev/null", "-w", "%{http_code}", destino],
            capture_output=True, text=True, check=False, timeout=30,
        )  # fmt: skip
        assert resultado.returncode != 0 and resultado.stdout in ("", "000"), destino


@pytest.mark.requisito("DD-46", "CT-EMI-03")
def test_modelo_com_imagem_externa_forcado_ao_conversor_sai_sem_buscar() -> None:
    """Mesmo se um modelo com vínculo externo passasse da validação, o conversor converte sem buscar nada."""
    conteudo = partes(inicial(Modelo.CATETER))
    relacoes = conteudo["word/_rels/document.xml.rels"].decode()
    externa = (
        '<Relationship Id="rIdExterna" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        f'image" Target="{EXTERNO_INERTE}/rastreio.png" TargetMode="External"/>'
    )
    conteudo["word/_rels/document.xml.rels"] = relacoes.replace(
        "</Relationships>", externa + "</Relationships>"
    ).encode()
    valores = {n: FICTICIOS.get(n, "") for n in nomes(Modelo.CATETER) if n != "logotipo"}
    docx = preencher(montar(conteudo), valores, {"logotipo": None})
    assert texto_do_pdf(conversor_no_ar().para_pdf(docx))
