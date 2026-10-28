"""Consulta, revinculação, descarte, desbloqueio e anulação (DDS §8.6) com o banco: CT-DOC-04 (leitura), CT-DOC-10;
DD-04, DD-36, DD-38, P-17, P-19, RF-710, RF-713, DEC-61."""

from __future__ import annotations

import io
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import Engine, text

from sar.modulo_01_acesso.servicos import ServicoAuditoria
from sar.modulo_04_documentos.contrato import EstadoIngestao
from sar.modulo_04_documentos.executores import (
    ExecutorDesbloquearDocumento,
    ExecutorDescartarDocumento,
    ParticipanteAnulacaoDocumentos,
)
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado, IntegridadeViolada, RegraViolada
from sar.nucleo.portas import Autorizacao, MarcoRetencao
from sar.nucleo.uow import UnidadeDeTrabalho
from testes.apoio import corpus
from testes.apoio.cadastro import AGORA, INICIO, dados_completos, pessoa
from testes.apoio.cadastro import montar as montar_cadastro
from testes.apoio.documentos import Documentos, montar
from testes.apoio.fabrica import Fabrica
from testes.apoio.relogio_controlado import RelogioControlado

pytestmark = pytest.mark.integracao


def autorizacao(usuarios: dict[str, int]) -> Autorizacao:
    return Autorizacao("a" * 32, usuarios["admin"], "Conferido pela administração")


def pagina(semente: int) -> bytes:
    """Páginas diferentes entre si: o hash do documento é único (§8.7)."""
    return corpus.em_formato(corpus.pagina_ficticia(semente), "PNG")


@dataclass
class MarcoFalso:
    marco_atual: MarcoRetencao

    def marco(self, uow: UnidadeDeTrabalho, paciente_id: int) -> MarcoRetencao:
        return self.marco_atual


@pytest.fixture
def docs(
    cadastro_zerado: dict[str, int], engine_web: Engine, engine_worker: Engine, tmp_path: Path, sem_tesseract: None
) -> Iterator[Documentos]:
    yield montar(engine_web, engine_worker, tmp_path, RelogioControlado(AGORA))


@pytest.fixture
def pacientes(cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica) -> tuple[int, int]:
    servico = montar_cadastro(engine_web).pacientes
    contexto = pessoa(cadastro_zerado)
    return (servico.criar(contexto, dados_completos(fabrica), INICIO),
            servico.criar(contexto, dados_completos(fabrica), INICIO))  # fmt: skip


def _contar(engine: Engine, sql: str, **parametros: object) -> int:
    with engine.connect() as c:
        return int(c.execute(text(sql), parametros).scalar_one())


def _arquivo(engine: Engine, documento_id: str) -> Path | None:
    with engine.connect() as c:
        arquivo = c.execute(text("SELECT arquivo FROM documento WHERE id = :d"), {"d": bytes.fromhex(documento_id)})
        nome = arquivo.scalar_one()
    return Path(nome[:2]) / nome


# ------------------------------------------------------------------ consulta
@pytest.mark.requisito("DD-36", "RF-708", "RNF-626", "RF-710")
def test_lista_versao_vigente_e_historico(
    docs: Documentos, pacientes: tuple[int, int], cadastro_zerado: dict[str, int], engine_migracao: Engine
) -> None:
    contexto, paciente = pessoa(cadastro_zerado), pacientes[0]
    v1 = docs.incorporado(contexto, paciente, "cartao_sus", [pagina(1)])
    v2 = docs.incorporado(contexto, paciente, "cartao_sus", [pagina(2)], substitui_id=v1, motivo="Ilegível")
    t1 = docs.incorporado(contexto, paciente, "declaracao_troca", [pagina(3)])
    t2 = docs.incorporado(contexto, paciente, "declaracao_troca", [pagina(4)])  # outro termo, independente
    lista = docs.documentos.listar(pessoa(cadastro_zerado, "visualizador", Perfil.VISUALIZADOR), paciente)
    resumo = {(d.vigente.id, tuple(a.id for a in d.anteriores)) for d in lista}
    assert resumo == {(v2, (v1,)), (t1, ()), (t2, ())}
    assert _contar(engine_migracao, "SELECT COUNT(*) FROM auditoria WHERE operacao = 'documento.listar'") == 1
    for perfil in (Perfil.ENFERMAGEM, Perfil.TI):  # DEC-55, RF-1004
        with pytest.raises(AcessoNegado):
            docs.documentos.listar(pessoa(cadastro_zerado, perfil=perfil), paciente)


