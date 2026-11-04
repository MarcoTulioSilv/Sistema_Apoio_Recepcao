"""Contrato do MOD-05 Emissão e relatórios (DDS §9.6): a única parte importável de fora do módulo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol

from sar.nucleo.contexto import Contexto


class Modelo(StrEnum):
    """Os modelos .docx (DEC-76): o valor é o código gravado em modelo_documento e emissao_documento."""

    CATETER = "DOC-02"
    TROCA = "DOC-03"
    ALIMENTOS = "DOC-04"
    EXTRA = "DOC-07"
    CRACHA = "CRACHA"

    @property
    def titulo(self) -> str:
        return _TITULOS[self]


_TITULOS = {
    Modelo.CATETER: "Termo de responsabilidade — implante de cateter",
    Modelo.TROCA: "Declaração de troca de turno",
    Modelo.ALIMENTOS: "Termo de responsabilidade — alimentos",
    Modelo.EXTRA: "Termo de necessidade de diálise extra",
    Modelo.CRACHA: "Crachá do paciente",
}


@dataclass(frozen=True, slots=True)
class Variavel:
    nome: str
    descricao: str
    imagem: bool = False


@dataclass(frozen=True, slots=True)
class Problema:
    """Um problema do modelo enviado (§9.2), para a tela explicar em linguagem simples."""

    codigo: str  # arquivo.tipo, arquivo.macro, xml.dtd, referencia.externa, variavel.desconhecida, fonte...
    detalhe: str | None = None  # o nome da variável, da fonte ou da estrutura


@dataclass(frozen=True, slots=True)
class VersaoModelo:
    versao: int  # 0: o modelo inicial embutido (DD-103)
    hash_sha256: str
    enviado_em: datetime | None  # None na versão 0
    enviado_por: int | None
    ativo: bool
    ativado_em: datetime | None


@dataclass(frozen=True, slots=True)
class ModeloResumo:
    modelo: Modelo
    versoes: tuple[VersaoModelo, ...]  # da mais nova à 0
    variaveis: tuple[Variavel, ...]  # a lista fechada, para a tela de envio

    @property
    def ativa(self) -> int:
        return next(v.versao for v in self.versoes if v.ativo)


@dataclass(frozen=True, slots=True)
class Envio:
    versao: int  # a versão gravada, ainda inativa
    avisos: tuple[Problema, ...]  # variável partida pelo Word: não impede, mas a tela mostra
    previa: bytes  # PDF com paciente fictício (DD-42)


class ModeloService(Protocol):
    """Só a administração (§4.5, P-22). Envio, ativação e reversão auditados com o hash do arquivo."""

    def listar(self, contexto: Contexto) -> list[ModeloResumo]: ...

    def baixar(self, contexto: Contexto, modelo: Modelo, versao: int | None = None) -> bytes:
        """O .docx da versão (a ativa, sem versão), para editar no Word. NaoEncontrado."""
        ...

    def enviar(self, contexto: Contexto, modelo: Modelo, arquivo: bytes) -> Envio:
        """Valida (§9.2), gera a prévia e grava a versão nova, inativa. RegraViolada("modelo.invalido") com
        `detalhe["problemas"]`: a lista de (código, detalhe). IndisponivelExterno se o conversor não responder."""
        ...

    def previa(self, contexto: Contexto, modelo: Modelo, versao: int) -> bytes:
        """O PDF da versão com o paciente fictício. NaoEncontrado."""
        ...

    def ativar(self, contexto: Contexto, modelo: Modelo, versao: int) -> None:
        """A partir daí, toda emissão usa essa versão; reverter é ativar uma anterior, inclusive a 0. Ativar a que
        já está ativa não grava nem audita. NaoEncontrado."""
        ...


class Documento(StrEnum):
    """Os documentos emitidos para um paciente (§9.1, DEC-76); o crachá tem operação própria."""

    FICHA = "DOC-01"
    CATETER = "DOC-02"
    TROCA = "DOC-03"
    ALIMENTOS = "DOC-04"
    EXTRA = "DOC-07"


@dataclass(frozen=True, slots=True)
class DocumentoEmitido:
    """Gerado de novo a cada emissão, do cadastro atual (RNF-903); entregue em memória, nunca guardado (DD-43)."""

    pdf: bytes
    nome_arquivo: str  # sem dado do paciente: código do documento e data


class EmissaoService(Protocol):
    def emitir(
        self,
        contexto: Contexto,
        documento: Documento,
        paciente_id: int,
        troca_id: int | None = None,
        confirmar_reemissao: bool = False,
    ) -> DocumentoEmitido:
        """Recepção e administração (§4.5). O DOC-03 sai de uma troca do paciente registrada e não cancelada
        (`troca_id`, RF-804). O DOC-07 avisa se já houve emissão no mês: ConfirmacaoNecessaria("extra.emitido_no_mes")
        até `confirmar_reemissao` (RF-805). NaoEncontrado (paciente ou troca), RegraViolada("instituicao.ausente")
        sem os dados institucionais (RF-802), IndisponivelExterno se o conversor não responder."""
        ...

    def emitir_cracha(self, contexto: Contexto, paciente_id: int) -> DocumentoEmitido:
        """RF-808. RegraViolada("cracha.sem_foto"): a tela orienta a capturar a foto."""
        ...


class RelatorioService(Protocol):
    def aniversariantes(self, contexto: Contexto, data: date) -> list[str]:
        """Os nomes dos pacientes em tratamento que fazem aniversário na data; só na tela inicial, não exportável
        (§10, RF-909). Sem registro na trilha (§4.5). AcessoNegado para quem não é recepção nem administração."""
        ...
