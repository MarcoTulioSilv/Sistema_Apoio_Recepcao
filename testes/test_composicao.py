from __future__ import annotations

from collections.abc import Sequence

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from sar.composicao import compor
from sar.nucleo.contexto import Contexto
from sar.nucleo.portas import Finalidade
from sar.nucleo.uow import RegistroAuditoria, UnidadeDeTrabalho


@pytest.mark.requisito("DD-02", "DD-03")
def test_componentes_ligados_e_auditoria_passa_pelo_gravador() -> None:
    gravados: list[RegistroAuditoria] = []

    def gravador(_sessao: Session, registros: Sequence[RegistroAuditoria]) -> None:
        gravados.extend(registros)

    engine = create_engine("sqlite://", poolclass=StaticPool)
    componentes = compor(engine, bytes(32), gravador)
    agora = componentes.relogio.agora()

    def operacao(uow: UnidadeDeTrabalho) -> None:
        uow.auditar(RegistroAuditoria(Contexto.sistema("teste", agora), "teste", "teste", None, None))

    componentes.executar(operacao)
    assert [r.operacao for r in gravados] == ["teste"]
    nonce, cifrado = componentes.cifra.cifrar(Finalidade.RASCUNHOS, b"x", b"1")
    assert componentes.cifra.decifrar(Finalidade.RASCUNHOS, nonce, cifrado, b"1") == b"x"
    engine.dispose()
