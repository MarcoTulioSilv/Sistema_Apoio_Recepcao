"""Consultas dos relatórios, sem banco (DDS §9.3, RF-902 a RF-911, DEC-44): os dados dos pacientes são montados à mão,
fictícios."""

from __future__ import annotations

from datetime import date, time

import pytest

from sar.modulo_02_cadastro.contrato import PacienteRelatorio, PeriodoRelatorio, Sexo, TipoCobertura, TipoEvento
from sar.modulo_03_operacao.contrato import BalancoMes, Escala, PacienteNaEscala, PareamentoDoMes
from sar.modulo_05_emissao import consultas
from sar.modulo_05_emissao.contrato import Bloco
from sar.modulo_06_configuracao.contrato import FaixaEtaria

D = date
FAIXAS = [FaixaEtaria(i, i + 9, f"{i}–{i + 9}") for i in range(0, 100, 10)] + [FaixaEtaria(100, None, "100 ou mais")]


def periodo(inicio: date, evento: TipoEvento | None = None, data: date | None = None, comprovante: bool = False,
            cobertura: TipoCobertura | None = None, convenio: int | None = None) -> PeriodoRelatorio:  # fmt: skip
    return PeriodoRelatorio(1, inicio, evento, data, comprovante, cobertura, convenio)


def paciente(pid: int, nome: str, *periodos: PeriodoRelatorio, sexo: Sexo | None = None,
             nascimento: date | None = None, municipio: str | None = None) -> PacienteRelatorio:  # fmt: skip
    return PacienteRelatorio(pid, nome, f"P{pid:03}", sexo, nascimento, municipio, periodos)


ANA = paciente(
    1, "Ana Exemplo", periodo(D(2025, 3, 1), TipoEvento.ALTA, D(2025, 6, 30)),
    periodo(D(2026, 10, 5), cobertura=TipoCobertura.SUS), sexo=Sexo.FEMININO, nascimento=D(1956, 10, 20),
    municipio="5211909",
)  # fmt: skip
BRUNO = paciente(2, "Bruno Exemplo", periodo(D(2026, 10, 1), TipoEvento.OBITO, D(2026, 10, 10), comprovante=True,
                 cobertura=TipoCobertura.CONVENIO, convenio=7), sexo=Sexo.MASCULINO, nascimento=D(1926, 1, 1),
                 municipio="5211909")  # fmt: skip
CAIO = paciente(3, "Caio Exemplo", periodo(D(2026, 9, 1)))  # sem sexo, nascimento, município nem cobertura
BASE = [ANA, BRUNO, CAIO]


@pytest.mark.requisito("RF-902")
def test_entradas_no_periodo_marcam_o_retorno() -> None:
    _, linhas = consultas.entradas(BASE, D(2026, 9, 1), D(2026, 10, 31))
    assert linhas == [
        ("Caio Exemplo", "P003", "01/09/2026", "Não"),
        ("Bruno Exemplo", "P002", "01/10/2026", "Não"),
        ("Ana Exemplo", "P001", "05/10/2026", "Sim"),  # já teve um período em 2025
    ]


@pytest.mark.requisito("RF-904")
def test_eventos_no_periodo_por_tipo_com_o_comprovante() -> None:
    _, todos = consultas.eventos(BASE, D(2025, 1, 1), D(2026, 12, 31), None)
    assert todos == [("Ana Exemplo", "P001", "Alta", "30/06/2025", "Não"),
                     ("Bruno Exemplo", "P002", "Óbito", "10/10/2026", "Sim")]  # fmt: skip
    _, obitos = consultas.eventos(BASE, D(2025, 1, 1), D(2026, 12, 31), TipoEvento.OBITO)
    assert [linha[2] for linha in obitos] == ["Óbito"]


@pytest.mark.requisito("RF-903", "DEC-44")
def test_cidade_conta_os_em_tratamento_com_nao_informado_e_total() -> None:
    _, linhas = consultas.por_cidade(BASE, D(2026, 10, 10), {"5211909": "Jataí-GO"})
    assert linhas == [("Jataí-GO", 2), ("Não informado", 1), ("Total", 3)]  # o dia do óbito ainda conta (P-09)
    _, depois = consultas.por_cidade(BASE, D(2026, 10, 11), {"5211909": "Jataí-GO"})
    assert depois == [("Jataí-GO", 1), ("Não informado", 1), ("Total", 2)]


@pytest.mark.requisito("RF-905", "DD-101")
def test_convenio_na_data_e_no_periodo() -> None:
    _, na_data = consultas.convenio_na_data(BASE, D(2026, 10, 6), {7: "Unimed Fictícia"})
    assert na_data == [("SUS", 1), ("Unimed Fictícia", 1), ("Não informado", 1), ("Total", 3)]
    _, no_periodo = consultas.convenio_no_periodo(BASE, D(2025, 1, 1), D(2026, 10, 31), {7: "Unimed Fictícia"})
    # Ana conta no SUS e no "não informado" (período de 2025 sem cobertura): os pacientes distintos são 3.
    assert no_periodo == [("SUS", 1), ("Unimed Fictícia", 1), ("Não informado", 2), ("Total de pacientes", 3)]


