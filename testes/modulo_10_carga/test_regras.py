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


@pytest.mark.requisito("ND-44", "DD-102")
def test_parentesco_sem_nome_vira_contato_com_o_parentesco() -> None:
    """Visto no uso (18/11/2026): "(64) 9... ESPOSA" é o número da esposa, sem o nome. Antes virava recado do
    paciente e o parentesco se perdia; agora é contato chamado pelo que está escrito, com aviso para pedir o nome."""
    avisos: list[str] = []
    [entre_parenteses, solto] = regras.ler_telefones("(64) 99999-0001 (filha)  (64) 99999-0002 ESPOSA", avisos)
    assert (entre_parenteses.contato, entre_parenteses.parentesco) == ("FILHA", "Filho ou filha")
    assert (solto.contato, solto.parentesco, solto.tipo) == ("ESPOSA", "Cônjuge", "recado")
    assert avisos == ["contato.sem_nome", "contato.sem_nome"]


@pytest.mark.requisito("ND-44")
def test_rotulo_antes_do_numero_quando_a_celula_comeca_com_texto() -> None:
    """Formato visto no uso (valores inventados): "PACIENTE 64 9... NOME IRMAO 64 9 ..."."""
    sobras: list[tuple[str, str]] = []
    lidos = regras.ler_telefones("  PACIENTE 64 999990001      JOAO IRMAO 64 9 99990002", [], sobras)
    assert lidos == [
        regras.TelefoneLido("64", "999990001", "celular", None, None),
        regras.TelefoneLido("64", "999990002", "recado", "JOAO", "Irmão ou irmã"),
    ]
    assert sobras == []  # o texto do começo é rótulo, não sobra


@pytest.mark.requisito("RF-1101")
def test_casa_entra_no_complemento_do_endereco() -> None:
    """Visto no uso: "CASA 2" ficava de fora do endereço."""
    endereco = "RUA DAS FLORES QD 12 LT 5 CASA 2 Nº 120 SETOR CENTRAL"
    r = regras.interpretar_p1(bloco(("PACIENTE:", "ANA FICTICIA Nº PT: 1"), ("ENDEREÇO:", endereco)))
    assert (r.logradouro, r.numero, r.complemento, r.bairro) == ("RUA DAS FLORES", "120", "QD 12 LT 5 CASA 2",
                                                                 "SETOR CENTRAL")  # fmt: skip
    assert not r.sobras


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
def test_rotulo_repetido_sem_campo_que_falte_manda_a_ficha_as_excecoes() -> None:
    """Na posição da mãe, o PACIENTE copiado é a mãe; numa ficha completa, não há campo para ele (ND-49)."""
    copiado = regras.interpretar_p1(bloco(("PACIENTE:", "X FICTICIO Nº PT: 1"), ("PACIENTE:", "Y FICTICIA")))
    assert copiado.excecao is None and copiado.nome_mae == "Y FICTICIA"
    assert regras.interpretar_p1(bloco(*FICHA, ("PACIENTE:", "Y FICTICIA"))).excecao == "p1.rotulo_repetido"


@pytest.mark.requisito("ND-49", "RF-1106")
def test_linha_estranha_nao_derruba_a_ficha_e_fica_a_vista() -> None:
    """Visto no uso (18/11/2026): a ficha lida por inteiro ia às exceções por uma linha solta (um endereço)."""
    r = regras.interpretar_p1(bloco(*FICHA[:4], ("RUA SOLTA QD 1 LT 1", "RUA SOLTA QD 1 LT 1"), *FICHA[4:]))
    assert r.excecao is None and r.prontuario == "0314"
    assert "p1.linha_nao_reconhecida" in r.avisos and dict(r.sobras)["linha"].startswith("RUA SOLTA")


@pytest.mark.requisito("RF-1101", "RNF-103")
def test_rotulo_que_so_contem_paciente_nao_corta_a_ficha() -> None:
    """Visto no uso (18/11/2026): "...PACIENTE" no meio da ficha começava outra, e o início caía no pedaço de baixo."""
    assert regras.comeca_ficha("PACIENTE:") and regras.comeca_ficha("PACIENTE :")
    assert not regras.comeca_ficha("CONTATO DO PACIENTE:")
    assert regras.campo_do_rotulo("CONTATO DO PACIENTE:") is None


@pytest.mark.requisito("ND-55")
def test_data_como_numero_serial_do_excel() -> None:
    assert regras.ler_data("43914") == date(2020, 3, 24)
    assert regras.ler_data("2015") is None  # um ano solto não é serial


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


