"""Contrato do MOD-01 Acesso e auditoria (DDS §5.4): a única parte importável de fora do módulo."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from sar.nucleo.contexto import Contexto
from sar.nucleo.uow import UnidadeDeTrabalho


@dataclass(frozen=True, slots=True)
class ResultadoVerificacao:
    integra: bool
    verificados: int
    primeiro_divergente_id: int | None = None
    motivo: str | None = None  # sequencia, elo, hash, ancora ou cabeca: diagnóstico para o TI
    alterado_depois_de: datetime | None = None  # QAS-13: data aproximada da alteração


@dataclass(frozen=True, slots=True)
class AvisoSimples:
    """O que a administração vê (RF-1011): sem detalhe técnico nem dado de paciente."""

    id: int
    detectado_em: datetime


@dataclass(frozen=True, slots=True)
class AvisoDiagnostico(AvisoSimples):
    """O que o TI vê: o elo divergente, para investigar."""

    registro_divergente_id: int


@dataclass(frozen=True, slots=True)
class CodigoIntegridade:
    """O que sai no rodapé dos relatórios e documentos emitidos (DD-86): o registro da âncora mais recente, o
    código (16 hexadecimais em quatro blocos) e quando a âncora foi registrada. A data é formatada na borda."""

    registro_id: int
    codigo: str
    registrada_em: datetime


class Conferencia(str, Enum):
    CONFERE = "confere"
    NAO_CONFERE = "nao_confere"  # a trilha atual não é a que existia quando o documento saiu
    SEM_REGISTRO = "sem_registro"  # nem o registro nem a âncora existem mais (expurgo de 5 anos)


class AuditService(Protocol):
    def registrar(
        self,
        uow: UnidadeDeTrabalho,
        contexto: Contexto,
        operacao: str,
        entidade: str,
        entidade_id: str | None,
        alteracoes: Mapping[str, tuple[object, object]] | None = None,
        motivo: str | None = None,
        autorizador_id: int | None = None,
    ) -> None:
        """Registra na mesma transação da operação; a falha desfaz a operação (DD-03). Só os campos que
        mudaram entram (DD-10); bytes, ponto flutuante e instante sem fuso são recusados na hora."""
        ...

    def verificar_cadeia(self, contexto: Contexto) -> ResultadoVerificacao:
        """TI ou sistema. Divergência abre aviso de integridade (RF-1011); cadeia íntegra registra a âncora
        (§13.1). Grava âncora e aviso: roda no processo do worker (DD-58)."""
        ...

    def codigo_vigente(self, uow: UnidadeDeTrabalho) -> CodigoIntegridade | None:
        """Para o rodapé: chamado pelo MOD-05 dentro da operação de emissão. None antes da primeira âncora."""
        ...

    def expurgar(self, contexto: Contexto) -> int:
        """Sistema. Apaga a trilha com mais de 5 anos (DEC-45) e grava o ponto de corte (RNF-628). Devolve
        quantos registros saíram."""
        ...


class IntegridadeService(Protocol):
    def ver_avisos(self, contexto: Contexto) -> list[AvisoSimples]:
        """Avisos abertos: simples para a administração, com diagnóstico para o TI."""
        ...

    def encerrar_aviso(self, contexto: Contexto, aviso_id: int, explicacao: str) -> None:
        """Só a administração, com a explicação recebida (DEC-43)."""
        ...

    def conferir_codigo(self, contexto: Contexto, registro_id: int, codigo: str) -> Conferencia:
        """Administração ou TI, numa investigação: o código do rodapé de um documento guardado confere com a
        trilha atual? (DD-86). Auditada."""
        ...
