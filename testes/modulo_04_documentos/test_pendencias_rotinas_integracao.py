"""Pendências (DDS §11.1, linhas 2, 14, 15, 16 e 18), leituras para outros módulos (§8.8) e rotinas do acervo
(DD-37, DD-41, P-19), com o banco."""

from __future__ import annotations

import io
import itertools
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pikepdf
import pytest
from sqlalchemy import Engine, text

from sar.composicao import montar_barramento, montar_executor
from sar.modulo_01_acesso.servicos import ServicoAuditoria
from sar.modulo_02_cadastro.contrato import DadosCobertura, TipoCobertura
from sar.modulo_02_cadastro.pendencias import ServicoChecklist
from sar.modulo_04_documentos.leitura import ServicoLeituraDocumentos
from sar.modulo_04_documentos.pendencias import (
    FonteAguardandoConferencia,
    FonteAssinaturasAntimalware,
    FonteChecklistFaltante,
    FonteDocumentoBloqueado,
    FonteElegiveisDescarte,
)
from sar.modulo_04_documentos.rotinas import RotinasDocumentos
from sar.modulo_06_configuracao.servicos import LeitorParametrosSQL
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.portas import FontePendencia, ItemPendencia, MarcoRetencao
from sar.nucleo.uow import UnidadeDeTrabalho
from testes.apoio import corpus
from testes.apoio.cadastro import AGORA, INICIO, Cadastro, dados_completos, pessoa
from testes.apoio.cadastro import montar as montar_cadastro
from testes.apoio.documentos import AntimalwareFalso, Documentos, montar
from testes.apoio.fabrica import Fabrica
from testes.apoio.relogio_controlado import RelogioControlado

pytestmark = pytest.mark.integracao


def pagina(semente: int) -> bytes:
    return corpus.em_formato(corpus.pagina_ficticia(semente), "PNG")


@dataclass
class MarcoFalso:
    marco_atual: MarcoRetencao

    def marco(self, uow: UnidadeDeTrabalho, paciente_id: int) -> MarcoRetencao:
        return self.marco_atual


class AntimalwareQueDetectaTudo(AntimalwareFalso):
    def varrer(self, dados: bytes) -> str | None:
        return "Teste-Revarredura"


@pytest.fixture
def docs(
    cadastro_zerado: dict[str, int], engine_web: Engine, engine_worker: Engine, tmp_path: Path, sem_tesseract: None
) -> Iterator[Documentos]:
    yield montar(engine_web, engine_worker, tmp_path, RelogioControlado(AGORA))


@pytest.fixture
def cadastro(engine_web: Engine) -> Cadastro:
    return montar_cadastro(engine_web)


def _listar(docs: Documentos, fonte: FontePendencia, contexto: Contexto) -> list[ItemPendencia]:
    return docs.executar(lambda uow: fonte.listar(uow, contexto))


def _contexto(usuarios: dict[str, int], perfil: Perfil, instante: datetime = AGORA) -> Contexto:
    chave = {Perfil.ADMINISTRACAO: "admin", Perfil.TI: "ti"}.get(perfil, "recepcao")
    return Contexto(usuarios[chave], perfil, None, "10.0.0.7", instante, "e" * 32)


# ------------------------------------------------------------------ pendências
@pytest.mark.requisito("RF-706", "RF-707")
def test_checklist_faltante_com_e_sem_convenio(
    docs: Documentos, cadastro: Cadastro, cadastro_zerado: dict[str, int], fabrica: Fabrica, engine_migracao: Engine
) -> None:
    ids = cadastro_zerado
    recepcao = pessoa(ids)
    sus = cadastro.pacientes.criar(recepcao, dados_completos(fabrica), INICIO)
    ipasgo = cadastro.configuracao.incluir_convenio(pessoa(ids, "admin", Perfil.ADMINISTRACAO), "Ipasgo")
    convenio = cadastro.pacientes.criar(recepcao, dados_completos(fabrica), INICIO,
                                        cobertura=DadosCobertura(TipoCobertura.CONVENIO, ipasgo, "123"))  # fmt: skip
    encerrado = cadastro.pacientes.criar(recepcao, dados_completos(fabrica), INICIO)
    with engine_migracao.begin() as c:
        c.execute(text("UPDATE periodo_tratamento SET evento_tipo = 'alta', evento_data = '2026-10-05'"
                       " WHERE paciente_id = :p"), {"p": encerrado})  # fmt: skip
    fonte = FonteChecklistFaltante(ServicoChecklist())
    itens = {i.paciente_id: i.descricao for i in _listar(docs, fonte, recepcao)}
    assert itens == {
        sus: "Falta: cartão do SUS, comprovante de endereço",
        convenio: "Falta: cartão do SUS, comprovante de endereço, cartão do convênio",
    }  # quem não está em tratamento fica de fora (§11.2)
    docs.incorporado(recepcao, sus, "cartao_sus", [pagina(1)])
    por_paciente = docs.executar(lambda uow: fonte.listar_por_pacientes(uow, recepcao, [sus]))
    assert [i.descricao for i in por_paciente] == ["Falta: comprovante de endereço"]
    assert _listar(docs, fonte, _contexto(ids, Perfil.TI)) == []