# ------------------------------------------------------------------ achados do uso com a P1 real (18/11/2026)
@pytest.mark.requisito("ND-44", "DD-102")
def test_parentesco_antes_do_nome_e_o_telefone_do_proprio_paciente() -> None:
    """Formato visto na P1 real (valores inventados): o do paciente leva o primeiro nome dele, e os contatos vêm como
    "PARENTESCO NOME", sem parênteses."""
    ficha = bloco(
        ("PACIENTE:", "JOSE DA SILVA FICTICIO Nº PT: 0100"),
        ("TELEFONE:", "(64) 999990001 JOSE (64) 99999.0002 ESPOSA MARIA (64) 99999.0003 FILHA ANA"),
    )
    assert regras.interpretar_p1(ficha).telefones == (
        regras.TelefoneLido("64", "999990001", "celular", None, None),
        regras.TelefoneLido("64", "999990002", "recado", "MARIA", "Cônjuge"),
        regras.TelefoneLido("64", "999990003", "recado", "ANA", "Filho ou filha"),
    )


@pytest.mark.requisito("RNF-103", "DD-114")
def test_titulo_entre_as_fichas_e_contado_a_parte() -> None:
    """Visto no uso: o título no topo da P1 virava um paciente com exceção."""
    titulo = bloco(("ENDEREÇOS E TELEFONES DOS PACIENTES", None))
    plano = regras.planejar([titulo, bloco(*FICHA, linha=3)], [], [], HOJE)
    assert plano.itens[0].excecao == regras.SEM_FICHA
    desfechos = [Desfecho(1, False, regras.SEM_FICHA), Desfecho(3, True)]
    conta = regras.contagens(2, desfechos, plano)
    assert conta["p1"] == {"linhas": 2, "importados": 1, "excecoes": 0, "sem_ficha": 1}
    assert conta["fecha"] and regras.SEM_FICHA not in conta["excecoes"]


@pytest.mark.requisito("RF-1106", "DD-114")
def test_trechos_que_a_leitura_nao_encaixou_ficam_como_sobra() -> None:
    ficha = bloco(
        ("PACIENTE:", "JOSE FICTICIO Nº PT: 0100"),
        ("DOC.PESSOAIS:", "CPF: 529.982.247-25 RG: 1234 SSP-GO TITULO 999"),
        ("TELEFONE:", "CASA DA FILHA (64) 999990001 PACIENTE"),
    )
    r = regras.interpretar_p1(ficha)
    assert dict(r.sobras) == {"documentos": "SSP-GO TITULO 999", "telefone": "CASA DA FILHA"}
    assert {"p1.sobra_documentos", "p1.sobra_telefone"} <= set(r.avisos)
    assert not regras.interpretar_p1(bloco(*FICHA)).sobras  # a ficha bem formada não deixa sobra


# -------------------------------------------------------------- formatos do perfil mascarado da P1 real (18/11/2026)
@pytest.mark.requisito("RF-1101", "ND-49", "DD-114")
@pytest.mark.parametrize(
    ("rotulo", "campo"),
    [("DATA DE NASCIMENTO:", "nascimento"), ("NASCIMENTO:", "nascimento"), ("NOME DA MAE:", "mae"),
     ("NOMR DA MÃE:", "mae"), ("NOME DA", "mae"), ("DOC.PESSOAL:", "documentos"), ("CIDAE/CEP:", "cidade"),
     ("CIDADE/UF:", "cidade"), ("FONE:", "telefone"), ("END:", "endereco"), ("INICIO TRATAMENTO:", "inicio"),
     ("DATA:", None), ("RUA DAS FLORES QD 12 LT 5 SETOR CENTRAL", None)],
)  # fmt: skip
def test_rotulo_com_outra_grafia_pelo_trecho(rotulo: str, campo: str | None) -> None:
    assert regras.campo_do_rotulo(rotulo) == campo


@pytest.mark.requisito("RF-1101")
def test_linha_sem_rotulo_continua_a_de_cima() -> None:
    r = regras.interpretar_p1(bloco(("PACIENTE:", "ANA FICTICIA Nº PT: 1"), ("NOME DA MÃE:", "MARIA DA SILVA"),
                                    ("", "E SOUZA FICTICIA")))  # fmt: skip
    assert r.excecao is None and r.nome_mae == "MARIA DA SILVA E SOUZA FICTICIA"
    assert "p1.linha_continuada" in r.avisos


@pytest.mark.requisito("RF-1101", "ND-48")
@pytest.mark.parametrize("celula", ["ANA FICTICIA PT 551", "ANA FICTICIA PT: 0551", "ANA FICTICIA NºPT:0551",
                                    "ANA FICTICIA N°PT 0551"])  # fmt: skip
def test_prontuario_com_ou_sem_o_n(celula: str) -> None:
    r = regras.interpretar_p1(bloco(("PACIENTE:", celula)))
    assert (r.nome, r.prontuario.lstrip("0") if r.prontuario else None) == ("ANA FICTICIA", "551")


