"""Contrato do MOD-06 Configuração (DDS §10.3): a única parte importável de fora do módulo. A leitura de
parâmetro pelos outros módulos é pela porta LeitorParametros do núcleo (DD-73), não por aqui; a dos dados de
referência é pelo Referencias, dentro da transação de quem chama."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.uow import UnidadeDeTrabalho

Valor = int | bool | date | None


@dataclass(frozen=True, slots=True)
class ParametroVigente:
    nome: str
    unidade: str
    valor: Valor
    padrao: Valor
    minimo: int | None
    maximo: int | None
    editor: Perfil
    imutavel_apos_uso: bool
    alterado_em: datetime | None  # None: nunca alterado, vale o padrão
    alterado_por: int | None


@dataclass(frozen=True, slots=True)
class Convenio:
    id: int
    nome: str
    ativo: bool


@dataclass(frozen=True, slots=True)
class Municipio:
    codigo: str  # IBGE, 7 dígitos
    nome: str
    uf: str


class Referencias(Protocol):
    """Para os outros módulos (MOD-02, MOD-05), dentro da unidade de trabalho deles. Sem verificação de
    permissão: quem chama já verificou a da sua operação."""

    def convenios_ativos(self, uow: UnidadeDeTrabalho) -> list[Convenio]: ...

    def convenio(self, uow: UnidadeDeTrabalho, id: int) -> Convenio | None:
        """Ativo ou não: a cobertura antiga mostra o convênio inativado (DD-49)."""
        ...

    def municipio(self, uow: UnidadeDeTrabalho, codigo: str) -> Municipio | None: ...

    def buscar_municipios(self, uow: UnidadeDeTrabalho, termo: str, uf: str | None = None) -> list[Municipio]:
        """Nomes que começam pelo termo, sem distinção de caixa e de acento; no máximo 20. Termo com menos de
        2 caracteres não busca. RegraViolada se a UF não existir."""
        ...


class ConfiguracaoService(Protocol):
    def listar_parametros(self, contexto: Contexto) -> list[ParametroVigente]: ...

    def alterar_parametro(self, contexto: Contexto, nome: str, valor: Valor) -> None:
        """Administração altera os operacionais; TI, os técnicos (§4.6). RegraViolada se o valor estiver fora
        dos limites ou do tipo, ou se o parâmetro for imutável e já tiver sido usado (DD-51). Auditada com o
        valor antes e depois."""
        ...

    def listar_convenios(self, contexto: Contexto) -> list[Convenio]:
        """Todos, ativos e inativos, em ordem de nome (config.consultar)."""
        ...

    def buscar_municipios(self, contexto: Contexto, termo: str, uf: str | None = None) -> list[Municipio]:
        """O mesmo de Referencias.buscar_municipios, para a interface (config.consultar)."""
        ...

    def listar_municipios(self, contexto: Contexto, uf: str) -> list[Municipio]:
        """Todos os municípios da UF, em ordem de nome, para os campos de escolha (config.consultar).
        RegraViolada("municipio.uf")."""
        ...

    def incluir_convenio(self, contexto: Contexto, nome: str) -> int:
        """Administração (RF-1204). RegraViolada se o nome for inválido ou já existir, sem distinção de caixa e
        de acento. Auditada."""
        ...

    def renomear_convenio(self, contexto: Contexto, convenio_id: int, nome: str) -> None:
        """Mesmas regras da inclusão; o nome igual ao atual não grava nem audita. NaoEncontrado."""
        ...

    def inativar_convenio(self, contexto: Contexto, convenio_id: int) -> None:
        """Deixa de ser oferecido em novo registro; a cobertura antiga continua com ele (DD-49). Já inativo não
        grava nem audita. NaoEncontrado."""
        ...

    def reativar_convenio(self, contexto: Contexto, convenio_id: int) -> None: ...
