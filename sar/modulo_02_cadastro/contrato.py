"""Contrato do MOD-02 Cadastro (DDS §6.7): a única parte importável de fora do módulo. Os serviços entram nas
etapas seguintes do Incremento 2; aqui começam os tipos que as regras e os serviços compartilham."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class Sexo(str, Enum):
    FEMININO = "F"
    MASCULINO = "M"


class TipoTelefone(str, Enum):
    CELULAR = "celular"
    FIXO = "fixo"
    RECADO = "recado"


class TipoEvento(str, Enum):
    OBITO = "obito"
    ALTA = "alta"
    TRANSFERENCIA = "transferencia"
    TRANSPLANTE = "transplante"
    DESISTENCIA = "desistencia"


class Situacao(str, Enum):  # §6.3, sempre derivada
    EM_CADASTRO = "em_cadastro"
    SEM_ALOCACAO = "sem_alocacao"
    ATIVO = "ativo"
    INATIVO = "inativo"
    FALECIDO = "falecido"


@dataclass(frozen=True, slots=True)
class DadosPaciente:
    """Campos da ficha (RF-101, RF-110, RF-111), na ordem da ficha de papel (RF-106). Só o nome e o prontuário
    são obrigatórios para criar (P-03); o que faltar vira pendência nomeada (RF-102). CPF, CNS e CEP podem vir
    com pontuação: as regras guardam só os dígitos."""

    prontuario: str | None = None
    nome: str | None = None
    data_nascimento: date | None = None
    sexo: Sexo | None = None
    nome_mae: str | None = None
    cpf: str | None = None
    cns: str | None = None
    rg: str | None = None
    rg_orgao: str | None = None
    naturalidade_municipio: str | None = None  # código IBGE
    logradouro: str | None = None
    numero: str | None = None
    complemento: str | None = None
    bairro: str | None = None
    municipio: str | None = None  # código IBGE; residência só em Goiás
    cep: str | None = None


class TipoCobertura(str, Enum):  # RF-301
    SUS = "sus"
    CONVENIO = "convenio"
