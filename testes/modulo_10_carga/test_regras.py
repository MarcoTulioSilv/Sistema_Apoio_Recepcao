"""Regras puras da carga (DDS §14.1, DD-114), sem banco nem arquivo. As fichas seguem o formato do perfilamento da
fase 1, com dados inventados aqui mesmo (nenhum valor vem de planilha real)."""

from __future__ import annotations

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sar.modulo_10_carga import regras
from sar.modulo_10_carga.regras import BlocoP1, CelulaP1, Desfecho, LinhaP3, LinhaP4

HOJE = date(2026, 11, 11)


def bloco(*pares: tuple[str, object], linha: int = 1) -> BlocoP1:
    return BlocoP1(linha, tuple(CelulaP1(linha + i, r, v) for i, (r, v) in enumerate(pares)))  # type: ignore[arg-type]


FICHA = (
    ("PACIENTE:", "JOAO DA SILVA FICTICIO   Nº PT: 0314"),
    ("NOME DA MÃE:", "MARIA DA SILVA FICTICIA"),
    ("DATA DE NASC:", date(1960, 4, 2)),
    ("ENDEREÇO:", "RUA DAS FLORES QD 12 LT 5 Nº 120 SETOR CENTRAL"),
    ("CIDADE /CEP:", "JATAI -GO   CEP: 75805-640   CÓD.IBGE: 521190"),
    ("TELEFONE", "(64) 99999.0001  PACIENTE  (64)98888-0002  ANA PAULA (esposa)  3631.0003  BETO (filho)"),
    ("DOC.PESSOAIS: ", "CPF: 529.982.247-25  RG: 1234567  ORGÃO EXPEDIDOR: SSP-GO"),
    ("CONVENIO:", "SUS   CNS: 123.4567.8901.2345"),
    ("INICIO TRATAM: ", "3/6/2016   CID N-000"),
)


@pytest.mark.requisito("RF-1101", "ND-49")
def test_ficha_da_p1_com_celulas_compostas() -> None:
    r = regras.interpretar_p1(bloco(*FICHA))
    assert r.excecao is None
    assert (r.prontuario, r.nome, r.nome_mae, r.nascimento) == (
        "0314", "JOAO DA SILVA FICTICIO", "MARIA DA SILVA FICTICIA", date(1960, 4, 2),
    )  # fmt: skip
    assert (r.municipio_nome, r.cep, r.ibge) == ("JATAI", "75805640", "521190")
    assert (r.cpf, r.rg, r.rg_orgao, r.cns, r.convenio) == (
        "52998224725",
        "1234567",
        "SSP-GO",
        "123456789012345",
        "SUS",
    )
    assert (r.logradouro, r.numero, r.complemento, r.bairro) == ("RUA DAS FLORES", "120", "QD 12 LT 5", "SETOR CENTRAL")
    assert r.inicio == date(2016, 6, 3)  # dd/mm sem zeros (perfilamento §4.2)


@pytest.mark.requisito("ND-45", "DEC-45")
def test_cid_e_descartado_na_extracao_e_so_contado() -> None:
    r = regras.interpretar_p1(bloco(*FICHA))
    assert r.cid_descartado
    assert "N-000" not in repr(r)  # o diagnóstico não sobrevive em campo nenhum


@pytest.mark.requisito("ND-44", "DD-102", "RF-201")
def test_telefone_tem_o_rotulo_depois_do_numero_e_vira_contato() -> None:
    r = regras.interpretar_p1(bloco(*FICHA))
    assert r.telefones == (
        regras.TelefoneLido("64", "999990001", "celular", None, None),
        regras.TelefoneLido("64", "988880002", "recado", "ANA PAULA", "Cônjuge"),
        regras.TelefoneLido("64", "36310003", "recado", "BETO", "Filho ou filha"),
    )
    assert "telefone.ddd_presumido" in r.avisos  # o 3631 veio sem DDD (ND-47)


@pytest.mark.parametrize(
    ("rotulo", "esperado"),
    [("(neta)", ("Outro parente", None)), ("VIZINHA", ("Vizinho ou amigo", None)), ("(comadre)", (None, "x"))],
)
@pytest.mark.requisito("DD-102")
def test_parentesco_vai_para_a_lista_fechada(rotulo: str, esperado: tuple[str | None, str | None]) -> None:
    avisos: list[str] = []
    [lido] = regras.ler_telefones(f"(64) 99999-0001  FULANA {rotulo}", avisos)
    assert lido.contato == "FULANA"
    assert lido.parentesco == esperado[0]
    assert ("contato.parentesco_desconhecido" in avisos) == (esperado[1] is not None)


