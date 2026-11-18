"""Leitura das planilhas sintéticas (PT §5.3) pelo extrator, sem banco."""

from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path

import pytest
import xlsxwriter
from openpyxl import load_workbook

from sar.modulo_10_carga import extrator, regras
from sar.nucleo.erros import RegraViolada
from testes.apoio import planilhas
from testes.apoio.fabrica import Fabrica


@pytest.mark.requisito("RF-1101", "RF-1102", "RF-1103", "AD-22", "ND-56")
def test_le_as_tres_planilhas_inteiras(fabrica: Fabrica, tmp_path: Path) -> None:
    sinteticas = planilhas.gerar(fabrica)
    lidas = extrator.ler(sinteticas.gravar(tmp_path))
    titulo, *fichas = lidas.p1  # o título no topo da P1 é um bloco a mais, que não é ficha
    assert regras.interpretar_p1(titulo).excecao == regras.SEM_FICHA
    assert [b.numero_linha for b in fichas] == [f.linha for f in sinteticas.fichas]
    assert len(lidas.p4) == sinteticas.linhas_p4  # o "2009" solto e o cabeçalho não contam
    assert len(lidas.p3) == sinteticas.linhas_p3  # anos, sentinelas e linhas vazias não contam
    assert {linha.ano for linha in lidas.p3} == {2018, 2019, 2024}


@pytest.mark.requisito("RNF-103", "DD-114", "CT-MIG-01")
def test_cada_defeito_cai_onde_deve_no_planejamento(fabrica: Fabrica, tmp_path: Path) -> None:
    sinteticas = planilhas.gerar(fabrica)
    lidas = extrator.ler(sinteticas.gravar(tmp_path))
    plano = regras.planejar(lidas.p1, lidas.p4, lidas.p3, date(2026, 11, 11))
    titulo, *itens = plano.itens
    assert titulo.excecao == regras.SEM_FICHA
    for ficha, item in zip(sinteticas.fichas, itens, strict=True):
        esperado, _ = planilhas.DEFEITOS.get(ficha.defeito or "", (planilhas.IMPORTADO, ()))
        if esperado in ("p1.rotulo_desconhecido", "P-03.minimo", "evento_saida"):  # as que a planilha já decide
            assert item.excecao == esperado, ficha.defeito
    assert plano.contagens_p4["sem_prontuario"] == 1
    assert plano.contagens_p3["casadas"] == sinteticas.casadas_p3
    assert plano.cid_descartados >= 1


def test_planilha_ausente_e_recusada_sem_dizer_o_conteudo(tmp_path: Path) -> None:
    with pytest.raises(RegraViolada) as erro:
        extrator.ler(tmp_path)
    assert (erro.value.codigo, erro.value.detalhe) == ("carga.planilha_ausente", {"planilha": "p1"})


def test_arquivo_que_nao_e_planilha_e_recusado(fabrica: Fabrica, tmp_path: Path) -> None:
    planilhas.gerar(fabrica).gravar(tmp_path)
    (tmp_path / extrator.ARQUIVOS["p4"]).write_bytes(b"isto nao e um xlsx")
    with pytest.raises(RegraViolada) as erro:
        extrator.ler(tmp_path)
    assert erro.value.codigo == "carga.planilha_ilegivel"


class LivroSemAbas:
    """O que o OpenPyXL devolve quando descarta a única aba de definição inválida: um livro vazio."""

    worksheets: list[object] = []  # noqa: RUF012

    def close(self) -> None:
        pass


