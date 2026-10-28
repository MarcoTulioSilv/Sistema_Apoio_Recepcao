"""Regras puras do cadastro (DDS §6.2, §6.3): CT-CAD-01 e a parte sem banco do CT-CAD-02."""

from __future__ import annotations

from datetime import date

import pytest
from faker import Faker
from hypothesis import given
from hypothesis import strategies as st

from sar.modulo_02_cadastro.contrato import DadosPaciente, Sexo, Situacao, TipoCobertura, TipoEvento, TipoTelefone
from sar.modulo_02_cadastro.regras import (
    CAMPOS_DE_PENDENCIA,
    CEP_NAO_VERIFICADO,
    campos_alterados,
    chave_triade,
    cns_valido,
    cpf_valido,
    idade,
    normalizar,
    pendencias,
    situacao,
    validar_cobertura,
    validar_contato,
    validar_evento,
    validar_telefone,
    verificar_abertura,
    verificar_inicio,
    verificar_minimo,
    verificar_nova_cobertura,
)
from sar.nucleo.erros import RegraViolada
from testes.apoio.fabrica import Fabrica, cns_definitivo

HOJE = date(2026, 10, 13)


def codigo(chamada: object) -> str:
    assert callable(chamada)
    with pytest.raises(RegraViolada) as erro:
        chamada()
    return erro.value.codigo


# ------------------------------------------------------------------ CPF e CNS (CT-CAD-02, DD-22)
@pytest.mark.requisito("CT-CAD-02", "RF-103")
@given(st.integers(min_value=0, max_value=2**31))
def test_cpf_gerado_pelo_faker_e_valido_com_ou_sem_pontuacao(semente: int) -> None:
    faker = Faker("pt_BR")
    faker.seed_instance(semente)
    formatado = faker.cpf()  # "123.456.789-09": oráculo independente do nosso algoritmo
    assert normalizar(DadosPaciente(cpf=formatado), HOJE).cpf == formatado.replace(".", "").replace("-", "")


@pytest.mark.requisito("CT-CAD-02", "RF-103", "DD-22")
@pytest.mark.parametrize("cpf", ["111.111.111-11", "000.000.000-00", "123.456.789-00", "529.982.247-24", "1234567890"])
def test_cpf_invalido_conhecido_e_recusado(cpf: str) -> None:
    assert codigo(lambda: normalizar(DadosPaciente(cpf=cpf), HOJE)) == "cpf.invalido"


@pytest.mark.requisito("CT-CAD-02", "RF-103")
@given(st.integers(min_value=0, max_value=2**31))
def test_cns_definitivo_e_valido_e_trocar_o_digito_final_invalida(semente: int) -> None:
    cns = Fabrica(semente).cns()
    assert cns_valido(cns)
    assert sum(int(c) * (15 - i) for i, c in enumerate(cns)) % 11 == 0  # propriedade do DATASUS, independente
    trocado = cns[:-1] + str((int(cns[-1]) + 1) % 10)
    assert not cns_valido(trocado)


@pytest.mark.requisito("CT-CAD-02", "RF-103")
@given(st.text(alphabet="0123456789", min_size=14, max_size=14), st.sampled_from("789"))
def test_cns_provisorio_vale_quando_a_soma_ponderada_e_multipla_de_11(corpo: str, inicio: str) -> None:
    cns = inicio + corpo
    assert cns_valido(cns) == (sum(int(c) * (15 - i) for i, c in enumerate(cns)) % 11 == 0)


@pytest.mark.requisito("CT-CAD-02", "RF-103", "DD-22")
@pytest.mark.parametrize("cns", ["123456789012345", "312345678901234", "000000000000000", "1234", "7" * 15])
def test_cns_invalido_conhecido_e_recusado(cns: str) -> None:
    assert codigo(lambda: normalizar(DadosPaciente(cns=cns), HOJE)) == "cns.invalido"


@pytest.mark.requisito("CT-CAD-02", "RF-103")
def test_cpf_e_cns_ausentes_passam_e_viram_pendencia() -> None:
    dados = normalizar(DadosPaciente(nome="Ana Fictício", prontuario="F1", cpf="  ", cns=""), HOJE)
    assert dados.cpf is None and dados.cns is None
    assert {"cpf", "cns"} <= set(pendencias(dados, cep_verificado=False))