@pytest.mark.requisito("ND-44")
def test_parentesco_sem_nome_vira_recado_do_paciente() -> None:
    avisos: list[str] = []
    [lido] = regras.ler_telefones("(64) 99999-0001 (filha)", avisos)
    assert (lido.contato, lido.tipo) == (None, "recado")
    assert avisos == ["contato.sem_nome"]


@pytest.mark.requisito("RF-1101", "ND-49")
def test_grafias_variadas_dos_rotulos() -> None:
    variada = bloco(
        ("PACIENTE", "ANA FICTICIA NºPT 551"), ("NOME MÃE:", "MAE FICTICIA"), ("DATA DE MASC:", "02/04/1960"),
        ("CIDADE:", "CAIAPÔNIA  CEP: 75850.000  COD.IBGE: 520440"), ("DOC.PESSOAIS:", "529.982.247-25 RG: 99"),
        ("CONVÊNIO:", "IPASGO / CNS: 123456789012345"), ("INICIO TRATAM:", date(2018, 3, 22)),
    )  # fmt: skip
    r = regras.interpretar_p1(variada)
    assert (r.prontuario, r.nascimento, r.cpf, r.convenio) == ("551", date(1960, 4, 2), "52998224725", "IPASGO")
    assert (r.municipio_nome, r.cep, r.ibge) == ("CAIAPÔNIA", "75850000", "520440")
    assert "cep.generico" in r.avisos  # termina em 000 (RF-1105)


@pytest.mark.requisito("ND-49", "RNF-103")
@pytest.mark.parametrize(
    ("pares", "codigo"),
    [
        ((("PACIENTE:", "X FICTICIO Nº PT: 1"), ("OBSERVAÇÃO:", "livre")), "p1.rotulo_desconhecido"),
        ((("PACIENTE:", "X FICTICIO Nº PT: 1"), ("PACIENTE:", "Y")), "p1.rotulo_repetido"),
    ],
)
def test_rotulo_desconhecido_ou_repetido_manda_a_ficha_inteira_as_excecoes(
    pares: tuple[tuple[str, object], ...], codigo: str
) -> None:
    assert regras.interpretar_p1(bloco(*pares)).excecao == codigo


@pytest.mark.requisito("ND-36")
def test_rg_igual_ao_cpf_e_a_cin_e_sai() -> None:
    r = regras.interpretar_p1(bloco(("PACIENTE:", "X FICTICIO Nº PT: 1"),
                                    ("DOC.PESSOAIS:", "CPF: 52998224725 RG: 52998224725 SSP-GO")))  # fmt: skip
    assert (r.cpf, r.rg, r.rg_orgao) == ("52998224725", None, None)
    assert "rg.igual_cpf" in r.avisos


@pytest.mark.requisito("ND-55")
@pytest.mark.parametrize(("valor", "esperado"), [("13/03/2024", date(2024, 3, 13)), ("31/02/2020", None),
                                                 ("????", None), (date(2020, 1, 2), date(2020, 1, 2))])  # fmt: skip
def test_datas_so_em_dia_mes_ano(valor: str | date, esperado: date | None) -> None:
    assert regras.ler_data(valor) == esperado


def p4(linha: int, pront: str, ent: object, cpf: str = "", cns: str = "", cep: str = "") -> LinhaP4:
    return LinhaP4(linha, {"PRONT": pront, "ENT": ent, "CPF": cpf, "CARTAOSUS": cns, "CEP": cep})  # type: ignore[dict-item]


@pytest.mark.requisito("RF-1102", "DD-114", "RN-04", "ND-48")
def test_p4_completa_o_que_falta_e_a_p1_prevalece() -> None:
    sem_inicio = bloco(*[par for par in FICHA if not par[0].startswith("INICIO")])
    plano = regras.planejar([sem_inicio], [p4(3, "314", "05/05/2019", cpf="11111111111")], [], HOJE)
    r = plano.itens[0].registro
    assert r.inicio == date(2019, 5, 5)  # 0314 na P1 casa com 314 na P4
    assert r.cpf == "52998224725"  # a P1 prevalece
    assert {"p4.completou_inicio", "p4.cpf_divergente"} <= set(r.avisos)
    assert plano.contagens_p4 == {"linhas": 1, "ligadas": 1, "fora_da_base": 0, "sem_prontuario": 0}


