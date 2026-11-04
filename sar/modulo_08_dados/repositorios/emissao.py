"""Repositórios de modelos de documento e emissões (SQL)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from sar.modulo_08_dados.interfaces.emissao import DadosEmissao, DadosVersaoModelo
from sar.modulo_08_dados.modelos.emissao import EmissaoDocumento, ModeloDocumento

_COLUNAS = (
    ModeloDocumento.codigo,
    ModeloDocumento.versao,
    ModeloDocumento.hash_sha256,
    ModeloDocumento.enviado_em,
    ModeloDocumento.enviado_por,
    ModeloDocumento.ativo,
    ModeloDocumento.ativado_em,
)


def _gravar(instante: datetime) -> datetime:
    return instante.astimezone(UTC).replace(tzinfo=None)


def _versao(linha: tuple[str, int, str, datetime, int, bool, datetime | None]) -> DadosVersaoModelo:
    codigo, versao, hash_sha256, enviado_em, enviado_por, ativo, ativado_em = linha
    return DadosVersaoModelo(codigo, versao, hash_sha256, enviado_em.replace(tzinfo=UTC), enviado_por, bool(ativo),
                             ativado_em.replace(tzinfo=UTC) if ativado_em is not None else None)  # fmt: skip


class RepositorioModeloSQL:
    def __init__(self, sessao: Session) -> None:
        self._s = sessao

    def versoes(self, codigo: str) -> list[DadosVersaoModelo]:
        consulta = select(*_COLUNAS).where(ModeloDocumento.codigo == codigo).order_by(ModeloDocumento.versao.desc())
        return [_versao(tuple(linha)) for linha in self._s.execute(consulta)]

    def arquivo(self, codigo: str, versao: int) -> bytes | None:
        consulta = select(ModeloDocumento.arquivo).where(
            ModeloDocumento.codigo == codigo, ModeloDocumento.versao == versao
        )
        return self._s.scalar(consulta)

    def ativo(self, codigo: str) -> DadosVersaoModelo | None:
        consulta = select(*_COLUNAS).where(ModeloDocumento.codigo == codigo, ModeloDocumento.ativo.is_(True))
        linha = self._s.execute(consulta).one_or_none()
        return _versao(tuple(linha)) if linha is not None else None

    def travar(self, codigo: str) -> None:
        self._s.execute(select(ModeloDocumento.id).where(ModeloDocumento.codigo == codigo).with_for_update())

    def criar(self, codigo: str, versao: int, arquivo: bytes, hash_sha256: str, em: datetime, por: int) -> None:
        self._s.add(ModeloDocumento(codigo=codigo, versao=versao, arquivo=arquivo, hash_sha256=hash_sha256,
                                    enviado_em=_gravar(em), enviado_por=por, ativo=False))  # fmt: skip
        self._s.flush()

    def ativar(self, codigo: str, versao: int | None, em: datetime, por: int) -> None:
        # Desativa antes de ativar: a restrição de um ativo por código vale a cada comando (uq_..._um_ativo).
        self._s.execute(
            update(ModeloDocumento)
            .where(ModeloDocumento.codigo == codigo, ModeloDocumento.ativo.is_(True))
            .values(ativo=False)
        )
        if versao is not None:
            self._s.execute(
                update(ModeloDocumento)
                .where(ModeloDocumento.codigo == codigo, ModeloDocumento.versao == versao)
                .values(ativo=True, ativado_em=_gravar(em), ativado_por=por)
            )


class RepositorioEmissaoSQL:
    def __init__(self, sessao: Session) -> None:
        self._s = sessao

    def registrar(self, emissao: DadosEmissao) -> None:
        self._s.add(EmissaoDocumento(paciente_id=emissao.paciente_id, modelo=emissao.modelo,
                                     versao_modelo=emissao.versao_modelo, referencia=emissao.referencia,
                                     competencia=emissao.competencia, emitido_em=_gravar(emissao.emitido_em),
                                     emitido_por=emissao.emitido_por))  # fmt: skip
        self._s.flush()

    def do_mes(self, paciente_id: int, competencia: str, modelo: str) -> int:
        consulta = select(func.count()).where(
            EmissaoDocumento.paciente_id == paciente_id,
            EmissaoDocumento.competencia == competencia,
            EmissaoDocumento.modelo == modelo,
        )
        return int(self._s.scalar(consulta) or 0)
