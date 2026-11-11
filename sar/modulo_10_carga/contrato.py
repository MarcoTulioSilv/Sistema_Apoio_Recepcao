"""Contrato do MOD-10 Carga inicial (DDS §14.5): a única parte importável de fora do módulo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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


class Tratamento(str, Enum):
    IMPORTADA_MANUAL = "importada_manual"  # a recepção cadastrou pela tela (P-28)
    DESCARTADA = "descartada"  # com motivo


class ResultadoConferencia(str, Enum):
    CONFERIDO = "conferido"
    DIVERGENTE = "divergente"


# Os campos conferidos na amostra (P-29: todos), na ordem da ficha; o rótulo é o da tela.
CAMPOS_CONFERIDOS: tuple[tuple[str, str], ...] = (
    ("nome", "Nome"),
    ("prontuario", "Prontuário"),
    ("nome_mae", "Nome da mãe"),
    ("data_nascimento", "Data de nascimento"),
    ("cpf", "CPF"),
    ("rg", "RG e órgão expedidor"),
    ("cns", "CNS"),
    ("endereco", "Endereço"),
    ("municipio", "Município"),
    ("cep", "CEP"),
    ("telefones", "Telefones e contatos"),
    ("convenio", "Convênio"),
    ("inicio", "Início do tratamento"),
)


@dataclass(frozen=True, slots=True)
class Original:
    """A ficha como estava na P1 e as linhas da P4 e da P3 ligadas a ela: o lado esquerdo da conferência."""

    p1: tuple[tuple[str, str | None], ...]  # (rótulo, valor), na ordem da planilha
    p4: tuple[dict[str, str | None], ...]
    p3: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class LinhaRelatorio:
    linha_id: int
    numero_linha: int
    excecao: str | None  # None: importada, talvez com avisos
    avisos: tuple[str, ...]
    tratamento: Tratamento | None
    motivo: str | None
    paciente_id: int | None
    original: Original


@dataclass(frozen=True, slots=True)
class Relatorio:
    """O relatório de exceções e avisos (RF-1106) do último lote: a efetivação, se houver; senão, a última simulação."""

    lote_id: int
    modo: Modo
    concluido_em: datetime | None
    aceito_em: datetime | None
    contagens: dict[str, Any]
    linhas: tuple[LinhaRelatorio, ...]  # na efetivação, só as com exceção ou aviso

    @property
    def pendentes(self) -> int:
        """Exceções ainda sem tratamento: o aceite espera por elas."""
        return sum(1 for linha in self.linhas if linha.excecao and linha.tratamento is None)


@dataclass(frozen=True, slots=True)
class PacienteSorteado:
    linha_id: int
    paciente_id: int
    rodada: int
    nome: str | None  # None: cadastro anulado depois da carga; sai da conta da amostra
    prontuario: str | None
    conferidos: int
    divergentes: int

    @property
    def completo(self) -> bool:
        return self.nome is None or self.conferidos + self.divergentes == len(CAMPOS_CONFERIDOS)


@dataclass(frozen=True, slots=True)
class Amostra:
    pacientes: tuple[PacienteSorteado, ...]
    rodadas: int

    @property
    def completa(self) -> bool:
        return bool(self.pacientes) and all(p.completo for p in self.pacientes)

    @property
    def divergencias(self) -> int:
        return sum(p.divergentes for p in self.pacientes)

    @property
    def pode_sortear_mais(self) -> bool:
        """P-29: com a amostra conferida e alguma divergência, a recepção pode pedir mais 15."""
        return self.completa and self.divergencias > 0


@dataclass(frozen=True, slots=True)
class CampoConferencia:
    campo: str
    rotulo: str
    valor_cadastro: str | None
    resultado: ResultadoConferencia | None


@dataclass(frozen=True, slots=True)
class Conferencia:
    """A tela lado a lado (§14.3): a planilha à esquerda, o cadastro como ficou à direita."""

    linha_id: int
    paciente_id: int
    original: Original
    campos: tuple[CampoConferencia, ...]


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

    def relatorio(self, contexto: Contexto) -> Relatorio | None:
        """RF-1106, para a recepção e a administração (nunca para o TI, RF-1004); a consulta é auditada. None antes
        da primeira simulação. Depois do aceite, só as contagens: as linhas já foram apagadas (DD-69)."""
        ...

    def tratar_excecao(
        self, contexto: Contexto, linha_id: int, tratamento: Tratamento, motivo: str | None, prontuario: str | None
    ) -> None:
        """Importada à mão: o prontuário do cadastro que a recepção fez pela tela, que fica ligado à linha. Descartada:
        motivo obrigatório. Pode ser refeito até o aceite. RegraViolada: "carga.sem_efetivacao", "carga.aceita",
        "carga.linha_sem_excecao", "carga.motivo", "carga.paciente_nao_encontrado", "carga.paciente_ja_ligado".
        NaoEncontrado se a linha não existe."""
        ...

    def amostra(self, contexto: Contexto) -> Amostra:
        """Os pacientes sorteados na efetivação e nas rodadas seguintes, com o andamento de cada um."""
        ...

    def conferencia(self, contexto: Contexto, linha_id: int) -> Conferencia:
        """NaoEncontrado se a linha não foi sorteada ou o cadastro foi anulado."""
        ...

    def registrar_conferencia(
        self, contexto: Contexto, linha_id: int, campo: str, resultado: ResultadoConferencia
    ) -> None:
        """Um campo do paciente sorteado. A divergência se corrige no cadastro, pela tela normal (§14.3, item 3).
        RegraViolada: "carga.aceita", "carga.campo". NaoEncontrado se a linha não foi sorteada."""
        ...

    def sortear_mais(self, contexto: Contexto) -> int:
        """P-29: mais 15, entre os importados ainda não sorteados; devolve quantos. RegraViolada:
        "carga.amostra_incompleta", "carga.sem_divergencia", "carga.aceita"."""
        ...

    def aceitar(self, contexto: Contexto, ativos_confirmados: int, confirmar_diferenca: bool = False) -> None:
        """Só a administração. Encerra a carga e apaga a área de trabalho (DD-69); não há segunda carga.
        RegraViolada: "carga.sem_efetivacao", "carga.aceita", "carga.amostra_incompleta",
        "carga.excecao_sem_tratamento", "carga.ativos_confirmados". ConfirmacaoNecessaria("ativos",
        {"carregados": n, "confirmados": m}) se o número confirmado pela recepção não bater com os carregados."""
        ...
