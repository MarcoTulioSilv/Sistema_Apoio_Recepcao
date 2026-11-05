"""Relatórios (DDS §9.3, §9.4, DD-44, DD-45, DD-47): cada relatório é uma consulta que produz o modelo tabular único,
com os filtros aplicados e as marcas; a tela, o PDF e o XLSX são renderizações dele. Ver é auditado com os filtros;
exportar, com os filtros e o formato (RNF-607). E os aniversariantes do dia da tela inicial (RF-909)."""

from __future__ import annotations

import re
from datetime import date, timedelta

from sar.modulo_01_acesso.contrato import AuditService, PermissionGuard
from sar.modulo_02_cadastro.contrato import LeituraCadastro, PacienteRelatorio, TipoEvento
from sar.modulo_03_operacao.contrato import ROTULOS_TURNO, LeituraOperacao
from sar.modulo_05_emissao import comum, consultas, exportacao, regras
from sar.modulo_05_emissao.contrato import (
    ArquivoRelatorio,
    Filtros,
    FormatoExportacao,
    Marca,
    ModoConvenio,
    Relatorio,
    Tabela,
)
from sar.modulo_06_configuracao.contrato import Referencias
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import RegraViolada
from sar.nucleo.parametros import LeitorParametros
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho

GUARDA = PermissionGuard()
COMPETENCIA = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
SERIES = frozenset({Relatorio.ENTRADAS, Relatorio.EVENTOS, Relatorio.RECORTE_LIVRE})  # RF-907
DE_FREQUENCIA = frozenset({Relatorio.FREQUENCIA_MENSAL, Relatorio.BALANCO_MENSAL, Relatorio.PREVIA,
                           Relatorio.RECORTE_LIVRE})  # RF-915, P-21  # fmt: skip
MENSAIS = frozenset({Relatorio.FREQUENCIA_MENSAL, Relatorio.BALANCO_MENSAL})  # RF-913
MODOS = {ModoConvenio.SITUACAO: "Situação na data", ModoConvenio.PERIODO: "Cobertura vigente no período"}


def operacao_de_ver(relatorio: Relatorio) -> str:
    return "relatorio.operacional.ver" if relatorio.operacional else "relatorio.gerencial.ver"


def _mes(competencia: str) -> str:
    return f"{competencia[5:]}/{competencia[:4]}"


def _competencias(inicio: date, fim: date) -> list[str]:
    meses, atual = [], inicio.replace(day=1)
    while atual <= fim:
        meses.append(atual.strftime("%Y-%m"))
        atual = (atual + timedelta(days=32)).replace(day=1)
    return meses


