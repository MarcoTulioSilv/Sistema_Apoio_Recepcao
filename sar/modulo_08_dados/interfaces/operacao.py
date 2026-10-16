"""Dados do MOD-03 Operação (DDS §7.1, §7.9): escalas, alocações, trocas, extras, termos, sessões, presenças,
ligações, ciências e marcas de mês alterado. Instantes em UTC, com fuso."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Literal, Protocol

SituacaoPresenca = Literal["presente", "ausente"]


@dataclass(frozen=True, slots=True)
class EscalaGravada:
    id: int
    codigo: str
    turno: int
    dias: str  # "seg,qua,sex"
    hora_inicio: time
    hora_fim: time


@dataclass(frozen=True, slots=True)
class AlocacaoGravada:
    id: int
    periodo_id: int
    escala_id: int | None  # None = sem alocação a partir da vigência (DD-27)
    vigencia_inicio: date


@dataclass(frozen=True, slots=True)
class TrocaGravada:
    id: int
    paciente_id: int
    data_origem: date
    data_destino: date
    escala_destino_id: int
    documento_id: bytes | None
    cancelada_em: datetime | None
    cancelada_motivo: str | None


@dataclass(frozen=True, slots=True)
class ExtraGravada:
    id: int
    paciente_id: int
    data: date
    escala_id: int
    cancelada_em: datetime | None
    cancelada_motivo: str | None


@dataclass(frozen=True, slots=True)
class SessaoGravada:
    id: int
    data: date
    escala_id: int
    confirmada_em: datetime | None
    confirmada_por: int | None
    nao_realizada_motivo: str | None
    versao: int


@dataclass(frozen=True, slots=True)
class PresencaGravada:
    id: int
    sessao_id: int
    paciente_id: int
    situacao: SituacaoPresenca
    data: date  # da sessão
    escala_id: int  # da sessão


@dataclass(frozen=True, slots=True)
class LigacaoGravada:
    id: int
    ausencia_id: int
    presenca_id: int
    criada_por: int
    criada_em: datetime


@dataclass(frozen=True, slots=True)
class CienciaGravada:
    presenca_id: int
    registrada_em: datetime
    registrada_por: int


@dataclass(frozen=True, slots=True)
class MarcaGravada:
    id: int
    competencia: str
    instante: datetime
    responsavel_id: int
    autorizador_id: int
    motivo: str
    solicitacao_id: bytes | None


class RepositorioOperacao(Protocol):
    # ---------------------------------------------------------------- escalas (tabela fixa, DEC-52)
    def escalas(self) -> list[EscalaGravada]:
        """Em ordem de id."""
        ...

    # ---------------------------------------------------------------- alocações (DD-27)
    def alocacoes(self, periodo_ids: Sequence[int]) -> list[AlocacaoGravada]:
        """Em ordem de período e de início."""
        ...

    def gravar_alocacao(self, periodo_id: int, escala_id: int | None, inicio: date) -> int:
        """Cria a vigência ou, se já houver uma no mesmo período e início, troca a escala dela (único da 0001)."""
        ...

    # ---------------------------------------------------------------- trocas e extras
    def troca_por_id(self, id: int, travar: bool = False) -> TrocaGravada | None: ...

    def trocas(self, paciente_ids: Sequence[int] | None, inicio: date, fim: date) -> list[TrocaGravada]:
        """Não canceladas com origem ou destino entre as datas; todas as dos pacientes, ou de todos com None."""
        ...

    def criar_troca(self, paciente_id: int, origem: date, destino: date, escala_destino_id: int) -> int: ...

    def cancelar_troca(self, id: int, em: datetime, motivo: str | None) -> None: ...

    def extra_por_id(self, id: int, travar: bool = False) -> ExtraGravada | None: ...

    def extras(self, paciente_ids: Sequence[int] | None, inicio: date, fim: date) -> list[ExtraGravada]:
        """Não canceladas entre as datas."""
        ...

    def criar_extra(self, paciente_id: int, data: date, escala_id: int) -> int: ...

    def cancelar_extra(self, id: int, em: datetime, motivo: str | None) -> None: ...

    # ---------------------------------------------------------------- sessões e presenças (DD-23, DD-24)
    def sessao(self, data: date, escala_id: int, travar: bool = False) -> SessaoGravada | None: ...

    def criar_sessao(self, data: date, escala_id: int) -> int:
        """Na confirmação; o único (data, escala) barra a segunda estação."""
        ...

    def garantir_sessao(self, data: date, escala_id: int) -> SessaoGravada:
        """Na primeira marcação: cria se não existe, sem corrida entre estações, e devolve a linha travada."""
        ...

    def tocar_sessao(self, id: int) -> int:
        """Avança a versão quando a lista muda (marcação, acréscimo), para a confirmação de uma tela antiga
        receber conflito (DD-17). Devolve a nova versão."""
        ...

    def sessoes(self, inicio: date, fim: date) -> list[SessaoGravada]:
        """Gravadas entre as datas, em ordem de data e escala."""
        ...

    def alguma_confirmada(self) -> bool:
        """Para a trava da data de implantação (DD-51)."""
        ...

    def confirmar_sessao(self, id: int, versao: int, em: datetime, por: int, nao_realizada: str | None) -> bool:
        """Grava a confirmação (ou a não realização, com o motivo) se a versão ainda for a informada."""
        ...

    def reabrir_sessao(self, id: int, versao: int) -> bool:
        """Desfaz a confirmação (ou a não realização) se a versão ainda for a informada; as presenças gravadas
        ficam, como exceções da sessão reaberta."""
        ...

    def presencas_da_sessao(self, sessao_id: int) -> list[PresencaGravada]: ...

    def presenca_por_id(self, id: int) -> PresencaGravada | None: ...

    def presencas(self, paciente_ids: Sequence[int] | None, inicio: date, fim: date) -> list[PresencaGravada]:
        """Das sessões entre as datas, em ordem de data e escala."""
        ...

    def gravar_presenca(self, sessao_id: int, paciente_id: int, situacao: SituacaoPresenca) -> int:
        """Cria ou muda a situação da presença do paciente na sessão."""
        ...

    def remover_presenca(self, id: int) -> None:
        """Remove também as ligações e a ciência da presença, que não podem ficar sem ela."""
        ...

    # ---------------------------------------------------------------- ligações manuais (DD-25) e ciências (RF-921)
    def ligacoes(self, presenca_ids: Sequence[int]) -> list[LigacaoGravada]:
        """As que têm um dos lados entre as presenças informadas."""
        ...

    def criar_ligacao(self, ausencia_id: int, presenca_id: int, por: int, em: datetime) -> int: ...

    def remover_ligacoes(self, ids: Sequence[int]) -> None: ...

    def ciencias(self, presenca_ids: Sequence[int]) -> list[CienciaGravada]: ...

    def criar_ciencia(self, presenca_id: int, em: datetime, por: int) -> None: ...

    def presencas_fora_da_escala(
        self, paciente_ids: Sequence[int] | None, inicio: date, fim: date, *, sem_planejamento: bool, sem_ciencia: bool
    ) -> list[PresencaGravada]:
        """Presenças (situação presente) em sessão que não é a da escala vigente do paciente na data. Com
        sem_planejamento, só as que não têm troca chegando nem extra planejada para a sessão (RF-921); com
        sem_ciencia, só as ainda sem ciência da enfermagem."""
        ...

    # ---------------------------------------------------------------- termos (RF-805, RF-809, DD-28)
    def ligar_documento_troca(self, troca_id: int, documento_id: bytes | None) -> None: ...

    def trocas_do_documento(self, documento_id: bytes) -> list[TrocaGravada]: ...

    def trocas_sem_documento(self, paciente_ids: Sequence[int] | None) -> list[TrocaGravada]:
        """Não canceladas e sem o termo assinado, em ordem de paciente e de origem."""
        ...

    def gravar_termo(self, paciente_id: int, competencia: str, documento_id: bytes) -> None:
        """Um por paciente e mês: o documento novo (nova versão) substitui o anterior."""
        ...

    def termos(self, paciente_ids: Sequence[int] | None) -> list[tuple[int, str, bytes]]:
        """(paciente, competência, documento)."""
        ...

    def remover_termos_do_documento(self, documento_id: bytes) -> list[tuple[int, str]]:
        """Remove e devolve (paciente, competência) dos termos que apontavam para o documento."""
        ...

    # ---------------------------------------------------------------- anulação (§7.8, DEC-61)
    def contagens_do_paciente(self, paciente_id: int, periodo_ids: Sequence[int]) -> dict[str, int]:
        """Quantas presenças, alocações, trocas, extras, ligações, ciências e termos o paciente tem."""
        ...

    def remover_do_paciente(self, paciente_id: int, periodo_ids: Sequence[int]) -> None:
        """Descarta tudo o que é do MOD-03 e está ligado ao paciente, na ordem das chaves estrangeiras."""
        ...

    # ---------------------------------------------------------------- marca de mês alterado (RF-915, DD-26)
    def criar_marca(
        self,
        competencia: str,
        instante: datetime,
        responsavel_id: int,
        autorizador_id: int,
        motivo: str,
        solicitacao_id: bytes | None,
    ) -> int:
        """Só inserção."""
        ...

    def marcas(self, competencias: Sequence[str]) -> list[MarcaGravada]:
        """Em ordem de competência e de instante."""
        ...
