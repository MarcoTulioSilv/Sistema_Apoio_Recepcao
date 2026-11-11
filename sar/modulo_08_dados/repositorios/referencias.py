"""Repositórios dos dados de referência do MOD-06 (SQL): convênios, municípios, instituição e faixas etárias."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from sar.modulo_08_dados.interfaces.referencias import (
    DadosConvenio,
    DadosFaixaEtaria,
    DadosInstituicao,
    DadosMunicipio,
)
from sar.modulo_08_dados.modelos.configuracao import Convenio, FaixaEtaria, Instituicao, Municipio


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

    def com_prefixo(self, prefixo: str) -> list[DadosMunicipio]:
        consulta = select(Municipio).where(Municipio.codigo_ibge.like(f"{_escapar_like(prefixo)}%", escape="\\"))
        return [_municipio(linha) for linha in self._s.scalars(consulta.order_by(Municipio.codigo_ibge))]

    def da_uf(self, uf: str) -> list[DadosMunicipio]:
        consulta = select(Municipio).where(Municipio.uf == uf).order_by(Municipio.nome)
        return [_municipio(linha) for linha in self._s.scalars(consulta)]

    def buscar(self, termo: str, uf: str | None, limite: int) -> list[DadosMunicipio]:
        consulta = select(Municipio).where(Municipio.nome.like(f"{_escapar_like(termo)}%", escape="\\"))
        if uf is not None:
            consulta = consulta.where(Municipio.uf == uf)
        consulta = consulta.order_by(Municipio.nome, Municipio.uf).limit(limite)
        return [_municipio(linha) for linha in self._s.scalars(consulta)]


def _instituicao(linha: Instituicao, tem_logotipo: bool) -> DadosInstituicao:
    return DadosInstituicao(
        linha.nome, linha.endereco, linha.cep, linha.municipio_id, linha.uf, linha.telefone, linha.cnpj, tem_logotipo
    )


class RepositorioInstituicaoSQL:
    def __init__(self, sessao: Session) -> None:
        self._s = sessao

    def obter(self, travar: bool = False) -> DadosInstituicao | None:
        consulta = select(Instituicao, Instituicao.logotipo_tipo.is_not(None)).where(Instituicao.id == 1)
        linha = self._s.execute(consulta.with_for_update() if travar else consulta).one_or_none()
        return _instituicao(linha[0], bool(linha[1])) if linha is not None else None

    def gravar(self, dados: DadosInstituicao) -> None:
        linha = self._s.get(Instituicao, 1)
        if linha is None:
            linha = Instituicao(id=1)
            self._s.add(linha)
        linha.nome, linha.endereco, linha.cep = dados.nome, dados.endereco, dados.cep
        linha.municipio_id, linha.uf, linha.telefone, linha.cnpj = dados.municipio, dados.uf, dados.telefone, dados.cnpj
        self._s.flush()

    def gravar_logotipo(self, png: bytes) -> None:
        self._s.execute(update(Instituicao).where(Instituicao.id == 1).values(logotipo=png, logotipo_tipo="png"))

    def logotipo(self) -> bytes | None:
        return self._s.scalar(select(Instituicao.logotipo).where(Instituicao.id == 1))

    def faixas_etarias(self) -> list[DadosFaixaEtaria]:
        consulta = select(FaixaEtaria).order_by(FaixaEtaria.inicio)
        return [DadosFaixaEtaria(f.inicio, f.fim, f.rotulo) for f in self._s.scalars(consulta)]