class ServicoRelatorios:
    def __init__(
        self,
        executar: ExecutorDeOperacao,
        leitura: LeituraCadastro,
        auditoria: AuditService | None = None,
        operacao: LeituraOperacao | None = None,
        referencias: Referencias | None = None,
        parametros: LeitorParametros | None = None,
    ) -> None:
        self._executar = executar
        self._leitura = leitura
        self._auditoria = auditoria
        self._operacao = operacao
        self._referencias = referencias
        self._parametros = parametros

    # ---------------------------------------------------------------- contrato
    def disponiveis(self, contexto: Contexto) -> list[Relatorio]:
        return [r for r in Relatorio if GUARDA.pode(contexto, operacao_de_ver(r))]

    def gerar(self, contexto: Contexto, relatorio: Relatorio, filtros: Filtros) -> Tabela:
        GUARDA.exigir(contexto, operacao_de_ver(relatorio))
        self._validar(contexto, relatorio, filtros)

        def operacao(uow: UnidadeDeTrabalho) -> Tabela:
            tabela = self._montar(uow, contexto, relatorio, filtros)
            self._servicos()[0].registrar(uow, contexto, operacao_de_ver(relatorio), "relatorio", relatorio.value,
                                          {"filtros": (None, _filtros_auditados(relatorio, filtros))})  # fmt: skip
            return tabela

        return self._executar(operacao)

    def exportar(
        self, contexto: Contexto, relatorio: Relatorio, filtros: Filtros, formato: FormatoExportacao
    ) -> ArquivoRelatorio:
        GUARDA.exigir(contexto, operacao_de_ver(relatorio))
        GUARDA.exigir(contexto, "relatorio.exportar")
        self._validar(contexto, relatorio, filtros)
        tabela = self._executar(lambda uow: self._montar(uow, contexto, relatorio, filtros))
        arquivo = exportacao.para_pdf(tabela) if formato is FormatoExportacao.PDF else exportacao.para_xlsx(tabela)

        def registrar(uow: UnidadeDeTrabalho) -> None:  # RNF-607: relatório, filtros e formato
            self._servicos()[0].registrar(
                uow, contexto, "relatorio.exportar", "relatorio", relatorio.value,
                {"formato": (None, formato.value), "filtros": (None, _filtros_auditados(relatorio, filtros))},
            )  # fmt: skip

        self._executar(registrar)
        return arquivo

    def aniversariantes(self, contexto: Contexto, data: date) -> list[str]:
        GUARDA.exigir(contexto, "relatorio.aniversariantes.ver")
        return [i.nome for i in self._executar(lambda uow: self._leitura.aniversariantes(uow, data))]

    # ---------------------------------------------------------------- filtros
    def _validar(self, contexto: Contexto, relatorio: Relatorio, filtros: Filtros) -> None:
        pede = relatorio.filtros
        precisa_periodo = "periodo" in pede and (
            relatorio is not Relatorio.CONVENIO or filtros.modo_convenio is ModoConvenio.PERIODO
        )
        precisa_data = "data_referencia" in pede and (
            relatorio is not Relatorio.CONVENIO or filtros.modo_convenio is ModoConvenio.SITUACAO
        )
        if precisa_periodo and (filtros.inicio is None or filtros.fim is None or filtros.inicio > filtros.fim):
            raise RegraViolada("relatorio.filtro.periodo")  # RF-901
        if precisa_data and filtros.data_referencia is None:
            raise RegraViolada("relatorio.filtro.data_referencia")
        if "competencia" in pede and not COMPETENCIA.match(filtros.competencia or ""):
            raise RegraViolada("relatorio.filtro.competencia")
        if "tipo_evento" in pede and filtros.tipo_evento not in (None, *(t.value for t in TipoEvento)):
            raise RegraViolada("relatorio.filtro.tipo_evento")

    def _rotulos(
        self, uow: UnidadeDeTrabalho, contexto: Contexto, relatorio: Relatorio, f: Filtros
    ) -> list[tuple[str, str]]:
        pede, rotulos = relatorio.filtros, []
        if relatorio is Relatorio.CONVENIO:
            rotulos.append(("Modo", MODOS[f.modo_convenio]))
        if "periodo" in pede and f.inicio and f.fim and (relatorio is not Relatorio.CONVENIO
                                                          or f.modo_convenio is ModoConvenio.PERIODO):  # fmt: skip
            rotulos.append(("Período", f"{regras.data_curta(f.inicio)} a {regras.data_curta(f.fim)}"))
        na_data = relatorio is not Relatorio.CONVENIO or f.modo_convenio is ModoConvenio.SITUACAO
        if "data_referencia" in pede and f.data_referencia and na_data:
            rotulos.append(("Data de referência", regras.data_curta(f.data_referencia)))
        if "competencia" in pede and f.competencia:
            rotulos.append(("Competência", _mes(f.competencia)))
        if relatorio is Relatorio.PREVIA:
            rotulos.append(("Competência", _mes(regras.competencia(contexto.instante))))
        if "tipo_evento" in pede:
            tipo = consultas.EVENTOS[TipoEvento(f.tipo_evento)] if f.tipo_evento else "Todos"
            rotulos.append(("Tipo de evento", tipo))
        if "paciente_id" in pede and f.paciente_id is not None:
            identificacao = self._leitura.identificacao(uow, f.paciente_id)
            rotulos.append(("Paciente", identificacao.nome if identificacao else "—"))
        return rotulos

    # ---------------------------------------------------------------- montagem
    def _servicos(self) -> tuple[AuditService, LeituraOperacao, Referencias, LeitorParametros]:
        if self._auditoria is None or self._operacao is None or self._referencias is None or self._parametros is None:
            raise RuntimeError("ServicoRelatorios montado só para os aniversariantes")
        return self._auditoria, self._operacao, self._referencias, self._parametros

    def _montar(self, uow: UnidadeDeTrabalho, contexto: Contexto, relatorio: Relatorio, f: Filtros) -> Tabela:
        auditoria, operacao, referencias, parametros = self._servicos()
        hoje = regras.hoje(contexto.instante)
        marcas: list[Marca] = []
        competencias: list[str] = []

        def base() -> list[PacienteRelatorio]:
            return self._leitura.base_relatorios(uow)

        if relatorio is Relatorio.ENTRADAS:
            colunas, linhas = consultas.entradas(base(), _d(f.inicio), _d(f.fim))
        elif relatorio is Relatorio.EVENTOS:
            tipo = TipoEvento(f.tipo_evento) if f.tipo_evento else None
            colunas, linhas = consultas.eventos(base(), _d(f.inicio), _d(f.fim), tipo)
        elif relatorio is Relatorio.CIDADE:
            pacientes = base()
            codigos = sorted({p.municipio for p in pacientes if p.municipio})
            municipios = {c: f"{m.nome}-{m.uf}" for c in codigos if (m := referencias.municipio(uow, c))}
            colunas, linhas = consultas.por_cidade(pacientes, _d(f.data_referencia), municipios)
        elif relatorio is Relatorio.CONVENIO:
            pacientes = base()
            ids = sorted({p.convenio_id for pac in pacientes for p in pac.periodos if p.convenio_id is not None})
            convenios = {i: c.nome for i in ids if (c := referencias.convenio(uow, i))}
            if f.modo_convenio is ModoConvenio.SITUACAO:
                colunas, linhas = consultas.convenio_na_data(pacientes, _d(f.data_referencia), convenios)
            else:
                colunas, linhas = consultas.convenio_no_periodo(pacientes, _d(f.inicio), _d(f.fim), convenios)
                marcas.append(self._inicio_serie(parametros))
        elif relatorio is Relatorio.FAIXA_ETARIA:
            colunas, linhas = consultas.por_faixa_etaria(base(), _d(f.data_referencia), referencias.faixas_etarias(uow))
        elif relatorio is Relatorio.SEXO:
            colunas, linhas = consultas.por_sexo(base(), _d(f.data_referencia))
        elif relatorio is Relatorio.OCUPACAO:
            colunas, linhas = consultas.ocupacao(operacao.escalas(uow), operacao.contagem(uow, _d(f.data_referencia)))
        elif relatorio is Relatorio.RECORTE_LIVRE:
            inicio, fim = _d(f.inicio), _d(f.fim)
            colunas, linhas = consultas.recorte_livre(base(), inicio, fim, operacao.realizadas(uow, inicio, fim))
            pendentes = operacao.sessoes_nao_confirmadas(uow, inicio, fim, contexto.instante)
            if pendentes:  # RF-914
                marcas.append(Marca("nao_confirmadas", f"{len(pendentes)} sessão(ões) não confirmada(s) no intervalo: "
                                                       "os números podem mudar com a confirmação."))  # fmt: skip
            competencias = _competencias(inicio, fim)
        else:  # mensais e prévia (RF-906, RF-916, DD-47)
            competencia = regras.competencia(contexto.instante) if relatorio is Relatorio.PREVIA else str(f.competencia)
            if relatorio in MENSAIS:
                situacao = operacao.mes_fechado(uow, competencia, hoje)
                if not situacao.fechado:  # RF-913: bloqueio, com quantas e quais faltam
                    faltam = [(regras.data_curta(s.data), ROTULOS_TURNO[s.escala.turno]) for s in situacao.pendentes]
                    raise RegraViolada("relatorio.mes_incompleto", {"quantidade": len(faltam), "pendentes": faltam})
            pareamentos = operacao.frequencia_do_mes(uow, competencia, contexto.instante)
            if f.paciente_id is not None and relatorio is not Relatorio.FREQUENCIA_MENSAL:
                pareamentos = {pid: p for pid, p in pareamentos.items() if pid == f.paciente_id}
            identificados = {pid: (i.nome, i.prontuario)
                             for pid, i in self._leitura.identificacoes(uow, sorted(pareamentos)).items()}  # fmt: skip
            montar = consultas.frequencia_mensal if relatorio is Relatorio.FREQUENCIA_MENSAL else consultas.balanco
            colunas, linhas = montar(pareamentos, identificados)
            if relatorio is Relatorio.PREVIA:
                marcas.append(Marca("previa", "PRÉVIA — mês em aberto: os números mudam até o fechamento do mês."))
            competencias = [competencia]

        if relatorio in SERIES:
            marcas.insert(0, self._inicio_serie(parametros))
        if relatorio in DE_FREQUENCIA:
            for marca in operacao.marcas_alteracao(uow, competencias):  # RF-915, P-21
                quando = regras.data_curta(regras.hoje(marca.instante))
                marcas.append(Marca("mes_alterado", f"Mês {_mes(marca.competencia)} alterado após o fechamento em "
                                                    f"{quando}. Motivo: {marca.motivo}"))  # fmt: skip
        comuns_ = comum.ler(uow, referencias, auditoria, contexto.instante)
        return Tabela(relatorio, relatorio.titulo, tuple(self._rotulos(uow, contexto, relatorio, f)), colunas,
                      tuple(linhas), tuple(marcas), contexto.instante,
                      comuns_.valores["codigo_integridade"])  # fmt: skip

    @staticmethod
    def _inicio_serie(parametros: LeitorParametros) -> Marca:
        implantacao = parametros.valor("data_implantacao")
        if isinstance(implantacao, date):
            return Marca("inicio_serie", f"Série histórica a partir de {regras.data_curta(implantacao)}, data de "
                                         "implantação do sistema.")  # fmt: skip
        return Marca("inicio_serie", "Série histórica sem data de implantação definida.")


def _d(valor: date | None) -> date:
    if valor is None:  # _validar garante; aqui só para o tipo
        raise RegraViolada("relatorio.filtro.periodo")
    return valor


def _filtros_auditados(relatorio: Relatorio, f: Filtros) -> str:
    """Só os filtros do relatório, em texto estável; nunca nome de paciente, só o id (DD-10)."""
    valores = {
        "inicio": f.inicio, "fim": f.fim, "data_referencia": f.data_referencia, "competencia": f.competencia,
        "tipo_evento": f.tipo_evento,
        "modo_convenio": f.modo_convenio.value if relatorio is Relatorio.CONVENIO else None,
        "paciente_id": f.paciente_id,
    }  # fmt: skip
    return "; ".join(f"{chave}={valor}" for chave, valor in valores.items() if valor is not None)
