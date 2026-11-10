"""Emissão de documentos com o banco e o conversor (DDS §9.1, RF-801 a RF-808, DD-42, DD-43, DD-106, RNF-903).

O relógio dos contextos é terça, 13/10/2026, às 10h; o paciente começa o tratamento em 01/10, na escala de segunda,
quarta e sexta do primeiro turno.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import date

import pytest
from PIL import Image
from sqlalchemy import Engine, text

from sar.modulo_01_acesso.servicos import ServicoAuditoria
from sar.modulo_03_operacao.leitura import ServicoLeituraOperacao
from sar.modulo_03_operacao.pendencias import FonteTermoAEmitir
from sar.modulo_05_emissao.contrato import Documento
from sar.modulo_05_emissao.emissao import EmissoesRegistradasSQL, ServicoEmissao
from sar.modulo_06_configuracao.contrato import DadosInstitucionais
from sar.modulo_06_configuracao.servicos import ServicoReferencias
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado, ConfirmacaoNecessaria, NaoEncontrado, RegraViolada
from testes.apoio.cadastro import INICIO, dados_completos, pessoa
from testes.apoio.fabrica import Fabrica
from testes.apoio.modelos import conversor_no_ar, texto_do_pdf
from testes.apoio.operacao import Operacao, contexto, montar

pytestmark = pytest.mark.integracao

SEG_1, TER_3 = 1, 6  # 1-seg e 3-ter (0002)
JATAI = "5211909"
CLINICA = DadosInstitucionais("Clínica Fictícia de Teste", "Rua das Flores, 100", "75803000", JATAI, "6436000000", None)


@dataclass
class FotosFalsas:
    """A LeituraDocumentos só com a foto: o cofre e a leitura da foto são testados no MOD-04."""

    fotos: dict[int, bytes] = field(default_factory=dict)

    def foto(self, contexto: Contexto, paciente_id: int) -> bytes | None:
        return self.fotos.get(paciente_id)


@dataclass
class Cenario:
    op: Operacao
    emissao: ServicoEmissao
    fotos: FotosFalsas
    ids: dict[str, int]
    paciente_id: int
    nome: str

    @property
    def recepcao(self) -> Contexto:
        return pessoa(self.ids)


@pytest.fixture
def cenario(
    operacao_zerada: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> Iterator[Cenario]:
    op = montar(engine_web)
    fotos = FotosFalsas()
    executar = op.cadastro.executar
    emissao = ServicoEmissao(executar, ServicoAuditoria(), ServicoReferencias(), op.cadastro.leitura,
                             op.cadastro.pacientes, ServicoLeituraOperacao(op.cadastro.leitura, op.parametros), fotos,
                             conversor_no_ar())  # fmt: skip
    admin = pessoa(operacao_zerada, "admin", Perfil.ADMINISTRACAO)
    op.cadastro.configuracao.alterar_institucional(admin, CLINICA)
    dados = dados_completos(fabrica)
    paciente_id = op.cadastro.pacientes.criar(pessoa(operacao_zerada), dados, INICIO)
    op.escalas.alocar(contexto(operacao_zerada, "enfermagem", Perfil.ENFERMAGEM), paciente_id, SEG_1, INICIO)
    yield Cenario(op, emissao, fotos, operacao_zerada, paciente_id, dados.nome or "")
    with engine_migracao.begin() as c:
        c.execute(text("DELETE FROM emissao_documento"))
        c.execute(text("DELETE FROM instituicao"))


def emissoes(engine: Engine) -> list[tuple[str, int, str | None, str]]:
    with engine.connect() as c:
        sql = "SELECT modelo, versao_modelo, referencia, competencia FROM emissao_documento ORDER BY id"
        return [tuple(linha) for linha in c.execute(text(sql))]  # type: ignore[misc]


def foto_jpeg() -> bytes:
    saida = io.BytesIO()
    Image.new("RGB", (300, 400), "#8899aa").save(saida, format="JPEG")
    return saida.getvalue()


@pytest.mark.requisito("RF-801", "RF-802", "RF-803", "DD-86", "RNF-206")
@pytest.mark.parametrize("documento", [Documento.CATETER, Documento.ALIMENTOS])
def test_documento_sai_preenchido_com_cabecalho_data_e_codigo(
    cenario: Cenario, engine_web: Engine, documento: Documento
) -> None:
    emitido = cenario.emissao.emitir(cenario.recepcao, documento, cenario.paciente_id)
    texto = texto_do_pdf(emitido.pdf).upper()
    assert cenario.nome.upper() in texto
    assert "CLÍNICA FICTÍCIA DE TESTE" in texto and "13 DE OUTUBRO DE 2026" in texto and "JATAÍ" in texto
    assert emitido.nome_arquivo == f"{documento.value.lower()}-2026-10-13.pdf"
    assert emissoes(engine_web) == [(documento.value, 0, None, "2026-10")]
    with engine_web.connect() as c:
        alteracoes = c.execute(text("SELECT alteracoes FROM auditoria WHERE operacao = 'emissao.documento.emitir'"))
        assert json.loads(alteracoes.scalar_one()) == {"modelo": [None, documento.value], "versao_modelo": [None, 0]}


@pytest.mark.requisito("RNF-903", "DD-43")
def test_cada_emissao_le_o_cadastro_atual(cenario: Cenario, fabrica: Fabrica) -> None:
    primeira = texto_do_pdf(cenario.emissao.emitir(cenario.recepcao, Documento.CATETER, cenario.paciente_id).pdf)
    ficha = cenario.op.cadastro.pacientes.ver_ficha(cenario.recepcao, cenario.paciente_id)
    novo_nome = fabrica.paciente().nome
    cenario.op.cadastro.pacientes.atualizar(cenario.recepcao, cenario.paciente_id, ficha.versao,
                                            replace(ficha.dados, nome=novo_nome))  # fmt: skip
    segunda = texto_do_pdf(cenario.emissao.emitir(cenario.recepcao, Documento.CATETER, cenario.paciente_id).pdf)
    assert cenario.nome.upper() in primeira and novo_nome.upper() in segunda and cenario.nome.upper() not in segunda


@pytest.mark.requisito("RF-804", "DD-75")
def test_declaracao_de_troca_com_as_duas_datas_e_os_dois_turnos(cenario: Cenario, engine_web: Engine) -> None:
    enfermeira = contexto(cenario.ids, "enfermagem", Perfil.ENFERMAGEM)
    troca = cenario.op.escalas.registrar_troca(enfermeira, cenario.paciente_id, date(2026, 10, 14),
                                               date(2026, 10, 15), TER_3)  # fmt: skip
    texto = texto_do_pdf(cenario.emissao.emitir(cenario.recepcao, Documento.TROCA, cenario.paciente_id, troca).pdf)
    assert "14/10/2026, turno: primeiro" in texto and "15/10/2026, terceiro turno" in texto
    assert emissoes(engine_web) == [("DOC-03", 0, f"troca:{troca}", "2026-10")]

    outro = cenario.op.cadastro.pacientes.criar(cenario.recepcao, dados_completos(Fabrica(99)), INICIO)
    with pytest.raises(NaoEncontrado):  # troca de outro paciente
        cenario.emissao.emitir(cenario.recepcao, Documento.TROCA, outro, troca)
    cenario.op.escalas.cancelar_troca(enfermeira, troca)
    with pytest.raises(NaoEncontrado):  # §9.1: só de troca registrada e não cancelada
        cenario.emissao.emitir(cenario.recepcao, Documento.TROCA, cenario.paciente_id, troca)


@pytest.mark.requisito("RF-805")
def test_termo_de_extra_avisa_a_segunda_emissao_no_mes(cenario: Cenario, engine_web: Engine) -> None:
    emitido = cenario.emissao.emitir(cenario.recepcao, Documento.EXTRA, cenario.paciente_id)
    assert "Turno: primeiro" in texto_do_pdf(emitido.pdf)
    with pytest.raises(ConfirmacaoNecessaria) as aviso:
        cenario.emissao.emitir(cenario.recepcao, Documento.EXTRA, cenario.paciente_id)
    assert aviso.value.codigo == "extra.emitido_no_mes" and aviso.value.dados == {"emissoes": 1}
    cenario.emissao.emitir(cenario.recepcao, Documento.EXTRA, cenario.paciente_id, confirmar_reemissao=True)
    assert [e[0] for e in emissoes(engine_web)] == ["DOC-07", "DOC-07"]


@pytest.mark.requisito("RF-808")
def test_cracha_exige_a_foto(cenario: Cenario, engine_web: Engine) -> None:
    with pytest.raises(RegraViolada) as erro:
        cenario.emissao.emitir_cracha(cenario.recepcao, cenario.paciente_id)
    assert erro.value.codigo == "cracha.sem_foto" and emissoes(engine_web) == []
    cenario.fotos.fotos[cenario.paciente_id] = foto_jpeg()
    emitido = cenario.emissao.emitir_cracha(cenario.recepcao, cenario.paciente_id)
    assert "DN:" in texto_do_pdf(emitido.pdf) and emissoes(engine_web) == [("CRACHA", 0, None, "2026-10")]


@pytest.mark.requisito("RF-801", "DD-106")
def test_ficha_em_lista_so_com_os_campos_preenchidos(cenario: Cenario, engine_web: Engine) -> None:
    emitido = cenario.emissao.emitir(cenario.recepcao, Documento.FICHA, cenario.paciente_id)
    texto = texto_do_pdf(emitido.pdf)
    ficha = cenario.op.cadastro.pacientes.ver_ficha(cenario.recepcao, cenario.paciente_id)
    cpf = ficha.dados.cpf or ""
    assert cenario.nome in texto and f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}" in texto
    assert "Período 1" in texto and "início em 01/10/2026" in texto
    assert "RG" not in texto and "Logradouro" not in texto  # vazios não aparecem
    assert "FICHA DE CADASTRO DO PACIENTE" in texto.upper() and "13 de outubro de 2026" in texto
    assert emissoes(engine_web) == [("DOC-01", 0, None, "2026-10")]


@pytest.mark.requisito("RF-802")
def test_sem_dados_institucionais_o_documento_nao_sai(cenario: Cenario, engine_migracao: Engine) -> None:
    with engine_migracao.begin() as c:
        c.execute(text("DELETE FROM instituicao"))
    for documento in (Documento.CATETER, Documento.FICHA):
        with pytest.raises(RegraViolada) as erro:
            cenario.emissao.emitir(cenario.recepcao, documento, cenario.paciente_id)
        assert erro.value.codigo == "instituicao.ausente"


@pytest.mark.requisito("RF-801", "RF-808")
@pytest.mark.parametrize(
    ("chave", "perfil"),
    [("admin", Perfil.VISUALIZADOR), ("ti", Perfil.TI), ("enfermagem", Perfil.ENFERMAGEM)],
)
def test_so_recepcao_e_administracao_emitem(cenario: Cenario, chave: str, perfil: Perfil) -> None:
    outro = pessoa(cenario.ids, chave, perfil)
    with pytest.raises(AcessoNegado):
        cenario.emissao.emitir(outro, Documento.CATETER, cenario.paciente_id)
    with pytest.raises(AcessoNegado):
        cenario.emissao.emitir_cracha(outro, cenario.paciente_id)


@pytest.mark.requisito("RF-801")
def test_paciente_inexistente_nao_e_encontrado(cenario: Cenario) -> None:
    with pytest.raises(NaoEncontrado):
        cenario.emissao.emitir(cenario.recepcao, Documento.CATETER, 999_999_999)


@pytest.mark.requisito("RF-809", "DD-02")
def test_pendencia_de_termo_mostra_se_ja_foi_emitido(cenario: Cenario) -> None:
    fonte = FonteTermoAEmitir(cenario.op.cadastro.leitura, EmissoesRegistradasSQL())
    enfermeira = contexto(cenario.ids, "enfermagem", Perfil.ENFERMAGEM)
    troca = cenario.op.escalas.registrar_troca(enfermeira, cenario.paciente_id, date(2026, 10, 14),
                                               date(2026, 10, 15), TER_3)  # fmt: skip

    def descricoes() -> list[str]:
        return [i.descricao for i in cenario.op.cadastro.executar(lambda uow: fonte.listar(uow, cenario.recepcao))]

    assert descricoes() == ["Declaração de troca de turno a emitir e assinar (14/10 para 15/10)"]
    cenario.emissao.emitir(cenario.recepcao, Documento.TROCA, cenario.paciente_id, troca)
    assert descricoes() == ["Declaração de troca de turno emitida, aguardando o documento assinado (14/10 para 15/10)"]