@pytest.mark.requisito("RF-910", "RF-1206")
def test_faixa_etaria_na_data_de_referencia_com_todas_as_faixas() -> None:
    _, linhas = consultas.por_faixa_etaria(BASE, D(2026, 10, 10), FAIXAS)
    contagem = dict(linhas)
    assert contagem["60–69"] == 1 and contagem["100 ou mais"] == 1 and contagem["Não informado"] == 1
    assert contagem["70–79"] == 0 and contagem["Total"] == 3 and len(linhas) == 13
    _, depois = consultas.por_faixa_etaria(BASE, D(2026, 10, 20), FAIXAS)  # Ana faz 70 no dia 20
    assert dict(depois)["60–69"] == 0 and dict(depois)["70–79"] == 1


@pytest.mark.requisito("RF-911")
def test_sexo_com_nao_informado() -> None:
    _, linhas = consultas.por_sexo(BASE, D(2026, 10, 6))
    assert linhas == [("Feminino", 1), ("Masculino", 1), ("Não informado", 1), ("Total", 3)]


@pytest.mark.requisito("RF-908", "DD-75")
def test_ocupacao_turno_a_turno_com_os_pacientes_e_os_sem_alocacao() -> None:
    """Os três turnos de segunda, quarta e sexta em sequência, depois os de terça, quinta e sábado."""
    escalas = [Escala.de_texto(i, c, t, d, time(6), time(10)) for i, c, t, d in (
        (1, "1-seg", 1, "seg,qua,sex"), (2, "1-ter", 1, "ter,qui,sab"), (3, "2-seg", 2, "seg,qua,sex"),
        (4, "2-ter", 2, "ter,qui,sab"), (5, "3-seg", 3, "seg,qua,sex"), (6, "3-ter", 3, "ter,qui,sab"))]  # fmt: skip
    por_id = {e.id: e for e in escalas}
    distribuicao = [PacienteNaEscala(1, "Ana Exemplo", "P001", None, por_id[1]),
                    PacienteNaEscala(2, "Bruno Exemplo", "P002", None, por_id[1]),
                    PacienteNaEscala(3, "Caio Exemplo", "P003", None, por_id[4]),
                    PacienteNaEscala(4, "Davi Exemplo", "P004", None, None)]  # fmt: skip
    colunas, blocos, total = consultas.ocupacao(list(reversed(escalas)), distribuicao)
    assert [c.titulo for c in colunas] == ["Paciente", "Prontuário"]
    assert blocos == [
        Bloco("Primeiro turno — segunda, quarta e sexta", (("Ana Exemplo", "P001"), ("Bruno Exemplo", "P002")),
              "2 pacientes"),
        Bloco("Segundo turno — segunda, quarta e sexta", (), "0 pacientes"),
        Bloco("Terceiro turno — segunda, quarta e sexta", (), "0 pacientes"),
        Bloco("Primeiro turno — terça, quinta e sábado", (), "0 pacientes"),
        Bloco("Segundo turno — terça, quinta e sábado", (("Caio Exemplo", "P003"),), "1 paciente"),
        Bloco("Terceiro turno — terça, quinta e sábado", (), "0 pacientes"),
        Bloco("Sem alocação", (("Davi Exemplo", "P004"),), "1 paciente", separado=True),
    ]  # fmt: skip
    assert total == "Total geral: 4 pacientes (3 nas escalas e 1 sem alocação)"
    # Sem ninguém fora das escalas, o bloco dos sem alocação não existe.
    _, blocos, total = consultas.ocupacao(escalas, distribuicao[:3])
    assert not any(b.separado for b in blocos) and total == "Total geral: 3 pacientes"


def _pareamento(previstas: int, realizadas: int, nao_compensadas: int, reposicoes: int, extras: int) -> PareamentoDoMes:
    balanco = BalancoMes("2026-09", previstas, realizadas, nao_compensadas, reposicoes, extras, 0, False)
    return PareamentoDoMes(balanco, (), (), (), 0, True)


@pytest.mark.requisito("RF-906", "RF-916", "DD-107")
def test_frequencia_e_balanco_num_relatorio_so_em_ordem_de_nome() -> None:
    pareamentos = {2: _pareamento(13, 12, 0, 1, 2), 1: _pareamento(13, 10, 3, 0, 0)}
    nomes = {1: ("Ana Exemplo", "P001"), 2: ("Bruno Exemplo", "P002")}
    colunas, linhas = consultas.frequencia_mensal(pareamentos, nomes)
    assert [c.titulo for c in colunas] == ["Paciente", "Prontuário", "Previstas", "Realizadas", "Ausências",
                                           "Reposições", "Ausências não compensadas", "Extras"]  # fmt: skip
    assert linhas == [("Ana Exemplo", "P001", 13, 10, 3, 0, 3, 0), ("Bruno Exemplo", "P002", 13, 12, 1, 1, 0, 2)]


@pytest.mark.requisito("RF-914")
def test_recorte_livre_lista_quem_esteve_em_tratamento_no_intervalo() -> None:
    _, linhas = consultas.recorte_livre(BASE, D(2026, 10, 11), D(2026, 10, 31), {1: 5})
    assert linhas == [("Ana Exemplo", "P001", 5), ("Caio Exemplo", "P003", 0)]  # Bruno faleceu em 10/10