@pytest.mark.requisito("RNF-103", "DD-65")
def test_planilha_que_abre_sem_aba_e_recusada_pelo_nome(
    fabrica: Fabrica, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Visto no uso (17/11/2026): a P4 convertida de .xls abria sem aba, e a carga quebrava com IndexError."""
    planilhas.gerar(fabrica).gravar(tmp_path)
    original = extrator.load_workbook

    def carregar(caminho: Path, **opcoes: object) -> object:
        return LivroSemAbas() if Path(caminho).name == extrator.ARQUIVOS["p4"] else original(caminho, **opcoes)

    monkeypatch.setattr(extrator, "load_workbook", carregar)
    with pytest.raises(RegraViolada) as erro:
        extrator.ler(tmp_path)
    assert (erro.value.codigo, erro.value.detalhe) == ("carga.planilha_sem_aba", {"planilha": "p4"})


def livro_com(*abas: tuple[str, list[tuple[str, str]], bool]) -> bytes:
    """Abas (nome, linhas de rótulo e valor, oculta). A primeira é a ativa e não pode ser oculta."""
    saida = io.BytesIO()
    livro = xlsxwriter.Workbook(saida, {"in_memory": True})
    for nome, linhas, oculta in abas:
        folha = livro.add_worksheet(nome)
        for i, (rotulo, valor) in enumerate(linhas):
            folha.write_string(i, 0, rotulo)
            folha.write_string(i, 1, valor)
        if oculta:
            folha.hide()
    livro.close()
    return saida.getvalue()


FICHA = [("PACIENTE:", "ANA FICTICIA Nº PT: 1"), ("NOME DA MÃE:", "MAE FICTICIA"), ("INICIO TRATAM:", "01/02/2020")]
TABELA = [("PACIENTE", "NOME DA MÃE"), ("ANA FICTICIA", "MAE FICTICIA")]


@pytest.mark.requisito("RF-1101", "DD-114")
@pytest.mark.parametrize(
    ("abas", "esperado"),
    [
        ((("Tabela", TABELA, False), ("A", FICHA, False), ("Oculta", FICHA, True)), 1),
        ((("Tabela", TABELA, False),), "carga.p1_sem_fichas"),
        ((("A", FICHA, False), ("C", FICHA, False)), "carga.p1_varias_abas"),
    ],
    ids=["a-visivel-com-fichas", "nenhuma-com-fichas", "duas-com-fichas"],
)
def test_p1_e_a_unica_aba_visivel_com_fichas(abas: tuple[tuple[str, list[tuple[str, str]], bool], ...],
                                             esperado: int | str) -> None:  # fmt: skip
    """Visto no uso (17/11/2026): a P1 real tem a aba original, uma tentativa de tabela e duas abas ocultas."""
    livro = load_workbook(io.BytesIO(livro_com(*abas)), read_only=True, data_only=True)
    try:
        if isinstance(esperado, int):
            assert len(extrator.blocos_p1(iter(extrator.aba_de_fichas(livro)))) == esperado
        else:
            with pytest.raises(RegraViolada) as erro:
                extrator.aba_de_fichas(livro)
            assert (erro.value.codigo, erro.value.detalhe) == (esperado, {"planilha": "p1"})
    finally:
        livro.close()


def para_strict(xlsx: bytes) -> bytes:
    """O mesmo arquivo no formato "Planilha Strict Open XML" do Excel: só os espaços de nomes mudam."""
    origem = zipfile.ZipFile(io.BytesIO(xlsx))
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w") as destino:
        for item in origem.infolist():
            dados = origem.read(item)
            if item.filename == "xl/workbook.xml":
                dados = dados.replace(b"http://schemas.openxmlformats.org/officeDocument/2006/relationships",
                                      b"http://purl.oclc.org/ooxml/officeDocument/relationships")  # fmt: skip
            destino.writestr(item, dados)
    return saida.getvalue()


@pytest.mark.requisito("DD-65", "AD-22")
def test_planilha_strict_e_recusada_com_o_que_fazer(fabrica: Fabrica, tmp_path: Path) -> None:
    """Visto no uso (17/11/2026): a P4 salva pelo Excel como Strict abria sem aba nenhuma."""
    sinteticas = planilhas.gerar(fabrica)
    sinteticas.gravar(tmp_path)
    (tmp_path / extrator.ARQUIVOS["p4"]).write_bytes(para_strict(sinteticas.p4))
    assert extrator.formato_strict(tmp_path / extrator.ARQUIVOS["p4"])
    assert not extrator.formato_strict(tmp_path / extrator.ARQUIVOS["p1"])
    with pytest.raises(RegraViolada) as erro:
        extrator.ler(tmp_path)
    assert (erro.value.codigo, erro.value.detalhe) == ("carga.planilha_strict", {"planilha": "p4"})


@pytest.mark.requisito("RF-1101", "RNF-103", "DD-114")
def test_ficha_comeca_no_paciente_depois_da_faixa_preta() -> None:
    """Visto no uso (18/11/2026): fichas sem prontuário, "PACIENTE:" copiado na linha da cidade e linha vazia dentro
    da ficha. Só a faixa preta seguida do PACIENTE começa outra ficha."""
    linhas: list[extrator.LinhaP1] = [
        (1, ("ENDEREÇOS E TELEFONES DOS PACIENTES", None)),  # título: bloco próprio, sem ficha
        (2, (None, None)),
        (3, ("PACIENTE:", "ANA FICTICIA")),  # sem prontuário
        (4, ("ENDEREÇO:", "RUA A")),
        (5, ("PACIENTE:", "JATAI -GO")),  # a cidade com o rótulo copiado
        (6, (None, None)),  # linha vazia no meio da ficha
        (7, ("INICIO TRATAM:", "01/02/2020")),
        (8, None),
        (9, (None, None)),
        (10, ("PACIENTE :", "BIA FICTICIA")),
        (11, ("NOME DA MÃE:", "MAE FICTICIA")),
        (12, None),
        (13, ("TELEFONE:", "(64) 3631-0000")),  # faixa seguida de outra coisa: continua a ficha
        (14, None),
        (15, ("PACIENTE:", "CIA FICTICIA")),
    ]
    blocos = extrator.blocos_p1(iter(linhas))
    assert [b.numero_linha for b in blocos] == [1, 3, 10, 15]
    assert [c.linha for c in blocos[1].celulas] == [3, 4, 5, 7]
    assert [c.linha for c in blocos[2].celulas] == [10, 11, 13]


@pytest.mark.requisito("RF-1101", "RNF-103")
def test_faixa_preta_separa_as_fichas_mesmo_com_texto_escondido(fabrica: Fabrica, tmp_path: Path) -> None:
    """Visto no uso (18/11/2026): as fichas da P1 real são separadas por uma linha pintada de preto."""
    sinteticas = planilhas.gerar(fabrica)
    lidas = extrator.ler(sinteticas.gravar(tmp_path))
    _, *fichas = lidas.p1
    assert [b.numero_linha for b in fichas] == [f.linha for f in sinteticas.fichas]
    assert not any("ESCONDIDA" in str(c.valor) for b in lidas.p1 for c in b.celulas)