@pytest.mark.requisito("CT-CAD-02")
def test_letra_no_meio_do_numero_e_erro_e_nao_e_descartada() -> None:
    assert codigo(lambda: normalizar(DadosPaciente(cpf="529.982.247-2S"), HOJE)) == "cpf.invalido"
    assert codigo(lambda: normalizar(DadosPaciente(cep="75800-0O0"), HOJE)) == "cep.invalido"
    assert codigo(lambda: normalizar(DadosPaciente(cep="7580-000"), HOJE)) == "cep.invalido"
    assert not cpf_valido("５２９９８２２４７２５")  # dígitos de largura total não são ASCII


def test_cns_de_dv_dez_usa_o_sufixo_001() -> None:
    pis = next(p for p in (f"1{n:010d}" for n in range(10**5)) if cns_definitivo(p)[11:14] == "001")
    assert cns_valido(cns_definitivo(pis))


# ------------------------------------------------------------------ mínimo e pendências (CT-CAD-01)
@pytest.mark.requisito("CT-CAD-01", "RF-102")
@pytest.mark.parametrize(
    ("nome", "prontuario", "inicio", "faltam"),
    [
        (None, None, None, ["nome", "prontuario", "inicio"]),
        ("Ana Fictício", None, HOJE, ["prontuario"]),
        ("Ana Fictício", "F1", None, ["inicio"]),
        (None, "F1", HOJE, ["nome"]),
    ],
)
def test_sem_o_minimo_da_p03_o_paciente_nao_e_criado(
    nome: str | None, prontuario: str | None, inicio: date | None, faltam: list[str]
) -> None:
    with pytest.raises(RegraViolada) as erro:
        verificar_minimo(DadosPaciente(nome=nome, prontuario=prontuario), inicio)
    assert erro.value.codigo == "P-03.minimo" and erro.value.detalhe == {"faltam": faltam}


@pytest.mark.requisito("CT-CAD-01", "RF-102")
def test_nome_so_de_espacos_conta_como_ausente() -> None:
    dados = normalizar(DadosPaciente(nome="   ", prontuario=" F1 "), HOJE)
    assert dados.prontuario == "F1"
    assert codigo(lambda: verificar_minimo(dados, HOJE)) == "P-03.minimo"


@pytest.mark.requisito("CT-CAD-01", "RF-102", "RF-109")
def test_com_o_minimo_os_faltantes_viram_pendencias_nomeadas_na_ordem_da_ficha() -> None:
    minimo = normalizar(DadosPaciente(nome="Ana Fictício", prontuario="F1"), HOJE)
    verificar_minimo(minimo, HOJE)
    assert pendencias(minimo, cep_verificado=False) == CAMPOS_DE_PENDENCIA
    completo = DadosPaciente(
        prontuario="F1", nome="Ana Fictício", data_nascimento=date(1960, 1, 2), sexo=Sexo.FEMININO,
        nome_mae="Maria Fictício", cpf="52998224725", cns=Fabrica(1).cns(), rg="123", rg_orgao="SSP/GO",
        naturalidade_municipio="5211909", logradouro="Rua A", numero="10", bairro="Centro", municipio="5211909",
        cep="75800000",
    )  # fmt: skip
    assert pendencias(completo, cep_verificado=True) == ()
    assert pendencias(completo, cep_verificado=False) == (CEP_NAO_VERIFICADO,)  # QAS-03


@pytest.mark.requisito("RF-101")
def test_textos_limpos_e_tamanho_da_coluna() -> None:
    dados = normalizar(DadosPaciente(nome="  Ana   Maria  Fictício ", municipio=" 5211909 "), HOJE)
    assert (dados.nome, dados.municipio) == ("Ana Maria Fictício", "5211909")
    assert codigo(lambda: normalizar(DadosPaciente(nome="x" * 151), HOJE)) == "nome.tamanho"
    assert codigo(lambda: normalizar(DadosPaciente(municipio="52119"), HOJE)) == "municipio.invalido"