@pytest.mark.requisito("SEG-19", "RF-710", "RNF-606", "P-17")
def test_paginas_como_imagem_e_download_so_da_administracao(
    docs: Documentos, pacientes: tuple[int, int], cadastro_zerado: dict[str, int], engine_migracao: Engine
) -> None:
    contexto = pessoa(cadastro_zerado)
    documento = docs.incorporado(contexto, pacientes[0], "cartao_sus", [pagina(1), pagina(2)])
    primeira = docs.documentos.pagina(contexto, documento, 1)
    assert primeira.tipo_midia == "image/jpeg" and Image.open(io.BytesIO(primeira.conteudo)).mode == "L"
    assert docs.documentos.pagina(contexto, documento, 2).conteudo != primeira.conteudo
    assert _contar(engine_migracao, "SELECT COUNT(*) FROM auditoria WHERE operacao = 'documento.ver'") == 2
    with pytest.raises(AcessoNegado):
        docs.documentos.baixar(contexto, documento)
    conteudo, midia = docs.documentos.baixar(pessoa(cadastro_zerado, "admin", Perfil.ADMINISTRACAO), documento)
    assert midia == "application/pdf" and conteudo.startswith(b"%PDF-")
    foto = docs.incorporado(contexto, pacientes[0], "foto_paciente", [corpus.foto_com_exif()], origem="webcam")
    assert Image.open(io.BytesIO(docs.documentos.pagina(contexto, foto, 1).conteudo)).mode == "RGB"


@pytest.mark.requisito("CT-DOC-04", "DD-38", "P-19", "SEG-15")
def test_arquivo_alterado_bloqueia_o_documento(
    docs: Documentos, pacientes: tuple[int, int], cadastro_zerado: dict[str, int], engine_migracao: Engine,
    tmp_path: Path,
) -> None:  # fmt: skip
    contexto = pessoa(cadastro_zerado)
    documento = docs.incorporado(contexto, pacientes[0], "cartao_sus", [pagina(1)])
    caminho = tmp_path / "cofre" / _arquivo(engine_migracao, documento)  # type: ignore[operator]
    bruto = bytearray(caminho.read_bytes())
    bruto[20] ^= 0xFF
    caminho.write_bytes(bytes(bruto))
    with pytest.raises(IntegridadeViolada):
        docs.documentos.pagina(contexto, documento, 1)
    motivo = _contar(engine_migracao, "SELECT COUNT(*) FROM documento WHERE bloqueio_motivo = 'hash_divergente'")
    assert motivo == 1  # o bloqueio ficou, mesmo com a leitura recusada
    with pytest.raises(RegraViolada) as erro:
        docs.documentos.pagina(contexto, documento, 1)
    assert erro.value.codigo == "documento.bloqueado"
    with pytest.raises(RegraViolada):  # hash divergente não se desbloqueia (P-19)
        docs.executar(lambda uow: ExecutorDesbloquearDocumento(ServicoAuditoria()).executar(
            uow, contexto, autorizacao(cadastro_zerado), {"documento_id": documento}))  # fmt: skip


@pytest.mark.requisito("P-19")
def test_desbloqueio_do_rescan_por_autorizacao(
    docs: Documentos, pacientes: tuple[int, int], cadastro_zerado: dict[str, int], engine_migracao: Engine
) -> None:
    contexto = pessoa(cadastro_zerado)
    documento = docs.incorporado(contexto, pacientes[0], "cartao_sus", [pagina(1)])
    with engine_migracao.begin() as c:
        c.execute(text("UPDATE documento SET bloqueado_em = NOW(6), bloqueio_motivo = 'rescan' WHERE id = :d"),
                  {"d": bytes.fromhex(documento)})  # fmt: skip
    with pytest.raises(RegraViolada):
        docs.documentos.pagina(contexto, documento, 1)
    executor = ExecutorDesbloquearDocumento(ServicoAuditoria())
    docs.executar(
        lambda uow: executor.executar(uow, contexto, autorizacao(cadastro_zerado), {"documento_id": documento})
    )
    assert docs.documentos.pagina(contexto, documento, 1).conteudo


