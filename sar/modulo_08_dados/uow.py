"""Unidade de trabalho sobre SQLAlchemy (DDS §3.3, §12.1). Implementa as portas UnidadeDeTrabalho e
ExecutorDeOperacao do núcleo."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Self, TypeVar, cast

from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from sar.modulo_08_dados.erros_banco import anotar_restricao
from sar.nucleo.eventos import Barramento, EventoDominio
from sar.nucleo.logs import campos_do_erro
from sar.nucleo.uow import RegistroAuditoria, UnidadeDeTrabalho

R = TypeVar("R")

log = logging.getLogger(__name__)

GravadorAuditoria = Callable[[Session, Sequence[RegistroAuditoria]], None]
"""Grava os registros acumulados na mesma transação, antes do commit. A cadeia encadeada (DD-03, DD-71)
chega com o MOD-01; até lá, só existem gravadores de teste."""

FabricaRepositorio = Callable[[Session], object]

TENTATIVAS = 3  # DD-59
ERROS_REPETIVEIS = {1205, 1213}  # ER_LOCK_WAIT_TIMEOUT, ER_LOCK_DEADLOCK


class UnidadeDeTrabalhoSQL:
    """Uma operação, uma transação. Sem confirmar(), a saída do bloco desfaz tudo."""

    def __init__(
        self,
        engine: Engine,
        barramento: Barramento,
        gravar_auditoria: GravadorAuditoria,
        repositorios: Mapping[type, FabricaRepositorio],
    ) -> None:
        self._engine = engine
        self._barramento = barramento
        self._gravar_auditoria = gravar_auditoria
        self._fabricas = repositorios
        self._sessao: Session | None = None
        self._repositorios: dict[type, object] = {}
        self._eventos: list[EventoDominio] = []
        self._auditoria: list[RegistroAuditoria] = []
        self._depois: list[Callable[[], None]] = []
        self._confirmada = False

    @property
    def sessao(self) -> Session:
        """Para os repositórios do MOD-08; nunca sai deste módulo."""
        if self._sessao is None:
            raise RuntimeError("unidade de trabalho fora do bloco with")
        return self._sessao

    @property
    def confirmada(self) -> bool:
        return self._confirmada

    def __enter__(self) -> Self:
        if self._sessao is not None or self._confirmada:
            raise RuntimeError("unidade de trabalho já usada")
        self._sessao = Session(self._engine, autoflush=True, expire_on_commit=False)
        return self

    def __exit__(self, *exc: object) -> None:
        sessao = self.sessao
        try:
            if not self._confirmada:
                sessao.rollback()
        finally:
            sessao.close()
            self._sessao = None
            self._depois.clear()

    def repositorio(self, tipo: type[R]) -> R:
        if tipo not in self._repositorios:
            try:
                fabrica = self._fabricas[tipo]
            except KeyError:
                raise LookupError(f"repositório não registrado: {tipo.__name__}") from None
            self._repositorios[tipo] = fabrica(self.sessao)
        return cast(R, self._repositorios[tipo])

    def publicar(self, evento: EventoDominio) -> None:
        self._exigir_aberta()
        self._eventos.append(evento)

    def auditar(self, registro: RegistroAuditoria) -> None:
        self._exigir_aberta()
        self._auditoria.append(registro)

    def depois_do_commit(self, acao: Callable[[], None]) -> None:
        self._exigir_aberta()
        self._depois.append(acao)

    def confirmar(self) -> None:
        """Eventos (DD-15) → auditoria (DD-03) → commit → ações de depois do commit."""
        self._exigir_aberta()
        sessao = self.sessao
        # Manipuladores podem publicar novos eventos e registrar auditoria: tudo entra antes do commit.
        while self._eventos:
            self._barramento.despachar(self, self._eventos.pop(0))
        sessao.flush()
        if self._auditoria:
            self._gravar_auditoria(sessao, tuple(self._auditoria))
        sessao.commit()
        self._confirmada = True
        acoes, self._depois = self._depois, []
        for acao in acoes:
            try:
                acao()
            except Exception as erro:
                # A operação já foi confirmada: a falha não pode desfazê-la nem repeti-la. Só o tipo do erro
                # (DD-81); a mensagem pode conter dado pessoal (RNF-624).
                log.error("uow.depois_do_commit.falhou", extra=campos_do_erro(erro))

    def _exigir_aberta(self) -> None:
        if self._sessao is None or self._confirmada:
            raise RuntimeError("unidade de trabalho não está aberta")


def e_repetivel(erro: DBAPIError) -> bool:
    """Impasse ou tempo de trava esgotado (DD-59)."""
    argumentos: tuple[object, ...] = getattr(erro.orig, "args", ())
    return bool(argumentos) and argumentos[0] in ERROS_REPETIVEIS


class ExecutorSQL:
    def __init__(self, fabrica: Callable[[], UnidadeDeTrabalhoSQL], tentativas: int = TENTATIVAS) -> None:
        self._fabrica = fabrica
        self._tentativas = tentativas

    def __call__(self, operacao: Callable[[UnidadeDeTrabalho], R]) -> R:
        for tentativa in range(1, self._tentativas + 1):
            uow = self._fabrica()
            try:
                with uow:
                    resultado = operacao(uow)
                    if not uow.confirmada:
                        uow.confirmar()
                return resultado
            except DBAPIError as erro:
                if tentativa == self._tentativas or not e_repetivel(erro):
                    anotar_restricao(erro)
                    raise
                log.warning(
                    "uow.impasse.repetido", extra={"resultado": f"tentativa_{tentativa + 1}_de_{self._tentativas}"}
                )
        raise AssertionError("inalcançável")
