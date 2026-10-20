"""Repositório do MOD-04 Documentos (SQL)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from sar.modulo_08_dados.interfaces.documentos import (
    DocumentoGravado,
    EstadoIngestao,
    IngestaoGravada,
    Origem,
    TipoGravado,
)
from sar.modulo_08_dados.modelos.cadastro import Paciente
from sar.modulo_08_dados.modelos.documentos import Documento, Ingestao, TipoDocumento


def _utc(instante: datetime | None) -> datetime | None:
    return instante.replace(tzinfo=UTC) if instante is not None else None


def _gravar(instante: datetime | None) -> datetime | None:
    return instante.astimezone(UTC).replace(tzinfo=None) if instante is not None else None


def _ingestao(i: Ingestao) -> IngestaoGravada:
    return IngestaoGravada(
        i.id, i.paciente_id, i.tipo, cast(Origem, i.origem), i.vinculo, i.substitui_id, cast(EstadoIngestao, i.estado),
        i.motivo_rejeicao, i.token_hash, i.hash_entrada, i.hash_reconstruido, i.paginas, i.campos_candidatos_cifrados,
        i.documento_id, i.criada_em.replace(tzinfo=UTC), i.criada_por, i.atualizada_em.replace(tzinfo=UTC),
    )  # fmt: skip


def _documento(d: Documento) -> DocumentoGravado:
    return DocumentoGravado(
        d.id, d.paciente_id, d.tipo, d.versao, d.substitui_id, d.arquivo, d.chave_cifrada, d.nonce, d.hash_sha256,
        d.paginas, cast(Origem, d.origem), d.capturado_em.replace(tzinfo=UTC), d.capturado_por, d.local_digitalizacao,
        _utc(d.descartado_em), _utc(d.bloqueado_em), d.bloqueio_motivo,
    )  # fmt: skip


class RepositorioDocumentosSQL:
    def __init__(self, sessao: Session) -> None:
        self._s = sessao

    # ---------------------------------------------------------------- tipos e pacientes
    def tipo(self, codigo: str) -> TipoGravado | None:
        t = self._s.get(TipoDocumento, codigo)
        if t is None:
            return None
        campos = tuple(c.strip() for c in (t.campos_extracao or "").split(",") if c.strip())
        return TipoGravado(t.codigo, t.nome, t.familia, t.anos_retencao, cast(Origem, t.origem), campos)

    def paciente_ativo(self, paciente_id: int) -> bool:
        anulado = self._s.execute(select(Paciente.anulado_em).where(Paciente.id == paciente_id)).first()
        return anulado is not None and anulado[0] is None

    # ---------------------------------------------------------------- ingestões
    def criar_ingestao(self, ingestao: IngestaoGravada) -> None:
        self._s.add(
            Ingestao(
                id=ingestao.id, paciente_id=ingestao.paciente_id, tipo=ingestao.tipo, origem=ingestao.origem,
                vinculo=ingestao.vinculo, substitui_id=ingestao.substitui_id, estado=ingestao.estado,
                motivo_rejeicao=ingestao.motivo_rejeicao, token_hash=ingestao.token_hash,
                hash_entrada=ingestao.hash_entrada, hash_reconstruido=ingestao.hash_reconstruido,
                paginas=ingestao.paginas, campos_candidatos_cifrados=ingestao.campos_candidatos_cifrados,
                documento_id=ingestao.documento_id, criada_em=_gravar(ingestao.criada_em),
                criada_por=ingestao.criada_por, atualizada_em=_gravar(ingestao.atualizada_em),
            )
        )  # fmt: skip
        self._s.flush()

    def ingestao(self, ingestao_id: bytes, travar: bool = False) -> IngestaoGravada | None:
        consulta = select(Ingestao).where(Ingestao.id == ingestao_id)
        if travar:
            consulta = consulta.with_for_update()
        linha = self._s.scalars(consulta).first()
        return _ingestao(linha) if linha is not None else None

    def salvar_ingestao(self, ingestao: IngestaoGravada) -> None:
        self._s.execute(
            update(Ingestao)
            .where(Ingestao.id == ingestao.id)
            .values(
                estado=ingestao.estado, motivo_rejeicao=ingestao.motivo_rejeicao, token_hash=ingestao.token_hash,
                hash_entrada=ingestao.hash_entrada, hash_reconstruido=ingestao.hash_reconstruido,
                paginas=ingestao.paginas, campos_candidatos_cifrados=ingestao.campos_candidatos_cifrados,
                documento_id=ingestao.documento_id, atualizada_em=_gravar(ingestao.atualizada_em),
            )
        )  # fmt: skip

    def tomar_da_fila(self) -> IngestaoGravada | None:
        consulta = (
            select(Ingestao)
            .where(Ingestao.estado == "recebida")
            .order_by(Ingestao.criada_em, Ingestao.id)  # desempate estável
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        linha = self._s.scalars(consulta).first()
        return _ingestao(linha) if linha is not None else None

    def em_estado(self, estados: Sequence[EstadoIngestao]) -> list[IngestaoGravada]:
        consulta = select(Ingestao).where(Ingestao.estado.in_(estados)).order_by(Ingestao.criada_em)
        return [_ingestao(i) for i in self._s.scalars(consulta)]

    def criadas_antes(self, estados: Sequence[EstadoIngestao], limite: datetime) -> list[IngestaoGravada]:
        consulta = select(Ingestao).where(Ingestao.estado.in_(estados), Ingestao.criada_em < _gravar(limite))
        return [_ingestao(i) for i in self._s.scalars(consulta.order_by(Ingestao.criada_em))]

    def ids_de_ingestoes(self, ids: Sequence[bytes]) -> dict[bytes, EstadoIngestao]:
        if not ids:
            return {}
        linhas = self._s.execute(select(Ingestao.id, Ingestao.estado).where(Ingestao.id.in_(ids)))
        return {id_: cast(EstadoIngestao, estado) for id_, estado in linhas}

    # ---------------------------------------------------------------- documentos
    def criar_documento(self, documento: DocumentoGravado) -> None:
        self._s.add(
            Documento(
                id=documento.id, paciente_id=documento.paciente_id, tipo=documento.tipo, versao=documento.versao,
                substitui_id=documento.substitui_id, arquivo=documento.arquivo, chave_cifrada=documento.chave_cifrada,
                nonce=documento.nonce, hash_sha256=documento.hash_sha256, paginas=documento.paginas,
                origem=documento.origem, capturado_em=_gravar(documento.capturado_em),
                capturado_por=documento.capturado_por, local_digitalizacao=documento.local_digitalizacao,
                descartado_em=_gravar(documento.descartado_em), bloqueado_em=_gravar(documento.bloqueado_em),
                bloqueio_motivo=documento.bloqueio_motivo,
            )
        )  # fmt: skip
        self._s.flush()

    def documento(self, documento_id: bytes) -> DocumentoGravado | None:
        linha = self._s.get(Documento, documento_id)
        return _documento(linha) if linha is not None else None

    def documento_com_hash(self, hash_sha256: str) -> bytes | None:
        return self._s.scalar(select(Documento.id).where(Documento.hash_sha256 == hash_sha256))

    def sucessor(self, documento_id: bytes) -> bytes | None:
        return self._s.scalar(select(Documento.id).where(Documento.substitui_id == documento_id))