@pytest.mark.requisito("RF-1101")
@pytest.mark.parametrize("celula", ["SUS 123.4567.8901.2345", "SUS: 123.456.789.012.345", "SUS CNS;123.4567.8901.2345"])
def test_cns_sem_rotulo_ou_com_ponto_e_virgula(celula: str) -> None:
    r = regras.interpretar_p1(bloco(("PACIENTE:", "ANA FICTICIA PT 1"), ("CONVÊNIO:", celula)))
    assert (r.cns, r.convenio) == ("123456789012345", "SUS")


@pytest.mark.requisito("ND-44", "DD-102")
def test_parenteses_com_nome_e_parentesco_e_ddd_com_zero() -> None:
    avisos: list[str] = []
    lidos = regras.ler_telefones("(64) 99999.0001(MARIA ESPOSA) 064 99990002 JOSE FILHO", avisos)
    assert lidos == [
        regras.TelefoneLido("64", "999990001", "recado", "MARIA", "Cônjuge"),
        regras.TelefoneLido("64", "999990002", "recado", "JOSE", "Filho ou filha"),
    ]
    assert "telefone.nono_digito" in avisos  # o 064 9999-0002 era celular de 8 dígitos


@pytest.mark.requisito("RF-1101")
def test_bairro_sem_palavra_chave_e_o_fim_do_endereco() -> None:
    r = regras.interpretar_p1(bloco(("PACIENTE:", "ANA FICTICIA PT 1"), ("ENDEREÇO:", "RUA 10 QD 5 LT 3 S/N CENTRO")))
    assert (r.logradouro, r.complemento, r.numero, r.bairro) == ("RUA 10", "QD 5 LT 3", "S/N", "CENTRO")
    assert "endereco.bairro_presumido" in r.avisos and not r.sobras


@pytest.mark.requisito("ND-55", "ND-56")
def test_data_com_barra_dobrada_e_ano_com_a_palavra_ano() -> None:
    assert regras.ler_data("12//03/2020") == date(2020, 3, 12)
    assert regras.classificar_linha_p3(("ANO 2015",), 0) == ("ano", 2015)


# -------------------------------------------------------------- segunda rodada do perfil mascarado (18/11/2026)
@pytest.mark.requisito("RF-1101")
def test_convenio_com_telefone_dentro_e_cns_na_linha_do_inicio() -> None:
    r = regras.interpretar_p1(bloco(
        ("PACIENTE:", "ANA FICTICIA PT 1"),
        ("CONVÊNIO:", "SUS : CNS: 123.4567.8901.2345 (64)99999 0001 PACIENTE"),
        ("INICIO TRATAM:", "02/03/2020 SUS 987.6543.2109.8765"),
    ))  # fmt: skip
    assert (r.convenio, r.cns, r.inicio) == ("SUS", "123456789012345", date(2020, 3, 2))
    assert r.telefones == (regras.TelefoneLido("64", "999990001", "celular", None, None),)
    assert "p1.telefone_fora_do_lugar" in r.avisos and "p1.cns_fora_do_lugar" not in r.avisos  # o da ficha vale


@pytest.mark.requisito("RF-1101")
def test_cns_so_na_linha_do_inicio_e_aproveitado() -> None:
    r = regras.interpretar_p1(bloco(("PACIENTE:", "ANA FICTICIA PT 1"),
                                    ("INICIO TRATAM:", "SUS CID N-000 CNS: 123.456.789.012.345")))  # fmt: skip
    assert r.cns == "123456789012345" and "p1.cns_fora_do_lugar" in r.avisos and r.cid_descartado


@pytest.mark.requisito("RF-1101", "RNF-103")
def test_data_numa_linha_de_texto_fica_de_fora_sem_derrubar_a_ficha() -> None:
    r = regras.interpretar_p1(bloco(*FICHA[:-2], ("CONVÊNIO:", date(2020, 3, 2)), FICHA[-1]))
    assert r.excecao is None and r.convenio is None and "p1.celula_fora_do_lugar" in r.avisos


@pytest.mark.requisito("RF-1101")
def test_rotulo_data_de_e_mae_com_prontuario() -> None:
    assert regras.campo_do_rotulo("DATA DE NASCIENTO:") == "nascimento"
    assert regras.campo_do_rotulo("DATA DE INICIO:") == "inicio"
    r = regras.interpretar_p1(bloco(("PACIENTE:", "ANA FICTICIA PT 1"), ("NOME DA MÃE:", "BIA FICTICIA PT 2")))
    assert "p1.mae_com_prontuario" in r.avisos


