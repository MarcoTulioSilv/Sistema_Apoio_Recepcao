"""Consultas dos relatórios (DDS §9.3), em funções puras: recebem os dados já lidos dos outros módulos e devolvem as
colunas e as linhas do modelo tabular (DD-44). Contagens só de cadastros não anulados, sem suprimir células (DEC-44):
toda categoria aparece, inclusive "não informado", e o total fecha com os pacientes contados."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date

from sar.modulo_02_cadastro.contrato import PacienteRelatorio, PeriodoRelatorio, Sexo, TipoCobertura, TipoEvento
from sar.modulo_03_operacao.contrato import Escala, PacienteNaEscala, PareamentoDoMes
from sar.modulo_05_emissao.contrato import Bloco, Coluna
from sar.modulo_05_emissao.regras import data_curta
from sar.modulo_06_configuracao.contrato import FaixaEtaria

Linhas = list[tuple[str | int, ...]]
Resultado = tuple[tuple[Coluna, ...], Linhas]

NAO_INFORMADO = "Não informado"
TOTAL = "Total"
EVENTOS = {TipoEvento.OBITO: "Óbito", TipoEvento.ALTA: "Alta", TipoEvento.TRANSFERENCIA: "Transferência",
           TipoEvento.TRANSPLANTE: "Transplante", TipoEvento.DESISTENCIA: "Desistência"}  # fmt: skip
SEXOS = {Sexo.FEMININO: "Feminino", Sexo.MASCULINO: "Masculino"}
DIAS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
PACIENTE, PRONTUARIO = Coluna("Paciente"), Coluna("Prontuário")


def em_tratamento(periodo: PeriodoRelatorio, data: date) -> bool:
    """O período cobre a data; o dia do evento ainda conta (P-09)."""
    return periodo.inicio <= data and (periodo.evento_data is None or data <= periodo.evento_data)


def toca(periodo: PeriodoRelatorio, inicio: date, fim: date) -> bool:
    return periodo.inicio <= fim and (periodo.evento_data is None or periodo.evento_data >= inicio)


def _periodo_em(paciente: PacienteRelatorio, data: date) -> PeriodoRelatorio | None:
    return next((p for p in reversed(paciente.periodos) if em_tratamento(p, data)), None)


def _sim(valor: bool) -> str:
    return "Sim" if valor else "Não"


def _contagem(titulo: str, contados: Counter[str], ordem: Sequence[str] | None = None) -> Resultado:
    """Categoria e quantidade; sem ordem fixa, da maior para a menor e por nome. Linha de total no fim."""
    if ordem is None:
        ordem = sorted(contados, key=lambda c: (c == NAO_INFORMADO, -contados[c], c))
    linhas: Linhas = [(categoria, contados.get(categoria, 0)) for categoria in ordem]
    linhas.append((TOTAL, sum(contados.values())))
    return (Coluna(titulo), Coluna("Quantidade", numerica=True)), linhas


# ------------------------------------------------------------------ gerenciais
def entradas(base: Iterable[PacienteRelatorio], inicio: date, fim: date) -> Resultado:
    """RF-902: períodos iniciados no intervalo; retorno quando o paciente já tinha período anterior."""
    achados = []
    for paciente in base:
        for numero, periodo in enumerate(paciente.periodos):
            if inicio <= periodo.inicio <= fim:
                achados.append((periodo.inicio, paciente.nome, paciente.prontuario, numero > 0))
    achados.sort()
    linhas: Linhas = [
        (nome, prontuario, data_curta(data), _sim(retorno)) for data, nome, prontuario, retorno in achados
    ]
    return (PACIENTE, PRONTUARIO, Coluna("Início do período"), Coluna("Retorno")), linhas


def eventos(base: Iterable[PacienteRelatorio], inicio: date, fim: date, tipo: TipoEvento | None) -> Resultado:
    """RF-904: eventos de encerramento com data no intervalo, de um tipo ou de todos."""
    achados = [
        (p.evento_data, paciente.nome, paciente.prontuario, p.evento_tipo, p.comprovante)
        for paciente in base
        for p in paciente.periodos
        if p.evento_tipo is not None and p.evento_data is not None and inicio <= p.evento_data <= fim
        and (tipo is None or p.evento_tipo is tipo)
    ]  # fmt: skip
    achados.sort(key=lambda a: (a[0], a[1]))
    linhas: Linhas = [(nome, prontuario, EVENTOS[evento], data_curta(data), _sim(comprovante))
                      for data, nome, prontuario, evento, comprovante in achados]  # fmt: skip
    colunas = (PACIENTE, PRONTUARIO, Coluna("Evento"), Coluna("Data"), Coluna("Comprovante anexado"))
    return colunas, linhas


def por_cidade(base: Iterable[PacienteRelatorio], data: date, municipios: Mapping[str, str]) -> Resultado:
    """RF-903: pacientes em tratamento na data por município de residência ("Nome-UF")."""
    contados = Counter(
        municipios.get(paciente.municipio, NAO_INFORMADO) if paciente.municipio else NAO_INFORMADO
        for paciente in base
        if _periodo_em(paciente, data) is not None
    )
    return _contagem("Município", contados)


def _cobertura(periodo: PeriodoRelatorio, convenios: Mapping[int, str]) -> str:
    if periodo.cobertura is TipoCobertura.SUS:
        return "SUS"
    if periodo.cobertura is TipoCobertura.CONVENIO and periodo.convenio_id is not None:
        return convenios.get(periodo.convenio_id, NAO_INFORMADO)
    return NAO_INFORMADO


def convenio_na_data(base: Iterable[PacienteRelatorio], data: date, convenios: Mapping[int, str]) -> Resultado:
    """RF-905, situação na data: a cobertura do período que cobre a data (DD-101)."""
    contados = Counter(
        _cobertura(periodo, convenios) for paciente in base if (periodo := _periodo_em(paciente, data)) is not None
    )
    return _contagem("Convênio ou SUS", contados)


def convenio_no_periodo(
    base: Iterable[PacienteRelatorio], inicio: date, fim: date, convenios: Mapping[int, str]
) -> Resultado:
    """RF-905, cobertura vigente no período: cada paciente conta uma vez por cobertura que teve no intervalo; quem
    trocou de cobertura aparece nas duas, e o total é de pacientes distintos."""
    por_cobertura: dict[str, set[int]] = {}
    pacientes: set[int] = set()
    for paciente in base:
        for periodo in paciente.periodos:
            if toca(periodo, inicio, fim):
                por_cobertura.setdefault(_cobertura(periodo, convenios), set()).add(paciente.paciente_id)
                pacientes.add(paciente.paciente_id)
    contados = Counter({cobertura: len(ids) for cobertura, ids in por_cobertura.items()})
    colunas, linhas = _contagem("Convênio ou SUS", contados)
    linhas[-1] = ("Total de pacientes", len(pacientes))
    return colunas, linhas


def idade(nascimento: date, data: date) -> int:
    return data.year - nascimento.year - ((data.month, data.day) < (nascimento.month, nascimento.day))


def por_faixa_etaria(base: Iterable[PacienteRelatorio], data: date, faixas: Sequence[FaixaEtaria]) -> Resultado:
    """RF-910: idade na data de referência, nas faixas da RF-1206; todas as faixas aparecem."""

    def faixa(nascimento: date | None) -> str:
        if nascimento is None:
            return NAO_INFORMADO
        anos = idade(nascimento, data)
        return next(f.rotulo for f in faixas if anos >= f.inicio and (f.fim is None or anos <= f.fim))

    contados = Counter(faixa(p.data_nascimento) for p in base if _periodo_em(p, data) is not None)
    return _contagem("Faixa etária", contados, [f.rotulo for f in faixas] + [NAO_INFORMADO])


def por_sexo(base: Iterable[PacienteRelatorio], data: date) -> Resultado:
    """RF-911, com a linha de não informado."""
    contados = Counter(SEXOS[p.sexo] if p.sexo else NAO_INFORMADO for p in base if _periodo_em(p, data) is not None)
    return _contagem("Sexo", contados, ["Feminino", "Masculino", NAO_INFORMADO])


# ------------------------------------------------------------------ operacionais
def rotulo_escala(escala: Escala) -> str:
    """DD-75: o turno por extenso e os dias; o código da escala só nas telas da enfermagem."""
    dias = [DIAS[d] for d in sorted(escala.dias)]
    return f"{escala.rotulo} — {', '.join(dias[:-1])} e {dias[-1]}"


def _ordem_da_escala(escala: Escala) -> tuple[int, int]:
    """Os três turnos de segunda, quarta e sexta em sequência; depois os de terça, quinta e sábado."""
    return min(escala.dias), escala.turno


def _quantos(n: int) -> str:
    return f"{n} paciente" if n == 1 else f"{n} pacientes"


def ocupacao(
    escalas: Sequence[Escala], distribuicao: Sequence[PacienteNaEscala]
) -> tuple[tuple[Coluna, ...], list[Bloco], str]:
    """RF-908: um bloco por escala, com os pacientes alocados na data e o total no rodapé; o total geral; e os sem
    alocação (RF-403) num bloco à parte, só quando houver algum."""
    blocos: list[Bloco] = []
    for escala in sorted(escalas, key=_ordem_da_escala):
        pacientes = [(p.nome, p.prontuario) for p in distribuicao if p.escala is not None and p.escala.id == escala.id]
        blocos.append(Bloco(rotulo_escala(escala), tuple(pacientes), _quantos(len(pacientes))))
    sem = [(p.nome, p.prontuario) for p in distribuicao if p.escala is None]
    total = f"Total geral: {_quantos(len(distribuicao))}"
    if sem:
        blocos.append(Bloco("Sem alocação", tuple(sem), _quantos(len(sem)), separado=True))
        total += f" ({len(distribuicao) - len(sem)} nas escalas e {len(sem)} sem alocação)"
    return (PACIENTE, PRONTUARIO), blocos, total


def _nomes(identificados: Mapping[int, tuple[str, str]], ids: Iterable[int]) -> list[tuple[str, str, int]]:
    return sorted((*identificados[i], i) for i in ids if i in identificados)


def frequencia_mensal(
    pareamentos: Mapping[int, PareamentoDoMes], identificados: Mapping[int, tuple[str, str]]
) -> Resultado:
    """RF-906 e RF-916 num relatório só (DD-107), e a prévia (DD-47): previstas, realizadas e as ausências, separadas em
    repostas e não compensadas; as extras só são definitivas com o mês fechado."""
    linhas: Linhas = []
    for nome, prontuario, pid in _nomes(identificados, pareamentos):
        b = pareamentos[pid].balanco
        linhas.append((nome, prontuario, b.previstas, b.realizadas, b.ausencias_nao_compensadas + b.reposicoes,
                       b.reposicoes, b.ausencias_nao_compensadas, b.extras))  # fmt: skip
    numeros = (Coluna("Previstas", True), Coluna("Realizadas", True), Coluna("Ausências", True),
               Coluna("Reposições", True), Coluna("Ausências não compensadas", True),
               Coluna("Extras", True))  # fmt: skip
    return (PACIENTE, PRONTUARIO, *numeros), linhas


def recorte_livre(
    base: Iterable[PacienteRelatorio], inicio: date, fim: date, realizadas: Mapping[int, int]
) -> Resultado:
    """RF-914: sessões realizadas por paciente em tratamento em algum dia do intervalo."""
    linhas: Linhas = [
        (paciente.nome, paciente.prontuario, realizadas.get(paciente.paciente_id, 0))
        for paciente in base
        if any(toca(p, inicio, fim) for p in paciente.periodos)
    ]
    return (PACIENTE, PRONTUARIO, Coluna("Sessões realizadas", numerica=True)), linhas
