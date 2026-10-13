"""Repositórios da trilha de auditoria (SQL). Instantes gravados sem fuso, em UTC (§12.2); devolvidos com fuso."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, aliased

from sar.modulo_08_dados.interfaces.trilha import Ancora, Aviso, Cabeca, Corte, Elo, FiltroTrilha, RegistroConsultado
from sar.modulo_08_dados.modelos.acesso import (
    Auditoria,
    AuditoriaAncora,
    AuditoriaCabeca,
    AuditoriaCorte,
    AvisoIntegridade,
    Usuario,
)

LOTE = 1000


def _utc(valor: datetime) -> datetime:
    return valor.replace(tzinfo=UTC)


def _opcional_utc(valor: datetime | None) -> datetime | None:
    return _utc(valor) if valor is not None else None


def _banco(valor: datetime) -> datetime:
    return valor.astimezone(UTC).replace(tzinfo=None)


def _elo(linha: Auditoria) -> Elo:
    return Elo(
        id=linha.id,
        instante=_utc(linha.instante),
        usuario_id=linha.usuario_id,
        autorizador_id=linha.autorizador_id,
        operacao=linha.operacao,
        entidade=linha.entidade,
        entidade_id=linha.entidade_id,
        alteracoes=linha.alteracoes,
        motivo=linha.motivo,
        origem=linha.origem,
        sessao_id=linha.sessao_id,
        requisicao_id=linha.requisicao_id,
        versao_formato=linha.versao_formato,
        hash_anterior=linha.hash_anterior,
        hash_registro=linha.hash_registro,
    )


def _ancora(linha: AuditoriaAncora) -> Ancora:
    return Ancora(linha.id, linha.ate_registro_id, linha.hash, _utc(linha.registrada_em))


def _aviso(linha: AvisoIntegridade) -> Aviso:
    return Aviso(
        linha.id,
        _utc(linha.detectado_em),
        linha.registro_divergente_id,
        _opcional_utc(linha.encerrado_em),
        linha.encerrado_por,
        linha.explicacao,
    )


class RepositorioTrilhaSQL:
    def __init__(self, sessao: Session) -> None:
        self._s = sessao

    def consultar(self, filtro: FiltroTrilha, limite: int) -> list[RegistroConsultado]:
        autor, autorizador = aliased(Usuario), aliased(Usuario)
        consulta = (
            select(Auditoria, autor.nome, autorizador.nome)
            .outerjoin(autor, autor.id == Auditoria.usuario_id)
            .outerjoin(autorizador, autorizador.id == Auditoria.autorizador_id)
            .order_by(Auditoria.id.desc())
            .limit(limite)
        )
        if filtro.desde is not None:
            consulta = consulta.where(Auditoria.instante >= _banco(filtro.desde))
        if filtro.ate is not None:
            consulta = consulta.where(Auditoria.instante < _banco(filtro.ate))
        if filtro.usuario_id is not None:
            consulta = consulta.where(Auditoria.usuario_id == filtro.usuario_id)
        if filtro.operacao_prefixo:
            consulta = consulta.where(Auditoria.operacao.startswith(filtro.operacao_prefixo, autoescape=True))
        if filtro.entidade:
            consulta = consulta.where(Auditoria.entidade == filtro.entidade)
        if filtro.entidade_id:
            consulta = consulta.where(Auditoria.entidade_id == filtro.entidade_id)
        if filtro.antes_de_id is not None:
            consulta = consulta.where(Auditoria.id < filtro.antes_de_id)
        return [
            RegistroConsultado(_elo(linha), nome, nome_autorizador)
            for linha, nome, nome_autorizador in self._s.execute(consulta)
        ]

    def cabeca(self) -> Cabeca:
        c = self._s.get_one(AuditoriaCabeca, 1)
        return Cabeca(c.ultimo_registro_id, c.ultimo_hash)

    def ultimo_corte(self) -> Corte | None:
        c = self._s.scalars(select(AuditoriaCorte).order_by(AuditoriaCorte.id.desc()).limit(1)).first()
        if c is None:
            return None
        return Corte(c.primeiro_id_remanescente, c.hash_anterior, _utc(c.executado_em), c.registros_expurgados)

    def elos(self, de_id: int, ate_id: int) -> Iterator[Elo]:
        proximo = de_id
        while proximo <= ate_id:
            lote = list(
                self._s.scalars(
                    select(Auditoria)
                    .where(Auditoria.id >= proximo, Auditoria.id <= ate_id)
                    .order_by(Auditoria.id)
                    .limit(LOTE)
                )
            )
            if not lote:
                return
            proximo = lote[-1].id + 1
            for linha in lote:
                self._s.expunge(linha)  # o lote lido não fica preso na sessão
                yield _elo(linha)

    def elo(self, id: int) -> Elo | None:
        linha = self._s.get(Auditoria, id)
        return _elo(linha) if linha is not None else None

    def ancoras(self, a_partir_de_id: int) -> list[Ancora]:
        linhas = self._s.scalars(
            select(AuditoriaAncora)
            .where(AuditoriaAncora.ate_registro_id >= a_partir_de_id)
            .order_by(AuditoriaAncora.id)
        )
        return [_ancora(linha) for linha in linhas]

    def ancora_mais_recente(self) -> Ancora | None:
        linha = self._s.scalars(select(AuditoriaAncora).order_by(AuditoriaAncora.id.desc()).limit(1)).first()
        return _ancora(linha) if linha is not None else None

    def ancora_do_registro(self, registro_id: int) -> Ancora | None:
        linha = self._s.scalars(
            select(AuditoriaAncora)
            .where(AuditoriaAncora.ate_registro_id == registro_id)
            .order_by(AuditoriaAncora.id.desc())
            .limit(1)
        ).first()
        return _ancora(linha) if linha is not None else None

    def registrar_ancora(self, ate_registro_id: int, hash: str, em: datetime) -> int:
        linha = AuditoriaAncora(ate_registro_id=ate_registro_id, hash=hash, registrada_em=_banco(em))
        self._s.add(linha)
        self._s.flush()
        return linha.id

    def avisos_abertos(self) -> list[Aviso]:
        linhas = self._s.scalars(
            select(AvisoIntegridade).where(AvisoIntegridade.encerrado_em.is_(None)).order_by(AvisoIntegridade.id)
        )
        return [_aviso(linha) for linha in linhas]

    def aviso(self, id: int) -> Aviso | None:
        linha = self._s.get(AvisoIntegridade, id)
        return _aviso(linha) if linha is not None else None

    def abrir_aviso(self, registro_divergente_id: int, em: datetime) -> int:
        linha = AvisoIntegridade(registro_divergente_id=registro_divergente_id, detectado_em=_banco(em))
        self._s.add(linha)
        self._s.flush()
        return linha.id

    def encerrar_aviso(self, id: int, usuario_id: int, em: datetime, explicacao: str) -> None:
        linha = self._s.get_one(AvisoIntegridade, id)
        linha.encerrado_em, linha.encerrado_por, linha.explicacao = _banco(em), usuario_id, explicacao
        self._s.flush()


class RepositorioExpurgoSQL:
    def __init__(self, sessao: Session) -> None:
        self._s = sessao

    def ultimo_elo_antes_de(self, limite: datetime) -> tuple[int, str] | None:
        linha = self._s.execute(
            select(Auditoria.id, Auditoria.hash_registro)
            .where(Auditoria.instante < _banco(limite))
            .order_by(Auditoria.id.desc())
            .limit(1)
        ).first()
        return (linha.id, linha.hash_registro) if linha is not None else None

    def contar_ate(self, id: int) -> int:
        return int(self._s.scalar(select(func.count()).select_from(Auditoria).where(Auditoria.id <= id)) or 0)

    def apagar_ate(self, id: int) -> None:
        self._s.execute(delete(Auditoria).where(Auditoria.id <= id))

    def registrar_corte(self, primeiro_id_remanescente: int, hash_anterior: str, em: datetime, quantidade: int) -> None:
        self._s.add(
            AuditoriaCorte(
                primeiro_id_remanescente=primeiro_id_remanescente,
                hash_anterior=hash_anterior,
                executado_em=_banco(em),
                registros_expurgados=quantidade,
            )
        )
        self._s.flush()
