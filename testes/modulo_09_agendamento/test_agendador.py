"""O agendador do worker (AD-12, DD-08) e a composição dos jobs com as rotinas dos módulos donos (§13.1, §13.3)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from sar.composicao import compor_agendamento
from sar.modulo_04_documentos.armazenamento import Pastas
from sar.modulo_09_agendamento.agendador import Agendador
from sar.modulo_09_agendamento.catalogo import CATALOGO, EXTERNOS, com_rotinas
from sar.modulo_09_agendamento.contrato import Execucao, Job, ResultadoJob
from sar.nucleo.contexto import Contexto
from testes.apoio.documentos import AntimalwareFalso
from testes.apoio.relogio_controlado import RelogioControlado

AGORA = datetime(2026, 11, 11, 1, 0, tzinfo=UTC)  # terça, 22h em Jataí: fora da janela de operação


def _rotina(_c: Contexto, _cursor: str | None, _s: float | None) -> ResultadoJob:
    return ResultadoJob(1)


@dataclass
class ServicoFalso:
    sucessos: dict[str, datetime]
    jobs: tuple[Job, ...] = field(default_factory=lambda: com_rotinas(dict.fromkeys(
        [j.nome for j in CATALOGO if j.nome not in EXTERNOS], _rotina)))  # fmt: skip
    rodados: list[str] = field(default_factory=list)
    todos: threading.Event = field(default_factory=threading.Event)
    esperados: int = 0

    def ultimos_sucessos(self) -> dict[str, datetime]:
        return self.sucessos

    def rodar(self, job: Job, contexto: Contexto, segundos: float | None) -> Execucao | None:
        assert contexto.e_sistema and contexto.origem == f"job.{job.nome}"
        self.rodados.append(job.nome)
        if len(self.rodados) >= self.esperados:
            self.todos.set()
        return None


@pytest.mark.requisito("DD-08", "AD-12", "CT-JOB-05")
def test_na_partida_roda_so_o_que_perdeu_o_horario() -> None:
    em_dia = {"ocupacao_disco": AGORA, "idade_assinaturas": AGORA, "expiracao_ingestoes": AGORA}
    servico = ServicoFalso(em_dia, esperados=2)
    agendador = Agendador(servico, RelogioControlado(AGORA))  # type: ignore[arg-type]
    try:
        imediatos = agendador.iniciar()
        assert sorted(imediatos) == ["descarte_rascunhos", "verificacao_cadeia"]  # nunca rodaram; fora da janela
        assert servico.todos.wait(10)
    finally:
        agendador.parar()
    assert sorted(servico.rodados) == sorted(imediatos)


@pytest.mark.requisito("AD-12")
def test_agenda_cada_job_do_worker_uma_vez() -> None:
    agendador = Agendador(ServicoFalso({}), RelogioControlado(AGORA))  # type: ignore[arg-type]
    try:
        agendador.iniciar()
        ids = sorted(j.id for j in agendador._agendador.get_jobs() if not j.id.endswith(".partida"))
    finally:
        agendador.parar()
    assert ids == sorted(j.nome for j in CATALOGO if j.nome not in EXTERNOS)


@pytest.mark.requisito("DD-61", "DD-58")
def test_composicao_liga_uma_rotina_a_cada_job_do_worker(tmp_path: Path) -> None:
    engine: Any = create_engine("sqlite://", poolclass=StaticPool)
    worker = compor_agendamento(engine, engine, bytes(32), Pastas(tmp_path / "c", tmp_path / "q"), AntimalwareFalso())
    assert all(j.rotina is not None for j in worker.agendamento.jobs if j.nome not in EXTERNOS)
    assert {j.nome for j in worker.agendamento.jobs} == {j.nome for j in CATALOGO}
    engine.dispose()