def test_nascimento_futuro_ou_absurdo_e_inicio_antes_do_nascimento() -> None:
    assert codigo(lambda: normalizar(DadosPaciente(data_nascimento=date(2026, 10, 14)), HOJE)) == (
        "data_nascimento.invalida"
    )
    assert codigo(lambda: normalizar(DadosPaciente(data_nascimento=date(1899, 12, 31)), HOJE)) == (
        "data_nascimento.invalida"
    )
    assert codigo(lambda: verificar_inicio(date(1959, 12, 31), date(1960, 1, 1))) == "inicio.antes_do_nascimento"
    verificar_inicio(date(2020, 1, 1), None)


def test_auditoria_recebe_so_o_que_mudou_com_enum_como_texto() -> None:
    antes = DadosPaciente(nome="Ana Fictício", prontuario="F1")
    depois = DadosPaciente(nome="Ana Fictício", prontuario="F2", sexo=Sexo.FEMININO)
    assert campos_alterados(antes, depois) == {"prontuario": ("F1", "F2"), "sexo": (None, "F")}


# ------------------------------------------------------------------ tríade (INV-08), idade, situação
@pytest.mark.requisito("CT-CAD-03", "INV-08")
def test_triade_sem_acento_sem_caixa_e_sem_espacos_repetidos() -> None:
    a = chave_triade("José  da Conceição Fictício", date(1950, 5, 1), "MARIA DAS DORES Fictício")
    b = chave_triade("jose da conceicao fictício", date(1950, 5, 1), "Maria  das Dôres Ficticio")
    assert a is not None and a == b
    assert chave_triade("José Fictício", date(1950, 5, 2), "Maria Fictício") != chave_triade(
        "José Fictício", date(1950, 5, 1), "Maria Fictício"
    )


@pytest.mark.requisito("CT-CAD-03", "INV-08")
@pytest.mark.parametrize(
    ("nome", "nascimento", "mae"),
    [(None, date(1950, 5, 1), "Maria"), ("José", None, "Maria"), ("José", date(1950, 5, 1), None)],
)
def test_triade_adiada_enquanto_faltar_um_dos_tres(nome: str | None, nascimento: date | None, mae: str | None) -> None:
    assert chave_triade(nome, nascimento, mae) is None


@pytest.mark.requisito("RF-105")
def test_idade_calculada_na_data() -> None:
    assert idade(date(1960, 10, 13), HOJE) == 66
    assert idade(date(1960, 10, 14), HOJE) == 65
    assert idade(date(2000, 2, 29), date(2026, 2, 28)) == 25


@pytest.mark.parametrize(
    ("eventos", "alocado", "esperada"),
    [
        ([], False, Situacao.EM_CADASTRO),
        ([None], False, Situacao.SEM_ALOCACAO),
        ([None], True, Situacao.ATIVO),
        ([TipoEvento.ALTA], False, Situacao.INATIVO),
        ([TipoEvento.TRANSFERENCIA, None], True, Situacao.ATIVO),  # voltou (RF-605)
        ([TipoEvento.DESISTENCIA, TipoEvento.OBITO], False, Situacao.FALECIDO),
    ],
)
def test_situacao_derivada_pelo_ultimo_periodo(
    eventos: list[TipoEvento | None], alocado: bool, esperada: Situacao
) -> None:
    assert situacao(eventos, alocado) is esperada


