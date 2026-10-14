"""Repositórios de convênios e municípios (SQL)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from sar.modulo_08_dados.interfaces.referencias import DadosConvenio, DadosMunicipio
from sar.modulo_08_dados.modelos.configuracao import Convenio, Municipio


def _convenio(linha: Convenio) -> DadosConvenio:
    return DadosConvenio(linha.id, linha.nome, linha.ativo)


def _municipio(linha: Municipio) -> DadosMunicipio:
    return DadosMunicipio(linha.codigo_ibge, linha.nome, linha.uf)


def _escapar_like(termo: str) -> str:
    return termo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class RepositorioConvenioSQL:
    def __init__(self, sessao: Session) -> None:
        self._s = sessao

    def listar(self) -> list[DadosConvenio]:
        return [_convenio(linha) for linha in self._s.scalars(select(Convenio).order_by(Convenio.nome, Convenio.id))]

    def por_id(self, id: int, travar: bool = False) -> DadosConvenio | None:
        consulta = select(Convenio).where(Convenio.id == id)
        linha = self._s.scalars(consulta.with_for_update() if travar else consulta).one_or_none()
        return _convenio(linha) if linha is not None else None

    def por_nome(self, nome: str) -> DadosConvenio | None:
        linha = self._s.scalars(select(Convenio).where(Convenio.nome == nome)).first()
        return _convenio(linha) if linha is not None else None

    def criar(self, nome: str) -> int:
        linha = Convenio(nome=nome, ativo=True)
        self._s.add(linha)
        self._s.flush()
        return linha.id

    def alterar(self, id: int, nome: str, ativo: bool) -> None:
        linha = self._s.get_one(Convenio, id)
        linha.nome, linha.ativo = nome, ativo
        self._s.flush()


class RepositorioMunicipioSQL:
    def __init__(self, sessao: Session) -> None:
        self._s = sessao

    def por_codigo(self, codigo: str) -> DadosMunicipio | None:
        linha = self._s.get(Municipio, codigo)
        return _municipio(linha) if linha is not None else None

    def da_uf(self, uf: str) -> list[DadosMunicipio]:
        consulta = select(Municipio).where(Municipio.uf == uf).order_by(Municipio.nome)
        return [_municipio(linha) for linha in self._s.scalars(consulta)]

    def buscar(self, termo: str, uf: str | None, limite: int) -> list[DadosMunicipio]:
        consulta = select(Municipio).where(Municipio.nome.like(f"{_escapar_like(termo)}%", escape="\\"))
        if uf is not None:
            consulta = consulta.where(Municipio.uf == uf)
        consulta = consulta.order_by(Municipio.nome, Municipio.uf).limit(limite)
        return [_municipio(linha) for linha in self._s.scalars(consulta)]
