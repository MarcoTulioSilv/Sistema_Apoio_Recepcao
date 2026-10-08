"""Contrato do MOD-01 Acesso e auditoria (DDS §5.4): a única parte importável de fora do módulo."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from sar.modulo_01_acesso.matriz import MATRIZ, Acesso, Celula, Entrada
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado, ErroSAR
from sar.nucleo.uow import UnidadeDeTrabalho


# ------------------------------------------------------------------ autenticação (DDS §5.2, §5.4)
class CredencialInvalida(AcessoNegado):
    """Mensagem sempre a mesma: login inexistente, senha errada, usuário inativo ou bloqueado. O motivo real
    vai só para a trilha (§5.2)."""


class TermoPendente(AcessoNegado):
    """Senha certa, mas sem termo de ciência registrado pelo TI (DEC-47)."""


class TrocaDeSenhaExigida(ErroSAR):
    """Senha certa e provisória: repetir a entrada informando a nova senha."""


class SessaoEncerrada(AcessoNegado):
    """Token desconhecido ou sessão encerrada. O motivo orienta a tela: "novo_login" mostra o aviso de que
    houve entrada em outro lugar (P-02); "inatividade" e "limite" pedem nova entrada (DD-19)."""

    def __init__(self, motivo: str | None = None) -> None:
        super().__init__(motivo or "sessao_desconhecida")
        self.motivo = motivo


@dataclass(frozen=True, slots=True)
class SessaoAberta:
    """O token vai só para o cookie; o banco guarda o SHA-256 dele (DD-05)."""

    token: str
    contexto: Contexto
    nome: str


class PermissionGuard:
    """Decide pelo perfil, a partir da matriz única (DDS §4, AD-20). Toda operação passa por aqui, no serviço;
    rota nenhuma decide acesso sozinha. Regras de recurso (o próprio rascunho, a visão pseudonimizada) ficam
    no serviço, guiadas pela nota da célula."""

    def __init__(self, matriz: tuple[Entrada, ...] = MATRIZ) -> None:
        self._por_chave = {(e.codigo, e.condicao): e for e in matriz}
        self._por_codigo: dict[str, list[Entrada]] = {}
        for entrada in matriz:
            self._por_codigo.setdefault(entrada.codigo, []).append(entrada)

    def _entrada(self, operacao: str, condicao: str | None) -> Entrada:
        variantes = self._por_codigo.get(operacao)
        if not variantes:
            raise LookupError(f"operação fora do catálogo do DDS §4: {operacao}")
        if condicao is None:
            if len(variantes) > 1:
                raise LookupError(f"{operacao} tem variantes: informe a condição")
            return variantes[0]
        entrada = self._por_chave.get((operacao, condicao))
        if entrada is None:
            raise LookupError(f"condição desconhecida para {operacao}: {condicao}")
        return entrada

    def celula(self, contexto: Contexto, operacao: str, condicao: str | None = None) -> Celula | None:
        return self._entrada(operacao, condicao).celulas.get(contexto.perfil)

    def pode(self, contexto: Contexto, operacao: str, condicao: str | None = None) -> bool:
        celula = self.celula(contexto, operacao, condicao)
        return celula is not None and celula.acesso is Acesso.EXECUTA

    def pode_solicitar(self, contexto: Contexto, operacao: str, condicao: str | None = None) -> bool:
        """Operação marcada "Aut.": o perfil pede, a administração aprova (DEC-42)."""
        celula = self.celula(contexto, operacao, condicao)
        return celula is not None and celula.acesso is Acesso.SOLICITA

    def exigir(self, contexto: Contexto, operacao: str, condicao: str | None = None) -> Celula:
        """Devolve a célula, para o serviço aplicar a nota (ex.: "diagnóstico" para o TI)."""
        celula = self.celula(contexto, operacao, condicao)
        if celula is None or celula.acesso is not Acesso.EXECUTA:
            raise AcessoNegado()
        return celula


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


class AuthService(Protocol):
    def entrar(self, login: str, senha: str, origem: str, nova_senha: str | None = None) -> SessaoAberta:
        """CredencialInvalida (mensagem única), TermoPendente, TrocaDeSenhaExigida ou RegraViolada (nova senha
        fraca, DD-83). Toda tentativa entra na trilha, inclusive as falhas (§4.1). Abre sessão nova e encerra a
        anterior do mesmo usuário (P-02)."""
        ...

    def sair(self, contexto: Contexto) -> None: ...

    def trocar_propria_senha(self, contexto: Contexto, senha_atual: str, nova_senha: str) -> None: ...


# ------------------------------------------------------------------ usuários (DDS §5.1, §4.1)
@dataclass(frozen=True, slots=True)
class UsuarioResumo:
    """O que a tela do TI vê de um usuário: nunca o hash da senha."""

    id: int
    nome: str
    login: str
    perfil: Perfil
    ativo: bool
    termo_ciencia_em: datetime | None
    deve_trocar_senha: bool
    bloqueado_ate: datetime | None
    versao: int


@dataclass(frozen=True, slots=True)
class UsuarioCriado:
    """A senha provisória é mostrada uma vez, a quem criou; o banco guarda só o hash."""

    id: int
    senha_provisoria: str


class UsuarioService(Protocol):
    def consultar(self, contexto: Contexto) -> list[UsuarioResumo]: ...

    def criar(self, contexto: Contexto, nome: str, login: str, perfil: Perfil) -> UsuarioCriado: ...

    def alterar_perfil(self, contexto: Contexto, usuario_id: int, versao: int, perfil: Perfil) -> None: ...

    def inativar(self, contexto: Contexto, usuario_id: int, versao: int) -> None:
        """Nunca exclui (RF-1005); as sessões do usuário acabam na mesma transação (UsuarioInativado)."""
        ...

    def reativar(self, contexto: Contexto, usuario_id: int, versao: int) -> None: ...

    def redefinir_senha(self, contexto: Contexto, usuario_id: int, versao: int) -> str:
        """Devolve a senha provisória, com troca obrigatória na próxima entrada."""
        ...

    def registrar_termo(self, contexto: Contexto, usuario_id: int, versao: int) -> None:
        """O TI registra que o usuário assinou o termo de ciência de uso (DEC-47)."""
        ...


class SessionManager(Protocol):
    def validar(self, token: str, origem: str, automatica: bool = False) -> Contexto:
        """Contexto da requisição, ou SessaoEncerrada. Inatividade e limite absoluto pelos parâmetros; a
        requisição automática da tela não renova a inatividade (DD-19, DD-57)."""
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
