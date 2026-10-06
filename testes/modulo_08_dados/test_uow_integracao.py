"""Unidade de trabalho no MySQL de verdade: conexão, persistência e impasse real (DD-59)."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator, Sequence
from typing import cast

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from sar.modulo_08_dados.uow import ExecutorSQL, UnidadeDeTrabalhoSQL
from sar.nucleo.eventos import Barramento
from sar.nucleo.uow import RegistroAuditoria, UnidadeDeTrabalho

pytestmark = pytest.mark.integracao


def sem_auditoria(_sessao: Session, _registros: Sequence[RegistroAuditoria]) -> None:
    pass


@pytest.fixture
def tabela(engine_migracao: Engine) -> Iterator[Engine]:
    """Tabela de apoio, criada e removida pelo teste."""
    with engine_migracao.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS teste_uow"))
        c.execute(text("CREATE TABLE teste_uow (id INT PRIMARY KEY, valor VARCHAR(100) NOT NULL) ENGINE=InnoDB"))
        c.execute(text("INSERT INTO teste_uow (id, valor) VALUES (1, ''), (2, '')"))
    yield engine_migracao
    with engine_migracao.begin() as c:
        c.execute(text("DROP TABLE teste_uow"))


def executor(engine: Engine) -> ExecutorSQL:
    return ExecutorSQL(lambda: UnidadeDeTrabalhoSQL(engine, Barramento(), sem_auditoria, {}))


def sessao(uow: UnidadeDeTrabalho) -> Session:
    return cast(UnidadeDeTrabalhoSQL, uow).sessao


@pytest.mark.requisito("DDS-12.2", "DD-59")
def test_conexao_em_utc_e_read_committed(tabela: Engine) -> None:
    def operacao(uow: UnidadeDeTrabalho) -> tuple[str, str]:
        linha = sessao(uow).execute(text("SELECT @@session.time_zone, @@session.transaction_isolation")).one()
        return str(linha[0]), str(linha[1])

    assert executor(tabela)(operacao) == ("+00:00", "READ-COMMITTED")


@pytest.mark.requisito("DDS-3.3")
def test_confirmado_e_visivel_em_outra_conexao_e_desfeito_nao(tabela: Engine) -> None:
    def grava(valor: str) -> Callable[[UnidadeDeTrabalho], None]:
        def operacao(uow: UnidadeDeTrabalho) -> None:
            sessao(uow).execute(text("UPDATE teste_uow SET valor = :v WHERE id = 1"), {"v": valor})
            if valor == "desfazer":
                raise RuntimeError("operação abortada")

        return operacao

    executor(tabela)(grava("gravado"))
    with pytest.raises(RuntimeError):
        executor(tabela)(grava("desfazer"))
    with tabela.connect() as c:
        assert c.execute(text("SELECT valor FROM teste_uow WHERE id = 1")).scalar_one() == "gravado"


@pytest.mark.requisito("DD-59")
def test_impasse_real_e_resolvido_repetindo_a_operacao(tabela: Engine) -> None:
    """Duas operações travam as mesmas linhas em ordem inversa. O MySQL escolhe uma vítima, que é
    repetida pelo executor; no fim, as duas operações estão gravadas."""
    barreira = threading.Barrier(2, timeout=15)
    tentativas = {"a": 0, "b": 0}
    erros: list[BaseException] = []

    def operacao(nome: str, primeira: int, segunda: int) -> Callable[[UnidadeDeTrabalho], None]:
        def executar(uow: UnidadeDeTrabalho) -> None:
            tentativas[nome] += 1
            s = sessao(uow)
            atualizar = text("UPDATE teste_uow SET valor = CONCAT(valor, :n) WHERE id = :id")
            s.execute(atualizar, {"n": nome, "id": primeira})
            if tentativas[nome] == 1:
                barreira.wait()  # as duas seguram a primeira linha antes de pedir a segunda
            s.execute(atualizar, {"n": nome, "id": segunda})

        return executar

    def rodar(nome: str, primeira: int, segunda: int) -> None:
        try:
            executor(tabela)(operacao(nome, primeira, segunda))
        except BaseException as erro:
            erros.append(erro)

    linhas = [threading.Thread(target=rodar, args=("a", 1, 2)), threading.Thread(target=rodar, args=("b", 2, 1))]
    for t in linhas:
        t.start()
    for t in linhas:
        t.join(timeout=60)

    assert erros == []
    assert sorted(tentativas.values()) == [1, 2]  # só a vítima repetiu
    with tabela.connect() as c:
        valores = c.execute(text("SELECT valor FROM teste_uow ORDER BY id")).scalars().all()
    assert all(sorted(v) == ["a", "b"] for v in valores)
