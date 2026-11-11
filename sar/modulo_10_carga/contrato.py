"""Contrato do MOD-10 Carga inicial (DDS §14.5): a única parte importável de fora do módulo."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from sar.nucleo.contexto import Contexto


class Modo(str, Enum):
    SIMULACAO = "simulacao"
    EFETIVACAO = "efetivacao"


@dataclass(frozen=True, slots=True)
class ResumoCarga:
    """Só números, por planilha e por código de exceção e de aviso (DD-65): é o que o terminal do TI mostra.

    contagens: {"p1": {"linhas", "importados", "excecoes"}, "p4": {"linhas", "ligadas", "fora_da_base",
    "sem_prontuario"}, "p3": {"linhas", "casadas", "sem_correspondencia"}, "excecoes": {código: n},
    "avisos": {código: n}, "cid_descartados": n, "fecha": bool}."""

    lote_id: int
    modo: Modo
    contagens: dict[str, Any]


class CargaService(Protocol):
    def simular(self, contexto: Contexto, pasta: Path) -> ResumoCarga:
        """Tudo numa transação desfeita no fim (DD-66); fica só o relatório de exceções e avisos, cifrado, até a
        próxima execução. AcessoNegado para quem não é TI; RegraViolada: "carga.ja_efetivada",
        "carga.contagem_nao_fecha" (RNF-103), "carga.planilha_ausente", "carga.planilha_ilegivel",
        "carga.planilha_grande" e "carga.p4_cabecalho"."""
        ...

    def efetivar(self, contexto: Contexto, pasta: Path) -> ResumoCarga:
        """Uma transação só, uma vez (DD-66, DD-72): grava os pacientes e todas as fichas da P1, cifradas, para a
        revisão e a conferência, e sorteia a primeira amostra (P-29). Os mesmos erros da simulação."""
        ...
