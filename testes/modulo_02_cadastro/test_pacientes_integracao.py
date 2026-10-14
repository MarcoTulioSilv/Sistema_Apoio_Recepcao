"""Paciente no MySQL, pelo usuário de banco da web: CT-CAD-01 a 03, INV-07, INV-15, DD-17."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date

import pytest
from sqlalchemy import Engine, text

from sar.modulo_02_cadastro.contrato import DadosPaciente, Situacao
from sar.modulo_02_cadastro.regras import CAMPOS_DE_PENDENCIA, CEP_NAO_VERIFICADO
from sar.nucleo.contexto import Perfil
from sar.nucleo.erros import AcessoNegado, ConfirmacaoNecessaria, ConflitoDeVersao, NaoEncontrado, RegraViolada
from testes.apoio.cadastro import INICIO, JATAI, dados_completos, montar, pessoa
from testes.apoio.fabrica import Fabrica

pytestmark = pytest.mark.integracao


def auditorias(engine: Engine, operacao: str) -> list[tuple[str, str]]:
    sql = "SELECT entidade_id, alteracoes FROM auditoria WHERE operacao = :o ORDER BY id"
    with engine.connect() as c:
        return [(str(a), str(b)) for a, b in c.execute(text(sql), {"o": operacao})]


def contar(engine: Engine, tabela: str) -> int:
    with engine.connect() as c:
        return int(c.execute(text(f"SELECT COUNT(*) FROM {tabela}")).scalar_one())  # noqa: S608 — nome fixo do teste


# ------------------------------------------------------------------ CT-CAD-01: mínimo
@pytest.mark.requisito("CT-CAD-01", "RF-102", "RNF-605")
def test_com_o_minimo_cria_paciente_com_periodo_aberto_e_pendencias(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    nome = fabrica.nome()
    pid = cadastro.pacientes.criar(recepcao, DadosPaciente(nome=f"  {nome} ", prontuario="F000123"), INICIO)
    ficha = cadastro.pacientes.ver_ficha(recepcao, pid)
    assert (ficha.dados.nome, ficha.dados.prontuario, ficha.versao) == (nome, "F000123", 1)
    assert [(p.inicio, p.evento_tipo) for p in ficha.periodos] == [(INICIO, None)]
    assert ficha.situacao is Situacao.SEM_ALOCACAO and ficha.pendencias == CAMPOS_DE_PENDENCIA
    [(entidade_id, alteracoes)] = auditorias(engine_web, "cadastro.paciente.criar")
    assert entidade_id == str(pid) and '"periodo_inicio":[null,"2026-10-01"]' in alteracoes


@pytest.mark.requisito("CT-CAD-01", "RF-102")
@pytest.mark.parametrize(
    ("dados", "inicio"),
    [(DadosPaciente(nome="Ana Fictício"), INICIO), (DadosPaciente(prontuario="F1"), INICIO),
     (DadosPaciente(nome="Ana Fictício", prontuario="F1"), None)],
)  # fmt: skip
def test_abaixo_do_minimo_nada_e_gravado(
    cadastro_zerado: dict[str, int], engine_web: Engine, dados: DadosPaciente, inicio: date | None
) -> None:
    with pytest.raises(RegraViolada) as erro:
        montar(engine_web).pacientes.criar(pessoa(cadastro_zerado), dados, inicio)
    assert erro.value.codigo == "P-03.minimo"
    assert contar(engine_web, "paciente") == 0 and contar(engine_web, "auditoria") == 0


# ------------------------------------------------------------------ CT-CAD-02: CPF, CNS e prontuário
@pytest.mark.requisito("CT-CAD-02", "INV-07", "INV-15", "RF-104")
@pytest.mark.parametrize("campo", ["prontuario", "cpf", "cns"])
def test_numero_repetido_e_recusado_informando_quem_ja_usa(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica, campo: str
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    primeiro = dados_completos(fabrica)
    pid = cadastro.pacientes.criar(recepcao, primeiro, INICIO)
    segundo = replace(dados_completos(fabrica), **{campo: getattr(primeiro, campo)})
    with pytest.raises(RegraViolada) as erro:
        cadastro.pacientes.criar(recepcao, segundo, INICIO)
    assert (erro.value.codigo, erro.value.detalhe) == (f"{campo}.repetido", {"paciente_id": pid})
    assert contar(engine_web, "paciente") == 1


@pytest.mark.requisito("CT-CAD-02", "INV-15")
def test_cpf_e_cns_ausentes_em_varios_pacientes_e_invalido_recusado(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    for prontuario in ("F1", "F2"):
        cadastro.pacientes.criar(recepcao, DadosPaciente(nome=fabrica.nome(), prontuario=prontuario), INICIO)
    with pytest.raises(RegraViolada) as erro:
        cadastro.pacientes.criar(
            recepcao, DadosPaciente(nome=fabrica.nome(), prontuario="F3", cpf="111.111.111-11"), INICIO
        )
    assert erro.value.codigo == "cpf.invalido" and contar(engine_web, "paciente") == 2


@pytest.mark.requisito("INV-07", "INV-15")
def test_criacoes_simultaneas_do_mesmo_prontuario_gravam_uma_so(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    nomes = [fabrica.nome() for _ in range(4)]

    def criar(nome: str) -> str:
        try:
            cadastro.pacientes.criar(recepcao, DadosPaciente(nome=nome, prontuario="F777"), INICIO)
        except RegraViolada as erro:
            return erro.codigo
        return "ok"

    with ThreadPoolExecutor(4) as grupo:
        assert sorted(grupo.map(criar, nomes)) == ["ok"] + ["prontuario.repetido"] * 3


# ------------------------------------------------------------------ CT-CAD-03: tríade
@pytest.mark.requisito("CT-CAD-03", "INV-08", "RF-108")
def test_triade_coincidente_pede_confirmacao_e_fica_como_possivel_duplicidade(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    original = dados_completos(fabrica)
    pid = cadastro.pacientes.criar(recepcao, original, INICIO)
    assert original.nome is not None and original.nome_mae is not None
    parecido = replace(
        dados_completos(fabrica),
        nome=original.nome.upper(),
        nome_mae=" ".join(original.nome_mae.split()).lower(),
        data_nascimento=original.data_nascimento,
    )
    with pytest.raises(ConfirmacaoNecessaria) as alerta:
        cadastro.pacientes.criar(recepcao, parecido, INICIO)
    assert (alerta.value.codigo, alerta.value.dados) == ("triade", {"candidatos": [pid]})
    assert contar(engine_web, "paciente") == 1  # nada gravado antes da confirmação

    outro = cadastro.pacientes.criar(recepcao, parecido, INICIO, confirmar_duplicidade=True)
    assert [d.paciente_id for d in cadastro.pacientes.ver_ficha(recepcao, outro).possiveis_duplicatas] == [pid]
    cadastro.pacientes.descartar_duplicidade(recepcao, outro, pid)
    cadastro.pacientes.descartar_duplicidade(recepcao, pid, outro)  # de novo, ao contrário: nada muda
    assert cadastro.pacientes.ver_ficha(recepcao, pid).possiveis_duplicatas == ()
    assert len(auditorias(engine_web, "cadastro.paciente.descartar_duplicidade")) == 1


@pytest.mark.requisito("CT-CAD-03", "INV-08")
def test_triade_adiada_sem_um_dos_tres_e_avaliada_na_atualizacao(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    original = dados_completos(fabrica)
    pid = cadastro.pacientes.criar(recepcao, original, INICIO)
    incompleto = replace(dados_completos(fabrica), nome=original.nome, data_nascimento=original.data_nascimento,
                         nome_mae=None)  # fmt: skip
    outro = cadastro.pacientes.criar(recepcao, incompleto, INICIO)  # sem a mãe: nenhum alerta
    cadastro.pacientes.atualizar(recepcao, outro, 1, replace(incompleto, nome_mae=original.nome_mae))
    assert [d.paciente_id for d in cadastro.pacientes.ver_ficha(recepcao, outro).possiveis_duplicatas] == [pid]
    with pytest.raises(NaoEncontrado):
        cadastro.pacientes.descartar_duplicidade(recepcao, pid, pid + 999_999)
    terceiro = cadastro.pacientes.criar(recepcao, dados_completos(fabrica), INICIO)
    with pytest.raises(RegraViolada) as erro:
        cadastro.pacientes.descartar_duplicidade(recepcao, pid, terceiro)
    assert erro.value.codigo == "duplicidade.sem_coincidencia"


# ------------------------------------------------------------------ residência e naturalidade
@pytest.mark.requisito("RF-111")
def test_residencia_so_em_goias_e_naturalidade_nacional(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    base = DadosPaciente(nome=fabrica.nome(), prontuario="F10")
    casos = {"3550308": "municipio.fora_de_goias", "5299999": "municipio.inexistente"}  # São Paulo; inexistente
    for codigo, esperado in casos.items():
        with pytest.raises(RegraViolada) as erro:
            cadastro.pacientes.criar(recepcao, replace(base, municipio=codigo), INICIO)
        assert erro.value.codigo == esperado
    pid = cadastro.pacientes.criar(recepcao, replace(base, municipio=JATAI, naturalidade_municipio="3550308"), INICIO)
    ficha = cadastro.pacientes.ver_ficha(recepcao, pid)
    assert ficha.residencia is not None and ficha.residencia.nome == "Jataí"
    assert ficha.naturalidade is not None and ficha.naturalidade.uf == "SP"


# ------------------------------------------------------------------ atualização (DD-17, DD-10)
@pytest.mark.requisito("DD-17", "RNF-605")
def test_atualizacao_com_versao_auditando_so_o_que_mudou(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    dados = replace(dados_completos(fabrica), cep="75800-000")
    pid = cadastro.pacientes.criar(recepcao, dados, INICIO)
    assert cadastro.pacientes.atualizar(recepcao, pid, 1, dados) == 1  # nada mudou: mesma versão
    assert cadastro.pacientes.atualizar(recepcao, pid, 1, replace(dados, bairro="Centro")) == 2
    with pytest.raises(ConflitoDeVersao):
        cadastro.pacientes.atualizar(recepcao, pid, 1, replace(dados, bairro="Vila Fátima"))
    assert auditorias(engine_web, "cadastro.paciente.atualizar") == [(str(pid), '{"bairro":[null,"Centro"]}')]
    with pytest.raises(NaoEncontrado):
        cadastro.pacientes.atualizar(recepcao, pid + 999_999, 1, dados)


@pytest.mark.requisito("QAS-03", "RF-109")
def test_cep_alterado_volta_a_nao_verificado(
    cadastro_zerado: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    dados = replace(dados_completos(fabrica), cep="75800000")
    pid = cadastro.pacientes.criar(recepcao, dados, INICIO)
    assert CEP_NAO_VERIFICADO in cadastro.pacientes.ver_ficha(recepcao, pid).pendencias
    with engine_migracao.begin() as c:
        c.execute(text("UPDATE paciente SET cep_verificado = 1 WHERE id = :p"), {"p": pid})
    cadastro.pacientes.atualizar(recepcao, pid, 1, replace(dados, numero="10"))
    assert CEP_NAO_VERIFICADO not in cadastro.pacientes.ver_ficha(recepcao, pid).pendencias
    cadastro.pacientes.atualizar(recepcao, pid, 2, replace(dados, numero="10", cep="75801000"))
    assert CEP_NAO_VERIFICADO in cadastro.pacientes.ver_ficha(recepcao, pid).pendencias


# ------------------------------------------------------------------ busca e permissões
@pytest.mark.requisito("RF-107", "CT-ACE-01")
def test_busca_por_nome_sem_acento_ou_numero_exato_sem_anulados(
    cadastro_zerado: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    dados = replace(dados_completos(fabrica), nome="Conceição Aparecida Fictício", prontuario="F555")
    pid = cadastro.pacientes.criar(recepcao, dados, INICIO)
    assert dados.cpf is not None and dados.cns is not None
    cpf_formatado = f"{dados.cpf[:3]}.{dados.cpf[3:6]}.{dados.cpf[6:9]}-{dados.cpf[9:]}"
    for termo in ("conceicao", "APARECIDA FICT", "F555", cpf_formatado, dados.cns):
        assert [i.paciente_id for i in cadastro.pacientes.buscar(recepcao, termo)] == [pid], termo
    assert cadastro.pacientes.buscar(recepcao, "c") == [] and cadastro.pacientes.buscar(recepcao, "%") == []
    visualizador = pessoa(cadastro_zerado, "admin", Perfil.VISUALIZADOR)
    assert len(cadastro.pacientes.buscar(visualizador, "conceicao")) == 1
    enfermagem = pessoa(cadastro_zerado, "admin", Perfil.ENFERMAGEM)
    assert len(cadastro.pacientes.buscar(enfermagem, "conceicao")) == 1
    with pytest.raises(AcessoNegado):
        cadastro.pacientes.ver_ficha(enfermagem, pid)
    ti = pessoa(cadastro_zerado, "ti", Perfil.TI)
    for chamada in (lambda: cadastro.pacientes.buscar(ti, "conceicao"), lambda: cadastro.pacientes.ver_ficha(ti, pid)):
        with pytest.raises(AcessoNegado):
            chamada()
    with engine_migracao.begin() as c:
        c.execute(text("UPDATE paciente SET anulado_em = NOW(6) WHERE id = :p"), {"p": pid})
    assert cadastro.pacientes.buscar(recepcao, "conceicao") == []
    with pytest.raises(NaoEncontrado):
        cadastro.pacientes.ver_ficha(recepcao, pid)


# ------------------------------------------------------------------ leituras para os outros módulos
@pytest.mark.requisito("INV-01", "INV-03", "INV-04")
def test_leituras_de_periodo_e_obito(
    cadastro_zerado: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    pid = cadastro.pacientes.criar(recepcao, dados_completos(fabrica), date(2026, 1, 10))
    leitura, executar = cadastro.leitura, cadastro.executar
    identificacao = executar(lambda uow: leitura.identificacao(uow, pid))
    assert identificacao is not None and identificacao.paciente_id == pid
    assert executar(lambda uow: leitura.periodo_aberto_em(uow, pid, date(2026, 1, 9))) is None
    aberto = executar(lambda uow: leitura.periodo_aberto_em(uow, pid, date(2026, 5, 1)))
    assert aberto is not None and (aberto.inicio, aberto.fim) == (date(2026, 1, 10), None)
    assert executar(lambda uow: leitura.pacientes_com_periodo_aberto_em(uow, date(2026, 5, 1))) == [pid]
    assert executar(lambda uow: leitura.data_obito(uow, pid)) is None
    with engine_migracao.begin() as c:
        c.execute(
            text(
                "UPDATE periodo_tratamento SET evento_tipo = 'obito', evento_data = '2026-06-01' WHERE paciente_id = :p"
            ),
            {"p": pid},
        )
    assert executar(lambda uow: leitura.data_obito(uow, pid)) == date(2026, 6, 1)
    no_dia = executar(lambda uow: leitura.periodo_aberto_em(uow, pid, date(2026, 6, 1)))
    assert no_dia is not None and no_dia.fim == date(2026, 6, 1)  # o dia do evento ainda é do período
    assert executar(lambda uow: leitura.periodo_aberto_em(uow, pid, date(2026, 6, 2))) is None
    assert executar(lambda uow: leitura.pacientes_com_periodo_aberto_em(uow, date(2026, 6, 2))) == []
    assert cadastro.pacientes.ver_ficha(recepcao, pid).situacao is Situacao.FALECIDO


@pytest.mark.requisito("RF-111", "INV-15")
def test_atualizacao_recusa_numero_de_outro_e_naturalidade_inexistente(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    primeiro = dados_completos(fabrica)
    pid = cadastro.pacientes.criar(recepcao, primeiro, INICIO)
    segundo = dados_completos(fabrica)
    outro = cadastro.pacientes.criar(recepcao, segundo, INICIO)
    casos = {"cpf": primeiro.cpf, "naturalidade_municipio": "5299999"}
    esperados = {"cpf": "cpf.repetido", "naturalidade_municipio": "naturalidade_municipio.inexistente"}
    for campo, valor in casos.items():
        with pytest.raises(RegraViolada) as erro:
            cadastro.pacientes.atualizar(recepcao, outro, 1, replace(segundo, **{campo: valor}))
        assert erro.value.codigo == esperados[campo]
    assert cadastro.pacientes.atualizar(recepcao, pid, 1, replace(primeiro, cpf=primeiro.cpf)) == 1  # o próprio


@pytest.mark.requisito("RF-1008")
def test_anulado_nao_existe_para_os_outros_modulos(
    cadastro_zerado: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    pid = cadastro.pacientes.criar(pessoa(cadastro_zerado), dados_completos(fabrica), INICIO)
    with engine_migracao.begin() as c:
        c.execute(text("UPDATE paciente SET anulado_em = NOW(6) WHERE id = :p"), {"p": pid})
    leitura, executar = cadastro.leitura, cadastro.executar
    assert executar(lambda uow: leitura.identificacao(uow, pid)) is None
    assert executar(lambda uow: leitura.periodo_aberto_em(uow, pid, INICIO)) is None
    assert executar(lambda uow: leitura.data_obito(uow, pid)) is None
    assert executar(lambda uow: leitura.pacientes_com_periodo_aberto_em(uow, INICIO)) == []


@pytest.mark.requisito("DEC-55", "DD-10", "RNF-605")
def test_busca_e_ficha_sao_auditadas_sem_o_termo(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    """DDS §4.2: busca auditada só com a quantidade; ver a ficha também é auditado (DEC-55)."""
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    dados = dados_completos(fabrica)
    pid = cadastro.pacientes.criar(recepcao, dados, INICIO)
    assert dados.nome is not None
    cadastro.pacientes.buscar(recepcao, dados.nome)
    cadastro.pacientes.ver_ficha(recepcao, pid)
    assert auditorias(engine_web, "cadastro.paciente.buscar") == [("None", '{"quantidade":[null,1]}')]
    assert auditorias(engine_web, "cadastro.paciente.ver_ficha") == [(str(pid), "None")]
    with engine_web.connect() as c:
        leituras = "'cadastro.paciente.buscar', 'cadastro.paciente.ver_ficha'"
        textos = c.execute(text(f"SELECT COALESCE(alteracoes, '') FROM auditoria WHERE operacao IN ({leituras})"))  # noqa: S608
        assert all(dados.nome not in linha for (linha,) in textos)


@pytest.mark.requisito("RF-107")
def test_busca_por_nome_com_acento(cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica) -> None:
    """Defeito encontrado ao auditar a busca: o termo ia também às colunas ASCII de CPF e CNS, e um nome com acento
    ("José") derrubava a consulta no MySQL."""
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    pid = cadastro.pacientes.criar(recepcao, replace(dados_completos(fabrica), nome="José Conceição Fictício"), INICIO)
    for termo in ("José", "conceição", "JOSE CONCEICAO"):
        assert [i.paciente_id for i in cadastro.pacientes.buscar(recepcao, termo)] == [pid], termo