# ------------------------------------------------------------------ revinculação
@pytest.mark.requisito("RF-713", "DD-36", "INV-06")
def test_revinculacao_leva_todas_as_versoes(
    docs: Documentos, pacientes: tuple[int, int], cadastro_zerado: dict[str, int], engine_migracao: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    contexto, errado, certo = pessoa(cadastro_zerado), *pacientes
    v1 = docs.incorporado(contexto, errado, "cartao_sus", [pagina(1)])
    v2 = docs.incorporado(contexto, errado, "cartao_sus", [pagina(2)], substitui_id=v1, motivo="Ilegível")
    for paciente, motivo, codigo in ((certo, " ", "revinculo.motivo"), (errado, "x", "revinculo.mesmo_paciente")):
        with pytest.raises(RegraViolada) as erro:
            docs.documentos.revincular(contexto, v2, paciente, motivo)
        assert erro.value.codigo == codigo
    docs.documentos.revincular(contexto, v1, certo, "Anexado ao paciente errado")
    assert {d.vigente.id for d in docs.documentos.listar(contexto, certo)} == {v2}
    assert docs.documentos.listar(contexto, errado) == []
    assert _contar(engine_migracao, "SELECT COUNT(*) FROM auditoria WHERE operacao = 'documento.revincular'"
                   " AND motivo = 'Anexado ao paciente errado'") == 2  # fmt: skip
    hashes = _contar(engine_migracao, "SELECT COUNT(DISTINCT hash_sha256) FROM documento")
    assert hashes == 2  # arquivo e hash intactos


@pytest.mark.requisito("RF-713")
def test_revinculacao_para_anulado_recusada(
    docs: Documentos, pacientes: tuple[int, int], cadastro_zerado: dict[str, int], engine_migracao: Engine
) -> None:
    contexto, origem, destino = pessoa(cadastro_zerado), *pacientes
    documento = docs.incorporado(contexto, origem, "cartao_sus", [pagina(1)])
    with engine_migracao.begin() as c:
        c.execute(text("UPDATE paciente SET anulado_em = NOW(6) WHERE id = :p"), {"p": destino})
    with pytest.raises(RegraViolada) as erro:
        docs.documentos.revincular(contexto, documento, destino, "motivo")
    assert erro.value.codigo == "paciente.anulado"


# ------------------------------------------------------------------ descarte (DD-04) e anulação (DEC-61)
@pytest.mark.requisito("CT-DOC-10", "DD-04", "INV-13", "RF-709", "DD-01")
def test_descarte_so_depois_do_prazo_destroi_chave_e_arquivo(
    docs: Documentos, pacientes: tuple[int, int], cadastro_zerado: dict[str, int], engine_migracao: Engine,
    tmp_path: Path,
) -> None:  # fmt: skip
    contexto = pessoa(cadastro_zerado)
    documento = docs.incorporado(contexto, pacientes[0], "cartao_sus", [pagina(1)])
    caminho = tmp_path / "cofre" / _arquivo(engine_migracao, documento)  # type: ignore[operator]
    marco = MarcoFalso(MarcoRetencao(em_tratamento=True, ultimo_encerramento=None))
    executor = ExecutorDescartarDocumento(ServicoAuditoria(), docs.cofre, marco)

    def em(instante: datetime) -> Contexto:
        return Contexto(contexto.usuario_id, Perfil.ADMINISTRACAO, None, "10.0.0.7", instante, "d" * 32)

    def descartar(autor: Contexto) -> None:
        docs.executar(
            lambda uow: executor.executar(uow, autor, autorizacao(cadastro_zerado), {"documento_id": documento})
        )

    daqui_a_30_anos = em(datetime(2056, 1, 1, 12, tzinfo=UTC))
    with pytest.raises(RegraViolada) as erro:  # em tratamento, não há prazo
        descartar(daqui_a_30_anos)
    assert erro.value.codigo == "retencao.vigente"
    marco.marco_atual = MarcoRetencao(em_tratamento=False, ultimo_encerramento=date(2026, 10, 1))
    with pytest.raises(RegraViolada):  # prazo em 13/10/2046 (o documento é o último registro)
        descartar(em(datetime(2046, 10, 12, 12, tzinfo=UTC)))
    descrito = docs.executar(lambda uow: executor.descrever(uow, {"documento_id": documento}))
    assert descrito == "Descartar Cartão do SUS (versão 1), prazo de retenção vencido em 13/10/2046"
    descartar(daqui_a_30_anos)
    assert not caminho.exists()
    with engine_migracao.connect() as c:
        chave, descartado, hash_ = c.execute(text("SELECT chave_cifrada, descartado_em, hash_sha256 FROM documento"
                                                  " WHERE id = :d"), {"d": bytes.fromhex(documento)}).one()  # fmt: skip
    assert chave is None and descartado is not None and len(hash_) == 64  # a linha fica como registro do descarte
    with pytest.raises(RegraViolada) as erro:
        docs.documentos.pagina(contexto, documento, 1)
    assert erro.value.codigo == "documento.descartado"
    with pytest.raises(RegraViolada):  # já descartado
        descartar(daqui_a_30_anos)


@pytest.mark.requisito("DEC-61", "CT-CAD-06")
def test_anulacao_descarta_documentos_e_cancela_ingestoes(
    docs: Documentos, pacientes: tuple[int, int], cadastro_zerado: dict[str, int], engine_migracao: Engine
) -> None:
    contexto, paciente = pessoa(cadastro_zerado), pacientes[0]
    docs.incorporado(contexto, paciente, "cartao_sus", [pagina(1)])
    docs.incorporado(contexto, paciente, "comprovante_endereco", [pagina(2)])
    docs.incorporado(contexto, pacientes[1], "cartao_sus", [pagina(3)])  # de outro paciente: fica
    em_andamento = docs.capturar(contexto, paciente, "cartao_sus", [pagina(4)])
    participante = ParticipanteAnulacaoDocumentos(ServicoAuditoria(), docs.cofre, docs.quarentena)
    impacto = docs.executar(lambda uow: participante.impacto(uow, paciente))
    assert impacto.contagens == {"documentos": 2} and not impacto.alcanca_mes_fechado
    docs.executar(lambda uow: participante.descartar(uow, contexto, paciente, autorizacao(cadastro_zerado)))
    assert _contar(engine_migracao, "SELECT COUNT(*) FROM documento WHERE chave_cifrada IS NULL") == 2
    assert docs.ingestao.situacao(contexto, em_andamento.id).estado is EstadoIngestao.CANCELADA
    assert docs.quarentena.ingestoes() == []
    assert docs.executar(lambda uow: participante.impacto(uow, paciente)).contagens == {}
