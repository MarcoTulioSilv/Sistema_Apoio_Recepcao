"""Repositório da carga inicial (SQL)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from sar.modulo_08_dados.interfaces.carga import DadosConferencia, DadosLinha, DadosLote
from sar.modulo_08_dados.modelos.carga import CargaConferencia, CargaLinha, CargaLote


def _gravar(instante: datetime) -> datetime:
    return instante.astimezone(UTC).replace(tzinfo=None)


def _ler(instante: datetime | None) -> datetime | None:
    return instante.replace(tzinfo=UTC) if instante is not None else None


def _lote(linha: CargaLote) -> DadosLote:
    return DadosLote(
        linha.id, linha.modo, linha.situacao, linha.contagens, linha.iniciado_em.replace(tzinfo=UTC),
        _ler(linha.concluido_em), _ler(linha.aceito_em), linha.aceito_por, linha.ativos_confirmados,
    )  # fmt: skip


def _linha(linha: CargaLinha) -> DadosLinha:
    return DadosLinha(
        linha.id, linha.lote_id, linha.planilha, linha.numero_linha, linha.conteudo_cifrado, linha.nonce,
        linha.paciente_id, linha.excecao_codigo, linha.excecao_tratada, linha.excecao_motivo,
        tuple(linha.avisos or ()), linha.amostra_rodada,
    )  # fmt: skip


class RepositorioCargaSQL:
    def __init__(self, sessao: Session) -> None:
        self._s = sessao

    def efetivacao(self, travar: bool = False) -> DadosLote | None:
        consulta = select(CargaLote).where(CargaLote.modo == "efetivacao", CargaLote.situacao != "falhou")
        linha = self._s.scalars(consulta.with_for_update() if travar else consulta).one_or_none()
        return _lote(linha) if linha is not None else None

    def ultimo_lote(self) -> DadosLote | None:
        efetivada = self.efetivacao()
        if efetivada is not None:
            return efetivada
        consulta = select(CargaLote).where(CargaLote.modo == "simulacao").order_by(CargaLote.id.desc()).limit(1)
        linha = self._s.scalars(consulta).one_or_none()
        return _lote(linha) if linha is not None else None

    def criar_lote(self, modo: str, iniciado_em: datetime) -> int:
        linha = CargaLote(modo=modo, situacao="em_andamento", iniciado_em=_gravar(iniciado_em))
        self._s.add(linha)
        self._s.flush()
        return linha.id

    def concluir_lote(self, lote_id: int, situacao: str, contagens: dict[str, Any], em: datetime) -> None:
        linha = self._s.get_one(CargaLote, lote_id)
        linha.situacao, linha.contagens, linha.concluido_em = situacao, contagens, _gravar(em)
        self._s.flush()

    def apagar_linhas_de_simulacao(self) -> int:
        simulacoes = select(CargaLote.id).where(CargaLote.modo == "simulacao")
        resultado = self._s.execute(delete(CargaLinha).where(CargaLinha.lote_id.in_(simulacoes)))
        return int(getattr(resultado, "rowcount", 0) or 0)

    def criar_linha(
        self,
        lote_id: int,
        planilha: str,
        numero_linha: int,
        cifrado: bytes,
        nonce: bytes,
        paciente_id: int | None,
        excecao_codigo: str | None,
        avisos: Sequence[str],
    ) -> int:
        linha = CargaLinha(
            lote_id=lote_id, planilha=planilha, numero_linha=numero_linha, conteudo_cifrado=cifrado, nonce=nonce,
            paciente_id=paciente_id, excecao_codigo=excecao_codigo, avisos=list(avisos) or None,
        )  # fmt: skip
        self._s.add(linha)
        self._s.flush()
        return linha.id

    def linhas(self, lote_id: int) -> list[DadosLinha]:
        consulta = (
            select(CargaLinha)
            .where(CargaLinha.lote_id == lote_id)
            .order_by(CargaLinha.planilha, CargaLinha.numero_linha)
        )
        return [_linha(linha) for linha in self._s.scalars(consulta)]

    def linha(self, linha_id: int, travar: bool = False) -> DadosLinha | None:
        consulta = select(CargaLinha).where(CargaLinha.id == linha_id)
        linha = self._s.scalars(consulta.with_for_update() if travar else consulta).one_or_none()
        return _linha(linha) if linha is not None else None

    def tratar(self, linha_id: int, tratamento: str, motivo: str, paciente_id: int | None) -> None:
        linha = self._s.get_one(CargaLinha, linha_id)
        linha.excecao_tratada, linha.excecao_motivo = tratamento, motivo
        if paciente_id is not None:
            linha.paciente_id = paciente_id
        self._s.flush()

    def marcar_amostra(self, linha_ids: Sequence[int], rodada: int) -> None:
        if linha_ids:
            self._s.execute(update(CargaLinha).where(CargaLinha.id.in_(linha_ids)).values(amostra_rodada=rodada))

    def conferencias(self) -> list[DadosConferencia]:
        consulta = select(CargaConferencia).order_by(CargaConferencia.paciente_id, CargaConferencia.campo)
        return [
            DadosConferencia(c.paciente_id, c.campo, c.resultado, c.conferido_por, c.conferido_em.replace(tzinfo=UTC))
            for c in self._s.scalars(consulta)
        ]

    def registrar_conferencia(self, paciente_id: int, campo: str, resultado: str, por: int, em: datetime) -> bool:
        consulta = select(CargaConferencia).where(
            CargaConferencia.paciente_id == paciente_id, CargaConferencia.campo == campo
        )
        atual = self._s.scalars(consulta.with_for_update()).one_or_none()
        if atual is None:
            self._s.add(CargaConferencia(paciente_id=paciente_id, campo=campo, resultado=resultado,
                                         conferido_por=por, conferido_em=_gravar(em)))  # fmt: skip
        elif atual.resultado == resultado:
            return False
        else:
            atual.resultado, atual.conferido_por, atual.conferido_em = resultado, por, _gravar(em)
        self._s.flush()
        return True

    def aceitar(self, lote_id: int, em: datetime, por: int, ativos_confirmados: int) -> None:
        linha = self._s.get_one(CargaLote, lote_id)
        linha.situacao, linha.aceito_em, linha.aceito_por = "aceita", _gravar(em), por
        linha.ativos_confirmados = ativos_confirmados
        self._s.flush()

    def apagar_area_de_trabalho(self) -> tuple[int, int]:
        linhas = self._s.execute(delete(CargaLinha))
        conferencias = self._s.execute(delete(CargaConferencia))
        return int(getattr(linhas, "rowcount", 0) or 0), int(getattr(conferencias, "rowcount", 0) or 0)
