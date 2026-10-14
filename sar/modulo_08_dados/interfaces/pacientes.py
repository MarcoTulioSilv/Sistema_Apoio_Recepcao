"""Agregado do paciente (DDS §6.1): paciente, períodos com evento e coberturas, contatos e telefones. Os campos
têm os mesmos nomes do DadosPaciente do MOD-02; o repositório faz a ponte com as colunas."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol

ColunaUnica = Literal["prontuario", "cpf", "cns"]


@dataclass(frozen=True, slots=True)
class CamposPaciente:
    prontuario: str | None  # None só no paciente anulado (DD-89)
    nome: str | None
    data_nascimento: date | None
    sexo: str | None
    nome_mae: str | None
    cpf: str | None
    cns: str | None
    rg: str | None
    rg_orgao: str | None
    naturalidade_municipio: str | None
    logradouro: str | None
    numero: str | None
    complemento: str | None
    bairro: str | None
    municipio: str | None
    cep: str | None


@dataclass(frozen=True, slots=True)
class PacienteGravado:
    id: int
    versao: int
    campos: CamposPaciente
    cep_verificado: bool
    anulado_em: datetime | None
    criado_em: datetime


@dataclass(frozen=True, slots=True)
class PeriodoGravado:
    id: int
    paciente_id: int
    inicio: date
    evento_tipo: str | None
    evento_data: date | None
    evento_local: str | None
    evento_documento_id: bytes | None
    evento_registrado_em: datetime | None


@dataclass(frozen=True, slots=True)
class CoberturaGravada:
    id: int
    periodo_id: int
    inicio: date
    tipo: str
    convenio_id: int | None
    carteirinha: str | None


@dataclass(frozen=True, slots=True)
class ContatoGravado:
    id: int
    paciente_id: int
    nome: str
    parentesco: str | None


@dataclass(frozen=True, slots=True)
class TelefoneGravado:
    id: int
    paciente_id: int | None
    contato_id: int | None
    ddd: str
    numero: str
    tipo: str


class RepositorioPaciente(Protocol):
    # ---------------------------------------------------------------- paciente
    def criar(self, campos: CamposPaciente, cep_verificado: bool, em: datetime) -> int: ...

    def por_id(self, id: int, travar: bool = False) -> PacienteGravado | None:
        """Inclusive anulado; quem chama decide. Com travar, a linha fica presa até o fim da transação: é a
        trava do agregado inteiro."""
        ...

    def atualizar(self, id: int, versao: int, campos: CamposPaciente, cep_verificado: bool) -> bool:
        """Grava se a versão ainda for a informada, e avança a versão (DD-17). False se outra tela gravou antes."""
        ...

    def anular(self, id: int, em: datetime) -> None:
        """DD-89: apaga os dados pessoais (todos os campos a nulo), exclui contatos e telefones, marca a anulação e
        avança a versão. Períodos e coberturas ficam."""
        ...

    def definir_cep_verificado(self, id: int, verificado: bool) -> None:
        """Resultado da consulta feita na resolução da pendência; não muda a versão do cadastro."""
        ...

    def quem_usa(self, coluna: ColunaUnica, valor: str) -> int | None:
        """Id do paciente que já tem o valor, anulado ou não: a restrição do banco vale para todos."""
        ...

    def por_nascimento(self, data: date) -> list[PacienteGravado]:
        """Não anulados, para a comparação da tríade (INV-08), que é feita no serviço."""
        ...

    def buscar(self, nome: str | None, exato: str | None, limite: int) -> list[PacienteGravado]:
        """Não anulados cujo nome contém o termo (sem distinção de caixa e de acento, pela collation), ou cujo
        prontuário, CPF ou CNS é igual ao termo exato. Em ordem de nome."""
        ...

    def vivos(self, ids: Sequence[int] | None) -> list[PacienteGravado]:
        """Não anulados, todos ou só os dos ids, numa consulta só (§11.3)."""
        ...

    def periodos_de(self, ids: Sequence[int] | None) -> list[PeriodoGravado]:
        """Períodos dos pacientes não anulados, todos ou só os dos ids, em ordem de paciente e de início."""
        ...

    def descartes(self) -> set[tuple[int, int]]:
        """Pares de duplicidade descartada, com o menor id primeiro."""
        ...

    def duplicidade_descartada(self, a: int, b: int) -> bool: ...

    def descartar_duplicidade(self, a: int, b: int, por: int, em: datetime) -> None:
        """Par gravado com o menor id primeiro (restrição da 0001)."""
        ...

    # ---------------------------------------------------------------- períodos e coberturas
    def periodos(self, paciente_id: int) -> list[PeriodoGravado]:
        """Em ordem de início."""
        ...

    def abrir_periodo(self, paciente_id: int, inicio: date) -> int: ...

    def periodo(self, id: int) -> PeriodoGravado | None: ...

    def gravar_evento(
        self,
        periodo_id: int,
        tipo: str | None,
        data: date | None,
        local: str | None,
        documento_id: bytes | None,
        registrado_em: datetime | None,
    ) -> None:
        """Registra, corrige ou remove (tudo None) o evento embutido no período (DD-13)."""
        ...

    def criar_cobertura(
        self, periodo_id: int, inicio: date, tipo: str, convenio_id: int | None, carteirinha: str | None
    ) -> int: ...

    def coberturas(self, periodo_ids: list[int]) -> list[CoberturaGravada]:
        """Em ordem de período e de início."""
        ...

    def pacientes_com_periodo_em(self, data: date) -> list[int]:
        """Não anulados com período que cobre a data: início até a data e evento, se houver, nela ou depois."""
        ...

    # ---------------------------------------------------------------- contatos e telefones
    def contatos(self, paciente_id: int) -> list[ContatoGravado]: ...

    def telefones(self, paciente_id: int) -> list[TelefoneGravado]:
        """Os do paciente e os dos contatos dele."""
        ...

    def contato(self, id: int) -> ContatoGravado | None: ...

    def criar_contato(self, paciente_id: int, nome: str, parentesco: str | None) -> int: ...

    def alterar_contato(self, id: int, nome: str, parentesco: str | None) -> None: ...

    def remover_contato(self, id: int) -> None:
        """Remove também os telefones do contato, que não podem ficar sem dono (INV-12)."""
        ...

    def telefone(self, id: int) -> TelefoneGravado | None: ...

    def criar_telefone(self, paciente_id: int | None, contato_id: int | None, ddd: str, numero: str, tipo: str) -> int:
        """Exatamente um dos dois donos (INV-12, garantida também pela CHECK do banco)."""
        ...

    def alterar_telefone(self, id: int, ddd: str, numero: str, tipo: str) -> None:
        """O dono não muda: telefone de contato não passa para o paciente, nem o contrário."""
        ...

    def remover_telefone(self, id: int) -> None: ...
