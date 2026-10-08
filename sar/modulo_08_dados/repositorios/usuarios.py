"""Repositório de usuários (SQL)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from sar.modulo_08_dados.interfaces.usuarios import DadosUsuario
from sar.modulo_08_dados.modelos.acesso import Usuario


def _utc(valor: datetime | None) -> datetime | None:
    return valor.replace(tzinfo=UTC) if valor is not None else None


def _dados(u: Usuario) -> DadosUsuario:
    return DadosUsuario(
        id=u.id,
        nome=u.nome,
        login=u.login,
        senha_hash=u.senha_hash,
        perfil=u.perfil,
        ativo=u.ativo,
        deve_trocar_senha=u.deve_trocar_senha,
        termo_ciencia_em=_utc(u.termo_ciencia_em),
        tentativas_falhas=u.tentativas_falhas,
        bloqueado_ate=_utc(u.bloqueado_ate),
        versao=u.versao,
    )


class RepositorioUsuarioSQL:
    def __init__(self, sessao: Session) -> None:
        self._s = sessao

    def por_login(self, login: str) -> DadosUsuario | None:
        u = self._s.scalars(select(Usuario).where(Usuario.login == login)).first()
        return _dados(u) if u is not None else None

    def por_id(self, id: int) -> DadosUsuario | None:
        u = self._s.get(Usuario, id)
        return _dados(u) if u is not None else None

    def travar(self, id: int) -> None:
        self._s.execute(select(Usuario.id).where(Usuario.id == id).with_for_update())

    def incrementar_falhas(self, id: int) -> int:
        self._s.execute(
            update(Usuario).where(Usuario.id == id).values(tentativas_falhas=Usuario.tentativas_falhas + 1),
            execution_options={"synchronize_session": False},
        )
        return int(self._s.scalar(select(Usuario.tentativas_falhas).where(Usuario.id == id)) or 0)

    def definir_bloqueio(self, id: int, ate: datetime | None) -> None:
        self._s.execute(
            update(Usuario)
            .where(Usuario.id == id)
            .values(bloqueado_ate=ate.astimezone(UTC).replace(tzinfo=None) if ate else None),
            execution_options={"synchronize_session": False},
        )

    def zerar_falhas(self, id: int) -> None:
        self._s.execute(
            update(Usuario).where(Usuario.id == id).values(tentativas_falhas=0, bloqueado_ate=None),
            execution_options={"synchronize_session": False},
        )

    def trocar_senha(self, id: int, senha_hash: str, deve_trocar: bool) -> None:
        self._s.execute(
            update(Usuario)
            .where(Usuario.id == id)
            .values(senha_hash=senha_hash, deve_trocar_senha=deve_trocar, versao=Usuario.versao + 1),
            execution_options={"synchronize_session": False},
        )

    def travar_ti_ativos(self) -> list[int]:
        consulta = select(Usuario.id).where(Usuario.perfil == "ti", Usuario.ativo.is_(True)).order_by(Usuario.id)
        return list(self._s.scalars(consulta.with_for_update()))

    def listar(self) -> list[DadosUsuario]:
        return [_dados(u) for u in self._s.scalars(select(Usuario).order_by(Usuario.nome, Usuario.id))]

    def criar(
        self, nome: str, login: str, senha_hash: str, perfil: str, em: datetime, termo_em: datetime | None
    ) -> int:
        usuario = Usuario(
            nome=nome,
            login=login,
            senha_hash=senha_hash,
            perfil=perfil,
            ativo=True,
            deve_trocar_senha=True,
            termo_ciencia_em=_banco(termo_em) if termo_em else None,
            criado_em=_banco(em),
        )
        self._s.add(usuario)
        self._s.flush()
        return usuario.id

    def _atualizar(self, id: int, versao: int, valores: dict[str, Any]) -> bool:
        resultado = self._s.execute(
            update(Usuario)
            .where(Usuario.id == id, Usuario.versao == versao)
            .values(**valores, versao=Usuario.versao + 1),
            execution_options={"synchronize_session": False},
        )
        return bool(getattr(resultado, "rowcount", 0) == 1)

    def alterar_perfil(self, id: int, versao: int, perfil: str) -> bool:
        return self._atualizar(id, versao, {"perfil": perfil})

    def definir_ativo(self, id: int, versao: int, ativo: bool) -> bool:
        return self._atualizar(id, versao, {"ativo": ativo})

    def redefinir_senha(self, id: int, versao: int, senha_hash: str) -> bool:
        valores = {"senha_hash": senha_hash, "deve_trocar_senha": True, "tentativas_falhas": 0, "bloqueado_ate": None}
        return self._atualizar(id, versao, valores)

    def registrar_termo(self, id: int, versao: int, em: datetime) -> bool:
        return self._atualizar(id, versao, {"termo_ciencia_em": _banco(em)})


def _banco(valor: datetime) -> datetime:
    return valor.astimezone(UTC).replace(tzinfo=None)
