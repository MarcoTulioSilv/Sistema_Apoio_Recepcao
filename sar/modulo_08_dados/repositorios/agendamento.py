"""Repositório do registro de execução dos jobs (SQL) e a trava nomeada (GET_LOCK) do MySQL (DD-61)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import Engine, func, select, text, update
from sqlalchemy.orm import Session

from sar.modulo_08_dados.interfaces.agendamento import ExecucaoGravada
from sar.modulo_08_dados.modelos.agendamento import JobExecucao

TAMANHO_RESUMO = 300


def _gravar(instante: datetime) -> datetime:
    return instante.astimezone(UTC).replace(tzinfo=None)


def _lido(instante: datetime | None) -> datetime | None:
    return instante.replace(tzinfo=UTC) if instante is not None else None


def _dados(linha: JobExecucao) -> ExecucaoGravada:
    return ExecucaoGravada(linha.id, linha.job, linha.inicio.replace(tzinfo=UTC), _lido(linha.fim), linha.resultado,
                           linha.itens, linha.resumo_erro, linha.cursor)  # fmt: skip


class RepositorioAgendamentoSQL:
    def __init__(self, sessao: Session) -> None:
        self._s = sessao

    def abrir(self, job: str, inicio: datetime) -> int:
        linha = JobExecucao(job=job, inicio=_gravar(inicio), resultado="em_andamento")
        self._s.add(linha)
        self._s.flush()
        return linha.id

    def fechar(
        self, id: int, fim: datetime, resultado: str, itens: int | None, resumo_erro: str | None, cursor: str | None
    ) -> None:
        self._s.execute(
            update(JobExecucao).where(JobExecucao.id == id).values(
                fim=_gravar(fim), resultado=resultado, itens=itens,
                resumo_erro=resumo_erro[:TAMANHO_RESUMO] if resumo_erro else None, cursor=cursor,
            )
        )  # fmt: skip

    def registrar(
        self, job: str, inicio: datetime, fim: datetime, resultado: str, itens: int | None, resumo_erro: str | None
    ) -> int:
        linha = JobExecucao(job=job, inicio=_gravar(inicio), fim=_gravar(fim), resultado=resultado, itens=itens,
                            resumo_erro=resumo_erro[:TAMANHO_RESUMO] if resumo_erro else None)  # fmt: skip
        self._s.add(linha)
        self._s.flush()
        return linha.id

    def por_id(self, id: int) -> ExecucaoGravada:
        return _dados(self._s.get_one(JobExecucao, id))

    def ultimos_sucessos(self, jobs: list[str] | None = None) -> dict[str, datetime]:
        consulta = (
            select(JobExecucao.job, func.max(JobExecucao.inicio))
            .where(JobExecucao.resultado.in_(("sucesso", "sem_trabalho")), JobExecucao.cursor.is_(None))
            .group_by(JobExecucao.job)
        )
        if jobs is not None:
            consulta = consulta.where(JobExecucao.job.in_(jobs))
        return {job: inicio.replace(tzinfo=UTC) for job, inicio in self._s.execute(consulta)}

    def ultima(self, job: str, resultado: str | None = None) -> ExecucaoGravada | None:
        consulta = select(JobExecucao).where(JobExecucao.job == job)
        if resultado is not None:
            consulta = consulta.where(JobExecucao.resultado == resultado)
        linha = self._s.scalars(consulta.order_by(JobExecucao.inicio.desc(), JobExecucao.id.desc()).limit(1)).first()
        return _dados(linha) if linha is not None else None

    def recentes(self, limite: int, job: str | None = None) -> list[ExecucaoGravada]:
        consulta = select(JobExecucao)
        if job is not None:
            consulta = consulta.where(JobExecucao.job == job)
        consulta = consulta.order_by(JobExecucao.inicio.desc(), JobExecucao.id.desc()).limit(limite)
        return [_dados(linha) for linha in self._s.scalars(consulta)]


class TravaMySQL:
    """GET_LOCK numa conexão própria, que fica aberta enquanto o job roda. O nome leva o banco, para o banco de
    testes e o da aplicação no mesmo servidor não se travarem um ao outro."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def obter(self, nome: str, espera_segundos: float) -> Iterator[bool]:
        with self._engine.connect() as conexao:
            chave = conexao.execute(text("SELECT CONCAT(DATABASE(), ':', :n)"), {"n": nome}).scalar_one()
            obtida = conexao.execute(
                text("SELECT GET_LOCK(:c, :t)"), {"c": chave[:64], "t": max(0, int(espera_segundos))}
            ).scalar_one()
            conexao.commit()
            try:
                yield obtida == 1
            finally:
                if obtida == 1:
                    conexao.execute(text("SELECT RELEASE_LOCK(:c)"), {"c": chave[:64]})
                    conexao.commit()
