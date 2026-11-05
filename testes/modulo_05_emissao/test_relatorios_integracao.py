"""Relatórios com o banco (DDS §9.3, §9.4, §4.5): CT-REL-01, permissões por perfil (P-20, DEC-55), marcas (RF-907,
RF-914, RF-915, DD-47) e a auditoria de ver e exportar (RNF-607).

A implantação é segunda, 28/09/2026: setembro tem só nove sessões (28, 29 e 30, três turnos cada). Os contextos são
de terça, 13/10/2026, às 10h, quando setembro já terminou e outubro está em aberto.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import pytest
from sqlalchemy import Engine, text

from sar.modulo_01_acesso.servicos import ServicoAuditoria
from sar.modulo_03_operacao.leitura import ServicoLeituraOperacao
from sar.modulo_05_emissao.contrato import Filtros, FormatoExportacao, ModoConvenio, Relatorio
from sar.modulo_05_emissao.relatorios import ServicoRelatorios
from sar.modulo_06_configuracao.servicos import ServicoReferencias
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado, RegraViolada
from testes.apoio.cadastro import dados_completos, pessoa
from testes.apoio.fabrica import Fabrica
from testes.apoio.operacao import Operacao, confirmar, contexto, definir_implantacao, montar

pytestmark = pytest.mark.integracao

SEG_1, TER_2 = 1, 4
IMPLANTACAO = date(2026, 9, 28)
SETEMBRO = [(date(2026, 9, d), e) for d, es in ((28, (1, 3, 5)), (29, (2, 4, 6)), (30, (1, 3, 5))) for e in es]
OUTUBRO = Filtros(inicio=date(2026, 9, 28), fim=date(2026, 10, 13))


@dataclass
class Cenario:
    op: Operacao
    relatorios: ServicoRelatorios
    ids: dict[str, int]
    pacientes: list[tuple[int, str]]

    def de(self, perfil: Perfil, chave: str | None = None) -> Contexto:
        padrao = {Perfil.RECEPCAO: "recepcao", Perfil.ENFERMAGEM: "enfermagem", Perfil.TI: "ti"}.get(perfil, "admin")
        return contexto(self.ids, chave or padrao, perfil)

    def fechar_setembro(self) -> None:
        for data, escala in SETEMBRO:
            confirmar(self.op, self.ids, data, escala)


@pytest.fixture
def cenario(
    engine_web: Engine, engine_migracao: Engine, operacao_zerada: dict[str, int], fabrica: Fabrica
) -> Iterator[Cenario]:
    definir_implantacao(engine_migracao, IMPLANTACAO, operacao_zerada["ti"])
    op = montar(engine_web)
    relatorios = ServicoRelatorios(op.cadastro.executar, op.cadastro.leitura, ServicoAuditoria(),
                                   ServicoLeituraOperacao(op.cadastro.leitura, op.parametros), ServicoReferencias(),
                                   op.parametros)  # fmt: skip
    enfermeira = contexto(operacao_zerada, "enfermagem", Perfil.ENFERMAGEM)
    pacientes = []
    for escala in (SEG_1, SEG_1, TER_2):
        dados = dados_completos(fabrica)
        pid = op.cadastro.pacientes.criar(pessoa(operacao_zerada), dados, date(2026, 9, 1))
        op.escalas.alocar(enfermeira, pid, escala, date(2026, 9, 1))
        pacientes.append((pid, dados.nome or ""))
    yield Cenario(op, relatorios, operacao_zerada, pacientes)
    with engine_migracao.begin() as c:
        c.execute(text("DELETE FROM instituicao"))


def auditorias(engine: Engine, operacao: str) -> list[tuple[str, dict[str, list[object]]]]:
    with engine.connect() as c:
        sql = "SELECT entidade_id, alteracoes FROM auditoria WHERE operacao = :o ORDER BY id"
        return [(e, json.loads(a)) for e, a in c.execute(text(sql), {"o": operacao})]


# ------------------------------------------------------------------ CT-REL-01
@pytest.mark.requisito("RF-913", "RF-906", "RF-916", "DEC-66", "CT-REL-01")
def test_relatorio_mensal_bloqueado_com_a_lista_do_que_falta(cenario: Cenario) -> None:
    admin = cenario.de(Perfil.ADMINISTRACAO)
    setembro = Filtros(competencia="2026-09")
    with pytest.raises(RegraViolada) as erro:
        cenario.relatorios.gerar(admin, Relatorio.FREQUENCIA_MENSAL, setembro)
    assert erro.value.codigo == "relatorio.mes_incompleto" and erro.value.detalhe["quantidade"] == 9
    assert erro.value.detalhe["pendentes"][:3] == [("28/09/2026", "Primeiro turno"), ("28/09/2026", "Segundo turno"),
                                                   ("28/09/2026", "Terceiro turno")]  # fmt: skip
    cenario.fechar_setembro()
    tabela = cenario.relatorios.gerar(admin, Relatorio.FREQUENCIA_MENSAL, setembro)
    assert [c.titulo for c in tabela.colunas] == ["Paciente", "Prontuário", "Previstas", "Realizadas", "Ausências",
                                                  "Extras"]  # fmt: skip
    por_nome = {linha[0]: linha[2:] for linha in tabela.linhas}
    primeiro, _, terca = cenario.pacientes
    assert por_nome[primeiro[1]] == (2, 2, 0, 0) and por_nome[terca[1]] == (1, 1, 0, 0)  # 28 e 30; 29
    balanco = cenario.relatorios.gerar(admin, Relatorio.BALANCO_MENSAL, Filtros(competencia="2026-09",
                                                                               paciente_id=terca[0]))  # fmt: skip
    assert [linha[0] for linha in balanco.linhas] == [terca[1]] and ("Paciente", terca[1]) in balanco.filtros
    with pytest.raises(RegraViolada) as erro:  # outubro ainda está em aberto: só a prévia (DD-47)
        cenario.relatorios.gerar(admin, Relatorio.BALANCO_MENSAL, Filtros(competencia="2026-10"))
    assert erro.value.codigo == "relatorio.mes_incompleto"


@pytest.mark.requisito("DD-47", "RF-916")
def test_previa_do_mes_corrente_com_a_marca(cenario: Cenario) -> None:
    tabela = cenario.relatorios.gerar(cenario.de(Perfil.RECEPCAO), Relatorio.PREVIA, Filtros())
    assert tabela.titulo == "PRÉVIA — mês em aberto" and ("Competência", "10/2026") in tabela.filtros
    assert [m.tipo for m in tabela.marcas] == ["previa"] and len(tabela.linhas) == 3


@pytest.mark.requisito("RF-915", "DD-26", "P-21")
def test_mes_alterado_aparece_nos_relatorios_de_frequencia_do_periodo(cenario: Cenario, engine_web: Engine) -> None:
    cenario.fechar_setembro()
    recepcao, admin = pessoa(cenario.ids), cenario.de(Perfil.ADMINISTRACAO)
    pid = cenario.pacientes[0][0]
    sid = cenario.op.turnos.solicitar_alteracao_confirmada(recepcao, date(2026, 9, 28), SEG_1, pid, False,
                                                            "Presença lançada por engano")  # fmt: skip
    cenario.op.autorizacoes.aprovar(admin, sid)
    for relatorio, filtros in ((Relatorio.FREQUENCIA_MENSAL, Filtros(competencia="2026-09")),
                               (Relatorio.RECORTE_LIVRE, OUTUBRO)):  # fmt: skip
        marcas = [
            m.texto for m in cenario.relatorios.gerar(admin, relatorio, filtros).marcas if m.tipo == "mes_alterado"
        ]
        assert marcas == ["Mês 09/2026 alterado após o fechamento em 13/10/2026. Motivo: Presença lançada por engano"]
    sexo = cenario.relatorios.gerar(admin, Relatorio.SEXO, Filtros(data_referencia=date(2026, 9, 30)))
    assert sexo.marcas == ()  # a marca é só dos relatórios de frequência (DEC-69)


@pytest.mark.requisito("RF-914", "RF-907")
def test_recorte_livre_sinaliza_sessoes_nao_confirmadas_e_o_inicio_da_serie(cenario: Cenario) -> None:
    cenario.fechar_setembro()
    tabela = cenario.relatorios.gerar(cenario.de(Perfil.ENFERMAGEM), Relatorio.RECORTE_LIVRE, OUTUBRO)
    tipos = [m.tipo for m in tabela.marcas]
    assert tipos[:2] == ["inicio_serie", "nao_confirmadas"]
    assert tabela.marcas[0].texto == "Série histórica a partir de 28/09/2026, data de implantação do sistema."
    assert {linha[0]: linha[2] for linha in tabela.linhas}[cenario.pacientes[0][1]] == 2  # 28 e 30 de setembro


@pytest.mark.requisito("RF-902", "RF-903", "RF-905", "RF-908", "RF-910", "RF-911", "RF-901")
def test_relatorios_gerenciais_e_ocupacao(cenario: Cenario) -> None:
    visualizador = cenario.de(Perfil.VISUALIZADOR)
    na_data = Filtros(data_referencia=date(2026, 10, 13))
    setembro = Filtros(inicio=date(2026, 9, 1), fim=date(2026, 9, 30))
    entradas = cenario.relatorios.gerar(visualizador, Relatorio.ENTRADAS, setembro)
    assert len(entradas.linhas) == 3 and entradas.marcas[0].tipo == "inicio_serie"
    for relatorio in (Relatorio.CIDADE, Relatorio.SEXO, Relatorio.FAIXA_ETARIA):
        total = cenario.relatorios.gerar(visualizador, relatorio, na_data).linhas[-1]
        assert total == ("Total", 3), relatorio
    convenio = cenario.relatorios.gerar(visualizador, Relatorio.CONVENIO, na_data)
    assert convenio.linhas == (("Não informado", 3), ("Total", 3)) and ("Modo", "Situação na data") in convenio.filtros
    periodo = cenario.relatorios.gerar(visualizador, Relatorio.CONVENIO, Filtros(
        modo_convenio=ModoConvenio.PERIODO, inicio=date(2026, 9, 1), fim=date(2026, 10, 13)))  # fmt: skip
    assert periodo.linhas[-1] == ("Total de pacientes", 3)
    ocupacao = cenario.relatorios.gerar(cenario.de(Perfil.ENFERMAGEM), Relatorio.OCUPACAO, na_data)
    contagem = dict(ocupacao.linhas)
    assert contagem["Primeiro turno — segunda, quarta e sexta"] == 2 and contagem["Total"] == 3
    eventos = cenario.relatorios.gerar(visualizador, Relatorio.EVENTOS, Filtros(inicio=date(2026, 9, 1),
                                                                                 fim=date(2026, 10, 13)))  # fmt: skip
    assert eventos.linhas == () and ("Tipo de evento", "Todos") in eventos.filtros


@pytest.mark.requisito("RF-901")
@pytest.mark.parametrize(
    ("relatorio", "filtros", "codigo"),
    [
        (Relatorio.ENTRADAS, Filtros(), "relatorio.filtro.periodo"),
        (Relatorio.ENTRADAS, Filtros(inicio=date(2026, 10, 2), fim=date(2026, 10, 1)), "relatorio.filtro.periodo"),
        (Relatorio.SEXO, Filtros(), "relatorio.filtro.data_referencia"),
        (Relatorio.FREQUENCIA_MENSAL, Filtros(competencia="2026-13"), "relatorio.filtro.competencia"),
        (Relatorio.EVENTOS, Filtros(inicio=date(2026, 1, 1), fim=date(2026, 2, 1), tipo_evento="fuga"),
         "relatorio.filtro.tipo_evento"),
        (Relatorio.CONVENIO, Filtros(modo_convenio=ModoConvenio.PERIODO), "relatorio.filtro.periodo"),
    ],
)  # fmt: skip
def test_filtro_faltante_ou_invalido_e_recusado(
    cenario: Cenario, relatorio: Relatorio, filtros: Filtros, codigo: str
) -> None:
    with pytest.raises(RegraViolada) as erro:
        cenario.relatorios.gerar(cenario.de(Perfil.ADMINISTRACAO), relatorio, filtros)
    assert erro.value.codigo == codigo


@pytest.mark.requisito("P-20", "DEC-55", "RF-1004")
def test_cada_perfil_ve_os_relatorios_que_lhe_cabem(cenario: Cenario) -> None:
    operacionais = [Relatorio.FREQUENCIA_MENSAL, Relatorio.BALANCO_MENSAL, Relatorio.PREVIA, Relatorio.OCUPACAO,
                    Relatorio.RECORTE_LIVRE]  # fmt: skip
    assert cenario.relatorios.disponiveis(cenario.de(Perfil.RECEPCAO)) == operacionais
    assert cenario.relatorios.disponiveis(cenario.de(Perfil.ENFERMAGEM)) == operacionais
    assert cenario.relatorios.disponiveis(cenario.de(Perfil.VISUALIZADOR)) == list(Relatorio)
    assert cenario.relatorios.disponiveis(cenario.de(Perfil.ADMINISTRACAO)) == list(Relatorio)
    assert cenario.relatorios.disponiveis(cenario.de(Perfil.TI)) == []
    na_data = Filtros(data_referencia=date(2026, 10, 13))
    for perfil in (Perfil.RECEPCAO, Perfil.ENFERMAGEM, Perfil.TI):
        with pytest.raises(AcessoNegado):
            cenario.relatorios.gerar(cenario.de(perfil), Relatorio.SEXO, na_data)
    with pytest.raises(AcessoNegado):
        cenario.relatorios.gerar(cenario.de(Perfil.TI), Relatorio.OCUPACAO, na_data)


@pytest.mark.requisito("RNF-607", "DD-45", "RF-912")
def test_ver_e_exportar_auditados_com_os_filtros_e_so_a_administracao_exporta(
    cenario: Cenario, engine_web: Engine
) -> None:
    na_data = Filtros(data_referencia=date(2026, 10, 13))
    cenario.relatorios.gerar(cenario.de(Perfil.VISUALIZADOR), Relatorio.SEXO, na_data)
    assert auditorias(engine_web, "relatorio.gerencial.ver") == [
        ("sexo", {"filtros": [None, "data_referencia=2026-10-13"]})
    ]
    for perfil in (Perfil.RECEPCAO, Perfil.VISUALIZADOR, Perfil.ENFERMAGEM):
        with pytest.raises(AcessoNegado):
            cenario.relatorios.exportar(cenario.de(perfil), Relatorio.OCUPACAO, na_data, FormatoExportacao.XLSX)
    admin = cenario.de(Perfil.ADMINISTRACAO)
    xlsx = cenario.relatorios.exportar(admin, Relatorio.OCUPACAO, na_data, FormatoExportacao.XLSX)
    pdf = cenario.relatorios.exportar(admin, Relatorio.OCUPACAO, na_data, FormatoExportacao.PDF)
    assert xlsx.conteudo.startswith(b"PK") and xlsx.nome_arquivo == "ocupacao-2026-10-13.xlsx"
    assert pdf.conteudo.startswith(b"%PDF-") and pdf.tipo_mime == "application/pdf"
    assert auditorias(engine_web, "relatorio.exportar") == [
        ("ocupacao", {"formato": [None, "xlsx"], "filtros": [None, "data_referencia=2026-10-13"]}),
        ("ocupacao", {"formato": [None, "pdf"], "filtros": [None, "data_referencia=2026-10-13"]}),
    ]
