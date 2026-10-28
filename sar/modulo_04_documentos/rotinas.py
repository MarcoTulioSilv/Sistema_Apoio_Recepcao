"""Rotinas do acervo (DD-41, DD-37, P-19), rodadas pelo worker; o agendamento na janela noturna chega com o MOD-09.

- Revarredura antimalware (SEG-22): cada documento decifrado em memória vai ao clamd; detecção bloqueia ("rescan").
- Conferência de hash (SEG-15): cada documento decifrado é conferido; divergência bloqueia ("hash_divergente"), e o
  bloqueio por hash cai sozinho quando o TI restaura o arquivo e o hash volta a conferir (P-19).
- Órfãos (DD-37): arquivo do cofre sem linha correspondente, ou temporário esquecido, é removido.

As duas primeiras andam por id, em lotes, e param no prazo dado: devolvem o cursor para continuar (DD-64). Só
identificadores vão à trilha e ao resultado (RNF-625).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from sar.modulo_01_acesso.contrato import AuditService
from sar.modulo_04_documentos.antimalware import Antimalware
from sar.modulo_04_documentos.armazenamento import Cofre
from sar.modulo_08_dados.interfaces.documentos import DocumentoGravado, RepositorioDocumentos
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import IntegridadeViolada
from sar.nucleo.portas import Relogio
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho

RESCAN = "documento.integridade.rescan"
VERIFICAR = "documento.integridade.verificar"
ORFAOS = "documento.ingestao.varrer_orfaos"
LOTE = 50
IDADE_MINIMA_ORFAO = 3600  # segundos: muito além de qualquer incorporação em andamento


@dataclass(frozen=True, slots=True)
class Resultado:
    verificados: int
    bloqueados: tuple[str, ...]  # ids dos documentos
    desbloqueados: tuple[str, ...]
    cursor: str | None  # None: acervo inteiro percorrido; senão, continuar depois deste id


class RotinasDocumentos:
    def __init__(
        self,
        executar: ExecutorDeOperacao,
        auditoria: AuditService,
        cofre: Cofre,
        antimalware: Antimalware,
        relogio: Relogio,
        agora_monotonico: Callable[[], float] = time.monotonic,
    ) -> None:
        self._executar = executar
        self._auditoria = auditoria
        self._cofre = cofre
        self._antimalware = antimalware
        self._relogio = relogio
        self._monotonico = agora_monotonico

    def _contexto(self, origem: str) -> Contexto:
        return Contexto.sistema(origem, self._relogio.agora())

    def _ler(self, documento: DocumentoGravado) -> bytes:
        return self._cofre.ler(documento.id, documento.arquivo, documento.chave_cifrada or b"", documento.nonce,
                               documento.hash_sha256)  # fmt: skip

    def _bloquear(self, operacao: str, documento: DocumentoGravado, motivo: str) -> None:
        contexto = self._contexto(operacao)

        def gravar(uow: UnidadeDeTrabalho) -> None:
            uow.repositorio(RepositorioDocumentos).bloquear(documento.id, contexto.instante, motivo)
            self._auditoria.registrar(uow, contexto, operacao, "documento", documento.id.hex(),
                                      {"bloqueio": (None, motivo)})  # fmt: skip

        self._executar(gravar)

    @staticmethod
    def _lote(cursor: bytes | None, uow: UnidadeDeTrabalho) -> list[DocumentoGravado]:
        return uow.repositorio(RepositorioDocumentos).acervo_depois_de(cursor, LOTE)

    def _percorrer(
        self, conferir: Callable[[DocumentoGravado], tuple[bool, bool]], depois_de: str | None, segundos: float | None
    ) -> Resultado:
        """`conferir` devolve (bloqueou, desbloqueou) para cada documento."""
        prazo = self._monotonico() + segundos if segundos is not None else None
        cursor = bytes.fromhex(depois_de) if depois_de else None
        verificados, bloqueados, desbloqueados = 0, list[str](), list[str]()
        while True:
            lote = self._executar(partial(self._lote, cursor))
            if not lote:
                return Resultado(verificados, tuple(bloqueados), tuple(desbloqueados), None)
            for documento in lote:
                if prazo is not None and self._monotonico() >= prazo:
                    marca = cursor.hex() if cursor is not None else None
                    return Resultado(verificados, tuple(bloqueados), tuple(desbloqueados), marca)
                bloqueou, desbloqueou = conferir(documento)
                verificados += 1
                if bloqueou:
                    bloqueados.append(documento.id.hex())
                if desbloqueou:
                    desbloqueados.append(documento.id.hex())
                cursor = documento.id

    # ---------------------------------------------------------------- revarredura (SEG-22)
    def revarrer(self, depois_de: str | None = None, segundos: float | None = None) -> Resultado:
        """AntimalwareIndisponivel interrompe: a rotina recomeça do cursor na próxima vez."""

        def conferir(documento: DocumentoGravado) -> tuple[bool, bool]:
            if documento.bloqueado_em is not None:
                return False, False
            try:
                conteudo = self._ler(documento)
            except IntegridadeViolada:
                self._bloquear(VERIFICAR, documento, "hash_divergente")
                return True, False
            if self._antimalware.varrer(conteudo) is None:
                return False, False
            self._bloquear(RESCAN, documento, "rescan")
            return True, False

        return self._percorrer(conferir, depois_de, segundos)

    # ---------------------------------------------------------------- conferência de hash (SEG-15)
    def verificar_hashes(self, depois_de: str | None = None, segundos: float | None = None) -> Resultado:
        def conferir(documento: DocumentoGravado) -> tuple[bool, bool]:
            try:
                self._ler(documento)
            except IntegridadeViolada:
                if documento.bloqueado_em is None:
                    self._bloquear(VERIFICAR, documento, "hash_divergente")
                    return True, False
                return False, False
            if documento.bloqueio_motivo != "hash_divergente":
                return False, False
            contexto = self._contexto(VERIFICAR)

            def liberar(uow: UnidadeDeTrabalho) -> None:  # arquivo restaurado do backup (P-19)
                uow.repositorio(RepositorioDocumentos).desbloquear(documento.id)
                self._auditoria.registrar(uow, contexto, VERIFICAR, "documento", documento.id.hex(),
                                          {"bloqueio": ("hash_divergente", None)})  # fmt: skip

            self._executar(liberar)
            return False, True

        return self._percorrer(conferir, depois_de, segundos)

    # ---------------------------------------------------------------- órfãos (DD-37)
    def remover_orfaos(self) -> int:
        conhecidos = self._executar(lambda uow: uow.repositorio(RepositorioDocumentos).arquivos())
        orfaos = self._cofre.orfaos(conhecidos, IDADE_MINIMA_ORFAO)
        for relativo in orfaos:
            self._cofre.remover_orfao(relativo)
        if orfaos:
            contexto = self._contexto(ORFAOS)
            self._executar(lambda uow: self._auditoria.registrar(uow, contexto, ORFAOS, "cofre", None,
                                                                 {"removidos": (None, len(orfaos))}))  # fmt: skip
        return len(orfaos)