@pytest.mark.requisito("RNF-625", "SEG-15")
def test_aguardando_conferencia_e_bloqueado(
    docs: Documentos, cadastro: Cadastro, cadastro_zerado: dict[str, int], fabrica: Fabrica, engine_migracao: Engine
) -> None:
    ids = cadastro_zerado
    recepcao = pessoa(ids)
    paciente = cadastro.pacientes.criar(recepcao, dados_completos(fabrica), INICIO)
    aberta = docs.capturar(recepcao, paciente, "cartao_sus", [pagina(1)])
    docs.worker.processar_proxima()
    [item] = _listar(docs, FonteAguardandoConferencia(), recepcao)
    assert (item.descricao, item.destino) == ("Cartão do SUS a conferir", f"/documentos/conferencia/{aberta.id}")
    assert _listar(docs, FonteAguardandoConferencia(), _contexto(ids, Perfil.TI)) == []
    documento = docs.ingestao.incorporar(recepcao, aberta.id)
    assert _listar(docs, FonteAguardandoConferencia(), recepcao) == []
    with engine_migracao.begin() as c:
        c.execute(text("UPDATE documento SET bloqueado_em = NOW(6), bloqueio_motivo = 'rescan'"))
    [da_administracao] = _listar(docs, FonteDocumentoBloqueado(), _contexto(ids, Perfil.ADMINISTRACAO))
    assert da_administracao.paciente_id == paciente
    [do_ti] = _listar(docs, FonteDocumentoBloqueado(), _contexto(ids, Perfil.TI))
    assert do_ti.paciente_id is None and do_ti.identificador_interno == documento  # só o identificador (RNF-625)
    assert _listar(docs, FonteDocumentoBloqueado(), recepcao) == []


@pytest.mark.requisito("DD-01", "DD-04")
def test_elegiveis_ao_descarte(
    docs: Documentos, cadastro: Cadastro, cadastro_zerado: dict[str, int], fabrica: Fabrica
) -> None:
    ids = cadastro_zerado
    paciente = cadastro.pacientes.criar(pessoa(ids), dados_completos(fabrica), INICIO)
    docs.incorporado(pessoa(ids), paciente, "cartao_sus", [pagina(1)])
    marco = MarcoFalso(MarcoRetencao(em_tratamento=False, ultimo_encerramento=date(2026, 10, 1)))
    fonte = FonteElegiveisDescarte(marco)
    assert _listar(docs, fonte, _contexto(ids, Perfil.ADMINISTRACAO)) == []
    [item] = _listar(docs, fonte, _contexto(ids, Perfil.ADMINISTRACAO, datetime(2046, 10, 14, 12, tzinfo=UTC)))
    assert item.descricao == "Retenção vencida em 13/10/2046: descarte possível"
    assert _listar(docs, fonte, _contexto(ids, Perfil.RECEPCAO, datetime(2047, 1, 1, tzinfo=UTC))) == []


@pytest.mark.requisito("SEG-21", "DD-97")
def test_assinaturas_do_antimalware(docs: Documentos, cadastro_zerado: dict[str, int]) -> None:
    antimalware = AntimalwareFalso()
    fonte = FonteAssinaturasAntimalware(antimalware, LeitorParametrosSQL(docs.executar))
    ti = _contexto(cadastro_zerado, Perfil.TI)
    assert _listar(docs, fonte, ti) == []
    antimalware.assinaturas_em = AGORA - timedelta(hours=49)
    [vencida] = _listar(docs, fonte, ti)
    assert vencida.descricao == "Assinaturas do antimalware de 11/10/2026 09:00"
    antimalware.fora_do_ar = True
    [fora] = _listar(docs, fonte, ti)
    assert fora.descricao.startswith("Antimalware sem resposta")
    assert _listar(docs, fonte, _contexto(cadastro_zerado, Perfil.ADMINISTRACAO)) == []


# ------------------------------------------------------------------ leituras para outros módulos
@pytest.mark.requisito("RF-1009", "RF-710", "RF-711")
def test_foto_e_copia_ao_titular(
    docs: Documentos, cadastro: Cadastro, cadastro_zerado: dict[str, int], fabrica: Fabrica, engine_migracao: Engine
) -> None:
    contexto = pessoa(cadastro_zerado)
    paciente = cadastro.pacientes.criar(contexto, dados_completos(fabrica), INICIO)
    leitura = ServicoLeituraDocumentos(
        docs.executar, ServicoAuditoria(), docs.cofre, MarcoFalso(MarcoRetencao(True, None))
    )
    assert leitura.foto(contexto, paciente) is None
    docs.incorporado(contexto, paciente, "cartao_sus", [pagina(1), pagina(2)])
    docs.incorporado(contexto, paciente, "foto_paciente", [corpus.foto_com_exif()], origem="webcam")
    foto = leitura.foto(contexto, paciente)
    assert foto is not None and foto.startswith(b"\xff\xd8\xff")
    copia = leitura.copia_ao_titular(contexto, paciente)
    assert len(pikepdf.open(io.BytesIO(copia)).pages) == 3
    assert docs.executar(lambda uow: leitura.tipos_presentes(uow, [paciente])) == {
        paciente: {"cartao_sus", "foto_paciente"}
    }
    with engine_migracao.connect() as c:
        vistas = c.execute(text("SELECT COUNT(*) FROM auditoria WHERE operacao = 'documento.ver'")).scalar_one()
    assert vistas == 3  # a foto e, na cópia, os dois documentos