# ------------------------------------------------------------------ contatos e telefones
@pytest.mark.requisito("RF-201", "RF-202", "DD-102")
def test_contato_exige_nome_parentesco_da_lista_e_telefone_por_tipo() -> None:
    assert validar_contato("  João Fictício ", " Filho ou filha ") == ("João Fictício", "Filho ou filha")
    assert validar_contato("João Fictício", " ") == ("João Fictício", None)
    assert codigo(lambda: validar_contato("  ", "Cônjuge")) == "contato.nome"
    # Antes, qualquer texto entrava como parentesco.
    assert codigo(lambda: validar_contato("João Fictício", "Padrasto")) == "contato.parentesco"
    assert validar_telefone("(64)", "99999-1234", TipoTelefone.CELULAR) == ("64", "999991234")
    assert validar_telefone("64", "3631-0000", TipoTelefone.FIXO) == ("64", "36310000")
    assert validar_telefone("64", "3631-0000", TipoTelefone.RECADO) == ("64", "36310000")
    assert codigo(lambda: validar_telefone("64", "3631-0000", TipoTelefone.CELULAR)) == "telefone.numero"
    assert codigo(lambda: validar_telefone("64", "99999-1234", TipoTelefone.FIXO)) == "telefone.numero"
    assert codigo(lambda: validar_telefone("20", "99999-1234", TipoTelefone.CELULAR)) == "telefone.ddd"
    assert codigo(lambda: validar_telefone("", "99999-1234", TipoTelefone.CELULAR)) == "telefone.ddd"
    assert codigo(lambda: validar_telefone("64", "", TipoTelefone.RECADO)) == "telefone.numero"


# ------------------------------------------------------------------ períodos e coberturas
@pytest.mark.requisito("INV-01", "INV-02", "RF-605")
def test_abertura_de_periodo() -> None:
    verificar_abertura(HOJE, ha_periodo_aberto=False, fim_anterior=date(2026, 1, 1), obito=None)
    assert codigo(lambda: verificar_abertura(HOJE, True, None, None)) == "INV-02"
    assert codigo(lambda: verificar_abertura(HOJE, False, date(2026, 1, 1), date(2026, 1, 1))) == "INV-01"
    assert codigo(lambda: verificar_abertura(date(2025, 12, 31), False, date(2026, 1, 1), None)) == (
        "periodo.antes_do_fim_anterior"
    )


@pytest.mark.requisito("RF-301", "RF-302", "INV-09", "DD-101")
def test_cobertura_sus_ou_convenio_uma_so_no_periodo_aberto() -> None:
    assert validar_cobertura(TipoCobertura.CONVENIO, 3, " 123 45 ") == "123 45"
    assert validar_cobertura(TipoCobertura.SUS, None, None) is None
    assert codigo(lambda: validar_cobertura(TipoCobertura.CONVENIO, None, None)) == "cobertura.convenio"
    assert codigo(lambda: validar_cobertura(TipoCobertura.SUS, 3, None)) == "cobertura.sus_sem_convenio"
    assert codigo(lambda: validar_cobertura(TipoCobertura.SUS, None, "123")) == "cobertura.sus_sem_convenio"
    verificar_nova_cobertura(periodo_aberto=True, ja_tem_cobertura=False)
    assert codigo(lambda: verificar_nova_cobertura(True, True)) == "INV-09"
    assert codigo(lambda: verificar_nova_cobertura(False, False)) == "cobertura.periodo_encerrado"


# ------------------------------------------------------------------ evento
@pytest.mark.requisito("RF-601", "RF-602", "INV-01")
def test_regras_do_evento() -> None:
    inicio = date(2026, 1, 1)
    assert validar_evento(TipoEvento.OBITO, HOJE, " Hospital X ", inicio, True, None, HOJE) == "Hospital X"
    assert validar_evento(TipoEvento.ALTA, inicio, None, inicio, True, None, HOJE) is None
    casos = [
        ((TipoEvento.ALTA, HOJE, None, inicio, True, date(2026, 5, 1), HOJE), "INV-01"),
        ((TipoEvento.ALTA, HOJE, None, inicio, False, None, HOJE), "evento.periodo_encerrado"),
        ((TipoEvento.ALTA, date(2025, 12, 31), None, inicio, True, None, HOJE), "evento.antes_do_inicio"),
        ((TipoEvento.ALTA, date(2026, 10, 14), None, inicio, True, None, HOJE), "evento.data_futura"),
        ((TipoEvento.ALTA, HOJE, "Casa", inicio, True, None, HOJE), "evento.local_nao_se_aplica"),
        ((TipoEvento.DESISTENCIA, HOJE, "Casa", inicio, True, None, HOJE), "evento.local_nao_se_aplica"),
    ]
    for argumentos, esperado in casos:
        assert codigo(lambda a=argumentos: validar_evento(*a)) == esperado
