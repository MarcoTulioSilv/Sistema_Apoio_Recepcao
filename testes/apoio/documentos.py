"""Apoio dos testes do MOD-04: a ingestão pela web (sar_web) e o worker (sar_worker) sobre o mesmo banco, com as
pastas do teste, o relógio controlado e um antimalware falso (o real fica nos testes do clamd)."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine

from sar.composicao import montar_barramento, montar_executor
from sar.modulo_01_acesso.servicos import ServicoAuditoria
from sar.modulo_04_documentos.antimalware import AntimalwareIndisponivel, Versao
from sar.modulo_04_documentos.armazenamento import Cofre, Quarentena
from sar.modulo_04_documentos.contrato import IngestaoAberta
from sar.modulo_04_documentos.documentos import ServicoDocumentos
from sar.modulo_04_documentos.ingestao import ServicoIngestao
from sar.modulo_04_documentos.worker import ProcessadorIngestoes
from sar.modulo_06_configuracao.servicos import LeitorParametrosSQL
from sar.modulo_08_dados.cifra import CifraAesGcm
from sar.nucleo.contexto import Contexto
from sar.nucleo.uow import ExecutorDeOperacao
from testes.apoio import corpus
from testes.apoio.relogio_controlado import RelogioControlado

CIFRA = CifraAesGcm(bytes(range(32)))


@dataclass
class AntimalwareFalso:
    assinaturas_em: datetime = datetime(2026, 10, 13, 6, tzinfo=UTC)
    fora_do_ar: bool = False
    varridos: list[bytes] = field(default_factory=list)
    recargas: int = 0
    base_nova: datetime | None = None  # o que a recarga carrega; None: a base continua a mesma

    def versao(self) -> Versao:
        if self.fora_do_ar:
            raise AntimalwareIndisponivel("fora do ar")
        return Versao("ClamAV 1.5.4", 27800, self.assinaturas_em)

    def varrer(self, dados: bytes) -> str | None:
        if self.fora_do_ar:
            raise AntimalwareIndisponivel("fora do ar")
        self.varridos.append(dados)
        return "Eicar-Test-Signature" if dados.startswith(corpus.eicar()) else None

    def recarregar(self) -> None:
        if self.fora_do_ar:
            raise AntimalwareIndisponivel("fora do ar")
        self.recargas += 1
        if self.base_nova is not None:
            self.assinaturas_em = self.base_nova


@dataclass(frozen=True, slots=True)
class Documentos:
    ingestao: ServicoIngestao
    worker: ProcessadorIngestoes
    quarentena: Quarentena
    cofre: Cofre
    antimalware: AntimalwareFalso
    relogio: RelogioControlado
    documentos: ServicoDocumentos
    executar: ExecutorDeOperacao

    def capturar(self, contexto: Contexto, paciente_id: int, tipo: str, paginas: list[bytes],
                 origem: str = "scanner", **opcoes: str) -> IngestaoAberta:  # fmt: skip
        """Abre, envia as páginas e conclui, como o agente faz (§8.5)."""
        aberta = self.ingestao.abrir(contexto, paciente_id, tipo, origem, **opcoes)
        for numero, pagina in enumerate(paginas, start=1):
            self.ingestao.receber_pagina(aberta.id, aberta.token, numero, io.BytesIO(pagina))
        self.ingestao.concluir(aberta.id, aberta.token, len(paginas))
        return aberta

    def incorporado(self, contexto: Contexto, paciente_id: int, tipo: str, paginas: list[bytes],
                    origem: str = "scanner", **opcoes: str) -> str:  # fmt: skip
        """Captura, processa e incorpora; devolve o id do documento."""
        aberta = self.capturar(contexto, paciente_id, tipo, paginas, origem, **opcoes)
        assert self.worker.processar_proxima()
        return self.ingestao.incorporar(contexto, aberta.id)


def montar(engine_web: Engine, engine_worker: Engine, pasta: Path, relogio: RelogioControlado) -> Documentos:
    quarentena, cofre = Quarentena(pasta / "quarentena", CIFRA), Cofre(pasta / "cofre", CIFRA)
    antimalware = AntimalwareFalso()
    web = montar_executor(engine_web, montar_barramento(relogio))
    worker = montar_executor(engine_worker, montar_barramento(relogio))
    return Documentos(
        ServicoIngestao(web, ServicoAuditoria(), LeitorParametrosSQL(web), quarentena, cofre, CIFRA, relogio),
        ProcessadorIngestoes(
            worker, ServicoAuditoria(), LeitorParametrosSQL(worker), quarentena, antimalware, CIFRA, relogio
        ),
        quarentena,
        cofre,
        antimalware,
        relogio,
        ServicoDocumentos(web, ServicoAuditoria(), cofre),
        web,
    )