# ------------------------------------------------------------------ rotinas
def _rotinas(
    engine_worker: Engine, docs: Documentos, antimalware: AntimalwareFalso, **opcoes: object
) -> RotinasDocumentos:
    executar = montar_executor(engine_worker, montar_barramento(docs.relogio))
    return RotinasDocumentos(executar, ServicoAuditoria(), docs.cofre, antimalware, docs.relogio, **opcoes)  # type: ignore[arg-type]


@pytest.mark.requisito("SEG-22", "DD-41", "P-19", "DD-64")
def test_revarredura_bloqueia_e_retoma_pelo_cursor(
    docs: Documentos, cadastro: Cadastro, cadastro_zerado: dict[str, int], fabrica: Fabrica, engine_worker: Engine
) -> None:
    contexto = pessoa(cadastro_zerado)
    paciente = cadastro.pacientes.criar(contexto, dados_completos(fabrica), INICIO)
    criados = sorted(docs.incorporado(contexto, paciente, "declaracao_troca", [pagina(n)]) for n in range(3))
    relogio = itertools.count()  # cada consulta ao relógio avança um "segundo"
    rotinas = _rotinas(engine_worker, docs, AntimalwareQueDetectaTudo(), agora_monotonico=lambda: float(next(relogio)))
    parcial = rotinas.revarrer(segundos=2.5)  # dá tempo de dois documentos
    assert parcial.verificados == 2 and parcial.cursor == criados[1]
    resto = rotinas.revarrer(depois_de=parcial.cursor)
    assert resto.verificados == 1 and resto.cursor is None
    assert sorted(parcial.bloqueados + resto.bloqueados) == criados
    assert rotinas.revarrer().bloqueados == ()  # o que já está bloqueado não é varrido de novo


@pytest.mark.requisito("SEG-15", "DD-41", "P-19", "DD-38")
def test_conferencia_de_hash_bloqueia_e_libera_apos_restauracao(
    docs: Documentos, cadastro: Cadastro, cadastro_zerado: dict[str, int], fabrica: Fabrica, engine_worker: Engine,
    engine_migracao: Engine, tmp_path: Path,
) -> None:  # fmt: skip
    contexto = pessoa(cadastro_zerado)
    paciente = cadastro.pacientes.criar(contexto, dados_completos(fabrica), INICIO)
    documento = docs.incorporado(contexto, paciente, "cartao_sus", [pagina(1)])
    with engine_migracao.connect() as c:
        nome = c.execute(
            text("SELECT arquivo FROM documento WHERE id = :d"), {"d": bytes.fromhex(documento)}
        ).scalar_one()
    caminho = tmp_path / "cofre" / nome[:2] / nome
    original = caminho.read_bytes()
    caminho.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    rotinas = _rotinas(engine_worker, docs, AntimalwareFalso())
    assert rotinas.verificar_hashes().bloqueados == (documento,)
    caminho.write_bytes(original)  # o TI restaurou do backup
    assert rotinas.verificar_hashes().desbloqueados == (documento,)
    assert docs.documentos.pagina(contexto, documento, 1).conteudo


@pytest.mark.requisito("DD-37", "R-41")
def test_orfaos_antigos_removidos_e_recentes_preservados(
    docs: Documentos, cadastro: Cadastro, cadastro_zerado: dict[str, int], fabrica: Fabrica, engine_worker: Engine,
    tmp_path: Path,
) -> None:  # fmt: skip
    contexto = pessoa(cadastro_zerado)
    paciente = cadastro.pacientes.criar(contexto, dados_completos(fabrica), INICIO)
    documento = docs.incorporado(contexto, paciente, "cartao_sus", [pagina(1)])
    antigo = tmp_path / "cofre" / "ab" / "abcdef-orfao"
    recente = tmp_path / "cofre" / "cd" / "cdef-em-andamento"
    for arquivo in (antigo, recente):
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_bytes(b"cifrado qualquer")
    duas_horas = time.time() - 7200
    os.utime(antigo, (duas_horas, duas_horas))
    assert _rotinas(engine_worker, docs, AntimalwareFalso()).remover_orfaos() == 1
    assert not antigo.exists() and recente.exists()
    assert docs.documentos.pagina(contexto, documento, 1).conteudo  # o conhecido ficou