@pytest.mark.requisito("RF-1102", "DD-114")
def test_p4_fora_da_base_e_sem_prontuario_sao_contadas_sem_virar_excecao() -> None:
    plano = regras.planejar([bloco(*FICHA)], [p4(3, "9000", "01/01/2010"), p4(4, "S/N", "01/01/2010")], [], HOJE)
    assert plano.itens[0].registro.excecao is None
    assert "p4.sem_linha" in plano.itens[0].registro.avisos
    assert plano.contagens_p4 == {"linhas": 2, "ligadas": 0, "fora_da_base": 1, "sem_prontuario": 1}


@pytest.mark.requisito("RF-1103", "RN-05")
def test_evento_de_saida_na_p3_manda_a_ficha_as_excecoes() -> None:
    evento = LinhaP3("OBITO", 7, 2024, "joão da  silva fictício", ("1", "JOAO DA SILVA FICTICIO"))
    plano = regras.planejar([bloco(*FICHA)], [], [evento], HOJE)
    assert plano.itens[0].excecao == "evento_saida"
    assert plano.itens[0].p3 == (evento,)
    assert plano.contagens_p3 == {"linhas": 1, "casadas": 1, "sem_correspondencia": 0}


@pytest.mark.requisito("P-03", "P-28", "DEC-57")
def test_sem_minimo_vai_as_excecoes() -> None:
    sem_pt = bloco(*(("PACIENTE:", "JOAO FICTICIO"), *FICHA[1:]))
    assert regras.planejar([sem_pt], [], [], HOJE).itens[0].excecao == "P-03.minimo"


@pytest.mark.requisito("ND-55")
def test_inicio_implausivel_some_e_avisa() -> None:
    errado = bloco(*(*FICHA[:-1], ("INICIO TRATAM:", "02/03/0214")))
    r = regras.planejar([errado], [], [], HOJE).itens[0].registro
    assert (r.inicio, r.excecao) == (None, "P-03.minimo")
    assert "inicio.invalido" in r.avisos


@pytest.mark.requisito("ND-56")
def test_p3_por_blocos_de_ano_com_sentinelas() -> None:
    assert regras.coluna_do_nome_p3("ÓBITO") == 1
    assert regras.coluna_do_nome_p3("ALTA") == 0
    assert regras.classificar_linha_p3(("2019",), 0) == ("ano", 2019)
    assert regras.classificar_linha_p3(("NÃO HOUVE ALTA",), 0)[0] == "sentinela"
    assert regras.classificar_linha_p3(("NOME", "DATA"), 0)[0] == "cabecalho"
    assert regras.classificar_linha_p3(("3", "ANA FICTICIA", "01/02/2019"), 1) == ("registro", "ANA FICTICIA")


@pytest.mark.requisito("RNF-103")
@given(st.lists(st.one_of(st.none(), st.sampled_from(["P-03.minimo", "evento_saida", "cpf.repetido"])), max_size=40))
def test_contagem_fecha_quando_toda_ficha_tem_desfecho(excecoes: list[str | None]) -> None:
    desfechos = [Desfecho(i, codigo is None, codigo) for i, codigo in enumerate(excecoes)]
    plano = regras.Plano((), {"linhas": 0, "ligadas": 0, "fora_da_base": 0, "sem_prontuario": 0},
                         {"linhas": 0, "casadas": 0, "sem_correspondencia": 0}, 0)  # fmt: skip
    conta = regras.contagens(len(excecoes), desfechos, plano)
    assert conta["fecha"]
    assert conta["p1"]["importados"] + conta["p1"]["excecoes"] == len(excecoes)


@pytest.mark.requisito("RNF-103")
@given(st.integers(min_value=1, max_value=40))
def test_contagem_nao_fecha_se_alguma_ficha_some(lidas: int) -> None:
    desfechos = [Desfecho(i, True) for i in range(lidas - 1)]
    plano = regras.Plano((), {"linhas": 0, "ligadas": 0, "fora_da_base": 0, "sem_prontuario": 0},
                         {"linhas": 0, "casadas": 0, "sem_correspondencia": 0}, 0)  # fmt: skip
    assert not regras.contagens(lidas, desfechos, plano)["fecha"]
