"""Catálogo de jobs contra o DDS §13.1 (CT-JOB-01) e as regras puras do agendamento: atraso, horário perdido, janela,
limite das 04:30, gatilhos e o alarme de disco (DD-08, DD-61, DD-64, DD-111)."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from sar.modulo_09_agendamento import regras
from sar.modulo_09_agendamento.agendador import gatilho
from sar.modulo_09_agendamento.catalogo import CATALOGO, EXTERNOS, POR_NOME, com_rotinas
from sar.modulo_09_agendamento.contrato import Diaria, Domingo, Externa, Intervalo, ResultadoJob
from sar.modulo_09_agendamento.disco import OcupacaoDisco, pastas_monitoradas, percentual
from sar.modulo_09_agendamento.pendencias import acima_do_alarme
from sar.nucleo.contexto import Contexto
from sar.nucleo.parametros import PARAMETROS

DDS = Path(__file__).resolve().parents[2] / "docs" / "DDS_recepcao-v1_1.md"
FUSO = regras.FUSO


def local(ano: int, mes: int, dia: int, hora: int, minuto: int = 0) -> datetime:
    return datetime(ano, mes, dia, hora, minuto, tzinfo=FUSO)


# ------------------------------------------------------------------ CT-JOB-01
def linhas_do_dds() -> list[list[str]]:
    texto = DDS.read_text(encoding="utf-8")
    secao = texto[texto.index("### 13.1 Catálogo de jobs") : texto.index("### 13.2")]
    linhas = [[c.strip() for c in b.strip().strip("|").split("|")] for b in secao.splitlines() if b.startswith("| ")]
    return [linha for linha in linhas if not linha[0].startswith("**")]


def _intervalo(texto: str) -> timedelta:
    numero, unidade = re.match(r"(\d+) (min|h|dias?)", texto).groups()  # type: ignore[union-attr]
    return {"min": timedelta(minutes=1), "h": timedelta(hours=1)}.get(unidade, timedelta(days=1)) * int(numero)


@pytest.mark.requisito("DD-61", "CT-JOB-01")
def test_catalogo_do_codigo_e_o_do_dds() -> None:
    do_dds = linhas_do_dds()
    assert len(do_dds) == len(CATALOGO) == 12
    for job, (nome, modulo, quando, intervalo, perdeu, manual) in zip(CATALOGO, do_dds, strict=True):
        assert job.rotulo == re.sub(r" \([^)]*\)$", "", nome), job.nome  # sem o comentário entre parênteses
        assert job.pesado == ("(pesada" in nome), job.nome
        assert job.modulo == modulo, job.nome
        assert regras.quando(job.agenda) == quando, job.nome
        assert job.intervalo_maximo == _intervalo(intervalo), job.nome
        assert job.roda_ao_subir == perdeu.startswith("Roda ao subir"), job.nome
        assert job.fora_da_janela == ("fora da janela" in perdeu), job.nome
        assert job.manual_permitida == (manual == "Sim"), job.nome


@pytest.mark.requisito("DD-62", "DD-63")
def test_so_backup_copia_e_fila_ficam_fora_do_worker() -> None:
    assert sorted(EXTERNOS) == ["backup", "consumidor_fila", "copia_pendrive"]
    assert all(isinstance(POR_NOME[n].agenda, Externa) for n in EXTERNOS)


def _rotina(_c: Contexto, _cursor: str | None, _s: float | None) -> ResultadoJob:
    return ResultadoJob(0)


@pytest.mark.requisito("DD-61")
def test_composicao_exige_uma_rotina_por_job_do_worker() -> None:
    do_worker = [j.nome for j in CATALOGO if j.nome not in EXTERNOS]
    jobs = com_rotinas(dict.fromkeys(do_worker, _rotina))
    assert all(j.rotina is not None for j in jobs if j.nome not in EXTERNOS)
    with pytest.raises(ValueError):
        com_rotinas(dict.fromkeys(do_worker[1:], _rotina))
    with pytest.raises(ValueError):
        com_rotinas({**dict.fromkeys(do_worker, _rotina), "backup": _rotina})


# ------------------------------------------------------------------ atraso (pendência 17)
@pytest.mark.requisito("R-38", "DD-61", "CT-JOB-04")
def test_atraso_conta_do_ultimo_sucesso() -> None:
    sucesso = local(2026, 11, 8, 2, 20)
    dois_dias = timedelta(days=2)
    assert regras.atrasado_desde(dois_dias, sucesso, sucesso + dois_dias, None) is None  # no limite, ainda em dia
    depois = sucesso + dois_dias + timedelta(seconds=1)
    assert regras.atrasado_desde(dois_dias, sucesso, depois, None) == sucesso + dois_dias


@pytest.mark.requisito("R-38", "DD-91", "CT-JOB-04")
def test_sem_sucesso_conta_da_implantacao_e_antes_dela_nada_atrasa() -> None:
    implantacao = local(2026, 11, 2, 0)
    assert regras.atrasado_desde(timedelta(days=2), None, local(2026, 12, 1, 0), None) is None
    assert regras.atrasado_desde(timedelta(days=2), None, local(2026, 11, 3, 23), implantacao) is None
    assert regras.atrasado_desde(timedelta(days=2), None, local(2026, 11, 4, 1), implantacao) == local(2026, 11, 4, 0)


# ------------------------------------------------------------------ horário perdido (DD-08) e janela (DEC-68)
@pytest.mark.requisito("DEC-68", "DD-32")
@pytest.mark.parametrize(("instante", "dentro"), [
    (local(2026, 11, 10, 4, 59), False), (local(2026, 11, 10, 5, 0), True), (local(2026, 11, 10, 19, 59), True),
    (local(2026, 11, 10, 20, 0), False), (local(2026, 11, 14, 12), True), (local(2026, 11, 15, 12), False),
])  # fmt: skip
def test_janela_de_operacao(instante: datetime, dentro: bool) -> None:
    assert regras.em_janela_de_operacao(instante) is dentro


@pytest.mark.requisito("DD-08", "CT-JOB-05")
def test_roda_ao_subir_so_quem_perdeu_o_horario() -> None:
    disco = com_rotinas(dict.fromkeys([j.nome for j in CATALOGO if j.nome not in EXTERNOS], _rotina))
    por_nome = {j.nome: j for j in disco}
    agora = local(2026, 11, 10, 22)
    assert regras.deve_rodar_ao_subir(por_nome["ocupacao_disco"], None, agora)
    assert regras.deve_rodar_ao_subir(por_nome["ocupacao_disco"], agora - timedelta(minutes=61), agora)
    assert not regras.deve_rodar_ao_subir(por_nome["ocupacao_disco"], agora - timedelta(minutes=10), agora)
    assert not regras.deve_rodar_ao_subir(por_nome["rescan_acervo"], None, agora)  # "próximo domingo"
    assert not regras.deve_rodar_ao_subir(POR_NOME["ocupacao_disco"], None, agora)  # sem rotina: não roda


@pytest.mark.requisito("DD-08", "DEC-68", "CT-JOB-05")
def test_verificacao_da_cadeia_ao_subir_so_fora_da_janela() -> None:
    cadeia = com_rotinas(dict.fromkeys([j.nome for j in CATALOGO if j.nome not in EXTERNOS], _rotina))
    job = next(j for j in cadeia if j.nome == "verificacao_cadeia")
    ontem = local(2026, 11, 8, 2)
    assert not regras.deve_rodar_ao_subir(job, ontem, local(2026, 11, 10, 10))
    assert regras.deve_rodar_ao_subir(job, ontem, local(2026, 11, 10, 21))


@pytest.mark.requisito("DD-64", "CT-JOB-05")
def test_limite_das_rotinas_pesadas_as_quatro_e_meia() -> None:
    assert regras.segundos_ate_o_limite(local(2026, 11, 15, 2, 30)) == 2 * 3600
    assert regras.segundos_ate_o_limite(local(2026, 11, 15, 4, 29)) == 60
    assert regras.segundos_ate_o_limite(local(2026, 11, 15, 22, 0)) == 6.5 * 3600  # a de amanhã


# ------------------------------------------------------------------ gatilhos do APScheduler
@pytest.mark.requisito("DD-64", "DD-61")
def test_gatilhos_no_fuso_da_clinica() -> None:
    sexta = local(2026, 11, 13, 12)
    diaria = gatilho(Diaria(2, 0))
    assert diaria is not None and diaria.get_next_fire_time(None, sexta) == local(2026, 11, 14, 2)
    domingo = gatilho(Domingo(2, 30))
    assert domingo is not None and domingo.get_next_fire_time(None, sexta) == local(2026, 11, 15, 2, 30)
    primeiro = gatilho(Domingo(2, 40, primeiro_do_mes=True))
    assert primeiro is not None and primeiro.get_next_fire_time(None, sexta) == local(2026, 12, 6, 2, 40)
    intervalo = gatilho(Intervalo(15))
    assert intervalo is not None
    assert gatilho(Externa("Semanal")) is None


# ------------------------------------------------------------------ disco (RNF-621, DD-111)
@pytest.mark.requisito("RNF-621", "DD-111", "CT-JOB-06")
@pytest.mark.parametrize(("ocupado", "alarme"), [(84, False), (85, True), (86, True)])
def test_alarme_de_disco_no_valor_limite(ocupado: int, alarme: bool) -> None:
    padrao = PARAMETROS["disco_alarme_ocupacao"].padrao
    assert padrao == 85
    assert acima_do_alarme(percentual(1000, ocupado * 10), padrao) is alarme


@pytest.mark.requisito("RNF-621", "DD-111")
def test_percentual_arredonda_para_baixo_e_mede_a_pasta_mais_cheia(tmp_path: Path) -> None:
    assert percentual(1000, 849) == 84 and percentual(0, 0) == 0
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    medidas = {a: (100, 40), b: (100, 91)}
    job = OcupacaoDisco([a, b, tmp_path / "nao_existe"], medir=lambda p: medidas[p])
    assert job(Contexto.sistema("teste", datetime(2026, 11, 10, tzinfo=UTC)), None, None).itens == 91


@pytest.mark.requisito("RNF-621")
def test_pastas_monitoradas_do_ambiente(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import os

    monkeypatch.setenv("SAR_DISCOS_MONITORADOS", os.pathsep.join([str(tmp_path / "backup"), str(tmp_path / "c")]))
    assert pastas_monitoradas([tmp_path / "c"]) == (tmp_path / "c", tmp_path / "backup")


def test_data_de_referencia_dos_testes() -> None:
    assert date(2026, 11, 15).weekday() == 6  # domingo, para os gatilhos acima