@pytest.mark.requisito("ND-56")
@pytest.mark.parametrize("celula", ["ALTAS 2015", "JANEIRO 2016", "ANO: 2017"])
def test_celula_sozinha_terminada_em_ano_e_cabecalho_da_p3(celula: str) -> None:
    assert regras.classificar_linha_p3((celula,), 0)[0] == "ano"


@pytest.mark.requisito("RF-1101", "ND-49")
def test_cidade_com_o_rotulo_paciente_copiado_e_lida_pela_posicao() -> None:
    """Visto no uso (18/11/2026): a ficha é copiada à mão e a linha da cidade ficou com "PACIENTE:"."""
    r = regras.interpretar_p1(bloco(*FICHA[:4], ("PACIENTE:", FICHA[4][1]), *FICHA[5:]))
    assert r.excecao is None and r.nome == "JOAO DA SILVA FICTICIO" and r.cep == "75805640"
    assert "p1.rotulo_trocado" in r.avisos


@pytest.mark.requisito("ND-49")
def test_paciente_repetido_fora_da_linha_da_cidade_continua_excecao() -> None:
    r = regras.interpretar_p1(bloco(*FICHA[:2], ("PACIENTE:", "OUTRO NOME"), *FICHA[2:]))
    assert r.excecao == "p1.rotulo_repetido"


@pytest.mark.requisito("RF-1101", "RF-1102")
@pytest.mark.parametrize(
    ("linha", "nome", "prontuario"),
    [
        ("ANA FICTICIA N° 0621", "ANA FICTICIA", "0621"),
        ("ANA FICTICIA Nº 0621", "ANA FICTICIA", "0621"),
        ("ANA FICTICIA 782", "ANA FICTICIA", "782"),
        ("ANA FICTICIA - 782", "ANA FICTICIA", "782"),
        ("ANA FICTICIA   Nº PT: 0314", "ANA FICTICIA", "0314"),
        ("ANA FICTICIA PT 15", "ANA FICTICIA", "15"),
        ("ANA FICTICIA", "ANA FICTICIA", None),
    ],
)
def test_prontuario_e_o_numero_da_linha_do_paciente(linha: str, nome: str, prontuario: str | None) -> None:
    """Visto no uso (18/11/2026): "NOME N° 9999" e "NOME 999" perdiam o prontuário, que liga a ficha à P4."""
    r = regras.interpretar_p1(bloco(("PACIENTE:", linha), *FICHA[1:]))
    assert (r.nome, r.prontuario) == (nome, prontuario)


@pytest.mark.requisito("RF-1101", "ND-49")
def test_dois_numeros_sem_pt_nao_viram_prontuario() -> None:
    r = regras.interpretar_p1(bloco(("PACIENTE:", "ANA FICTICIA 782 / 0621"), *FICHA[1:]))
    assert (r.nome, r.prontuario) == ("ANA FICTICIA", None)
    assert "p1.prontuario_ambiguo" in r.avisos and dict(r.sobras)["paciente"].startswith("782")


@pytest.mark.requisito("RF-1101", "ND-49")
def test_rotulo_repetido_le_o_campo_que_falta_pela_posicao() -> None:
    """Visto no uso (18/11/2026): "CONVENIO:" copiado na linha do início e "ENDERECO:" em todas as linhas de baixo."""
    r = regras.interpretar_p1(bloco(*FICHA[:8], ("CONVENIO:", "3/6/2016")))
    assert r.excecao is None and r.inicio == date(2016, 6, 3) and "p1.rotulo_trocado" in r.avisos
    r = regras.interpretar_p1(bloco(*FICHA[:4], *(("ENDEREÇO:", v) for _, v in FICHA[4:])))
    assert r.excecao is None and r.cep == "75805640" and r.cns == "123456789012345" and r.inicio is not None


@pytest.mark.requisito("ND-49")
def test_rotulo_repetido_sem_data_no_campo_de_data_continua_excecao() -> None:
    """A mãe repetida numa ficha sem início: o único campo que falta é uma data, e o valor não é data."""
    r = regras.interpretar_p1(bloco(*FICHA[:2], ("NOME DA MÃE:", "OUTRA FICTICIA"), *FICHA[2:8]))
    assert r.excecao == "p1.rotulo_repetido"


@pytest.mark.requisito("RF-1106")
def test_rotulo_com_erro_de_digitacao_e_reconhecido() -> None:
    """Visto no uso (18/11/2026): a tela marcava como não reconhecido o que a leitura já tinha lido."""
    for rotulo, campo in (("TELEONE:", "telefone"), ("CONVENIIO:", "convenio"), ("DATA DE NAS:", "nascimento"),
                          ("CIADADE/CEP:", "cidade"), ("INICIO TRT:", "inicio"), ("NOME DA:", "mae")):  # fmt: skip
        assert regras.campo_do_rotulo(rotulo) == campo, rotulo
