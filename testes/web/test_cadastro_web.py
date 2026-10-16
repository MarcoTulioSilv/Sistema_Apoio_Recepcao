"""Tela de novo cadastro, com o banco de testes: RF-101, RF-102, RF-919, CT-CAD-01 a 05 pela interface."""

from __future__ import annotations

import re

import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, text

from sar.nucleo.portas import EnderecoCep
from testes.apoio.acesso import CriarUsuario
from testes.apoio.cadastro import ProvedorCepFalso
from testes.apoio.fabrica import Fabrica
from testes.apoio.web import get, logado, montar, post

pytestmark = pytest.mark.integracao

JATAI = "5211909"


def recepcao(engine: Engine, criar_usuario: CriarUsuario, provedor: ProvedorCepFalso | None = None) -> FlaskClient:
    criar_usuario("webcad_rec")
    return logado(montar(engine, provedor), "webcad_rec")


def contar(engine: Engine, tabela: str) -> int:
    with engine.connect() as c:
        return int(c.execute(text(f"SELECT COUNT(*) FROM {tabela}")).scalar_one())  # noqa: S608


def minimo(fabrica: Fabrica, **extra: str) -> dict[str, str]:
    return {"nome": fabrica.nome(), "prontuario": fabrica.prontuario(), "inicio": "2026-10-01", **extra}


@pytest.mark.requisito("RF-101", "RF-106", "CT-ACE-01")
def test_tela_aparece_para_quem_cadastra_e_nao_para_o_ti(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine
) -> None:
    cliente = recepcao(engine_web, criar_usuario)
    pagina = get(cliente, "/cadastro/novo").get_data(as_text=True)
    assert 'href="/cadastro/novo"' in get(cliente, "/").get_data(as_text=True)
    assert 'list="municipios-go"' in pagina and '<option value="Jataí"></option>' in pagina  # sugestões de Goiás
    assert "htmx-4.0.0.min.js" in pagina and 'content="history:false' in pagina  # nada da ficha no navegador
    criar_usuario("webcad_ti", perfil="ti")
    ti = logado(montar(engine_web), "webcad_ti")
    assert get(ti, "/cadastro/novo").status_code == 403
    assert post(ti, "/cadastro/rascunho", {"nome": "x"}).status_code == 403
    assert 'href="/cadastro/novo"' not in get(ti, "/").get_data(as_text=True)


@pytest.mark.requisito("CT-CAD-01", "RF-102", "RF-201", "RF-202")
def test_salva_o_paciente_com_telefones_e_contato_numa_vez(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cliente = recepcao(engine_web, criar_usuario)
    dados = minimo(
        fabrica, municipio=JATAI, cobertura="sus", **{
            "tel-0-ddd": "64", "tel-0-numero": "99999-0001", "tel-0-tipo": "celular",
            "tel-1-ddd": "", "tel-1-numero": "", "tel-1-tipo": "celular",  # linha vazia: ignorada
            "contato-0-nome": fabrica.nome(), "contato-0-parentesco": "Cônjuge",
            "contato-0-tel-0-ddd": "64", "contato-0-tel-0-numero": "3631-0002", "contato-0-tel-0-tipo": "fixo",
        },
    )  # fmt: skip
    post(cliente, "/cadastro/rascunho", {"nome": dados["nome"]})
    resposta = post(cliente, "/cadastro/novo", {**dados, "acao": "paciente"})
    assert resposta.status_code == 302 and re.fullmatch(
        r"/pacientes/\d+\?resultado=criado", resposta.headers["Location"]
    )
    ficha = get(cliente, resposta.headers["Location"]).get_data(as_text=True)  # vai direto para a ficha
    assert "Paciente cadastrado." in ficha and dados["prontuario"] in ficha
    assert (contar(engine_web, "paciente"), contar(engine_web, "telefone"), contar(engine_web, "contato")) == (1, 2, 1)
    assert contar(engine_web, "cobertura") == 1 and contar(engine_web, "rascunho_cadastro") == 0


@pytest.mark.requisito("CT-CAD-01", "RF-102")
def test_sem_o_minimo_aponta_o_que_falta_e_guarda_o_digitado(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cliente = recepcao(engine_web, criar_usuario)
    nome = fabrica.nome()
    corpo = post(cliente, "/cadastro/novo", {"nome": nome, "inicio": "2026-10-01", "acao": "paciente"}).get_data(
        as_text=True
    )
    assert "Para salvar o paciente falta: prontuário. Sem isso, salve como rascunho." in corpo
    assert re.search(r'id="prontuario"[^>]*aria-invalid="true"', corpo) and f'value="{nome}"' in corpo
    assert contar(engine_web, "paciente") == 0


@pytest.mark.requisito("CT-CAD-02", "DD-22", "DEC-59")
def test_cpf_invalido_ou_repetido_marca_o_campo(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cliente = recepcao(engine_web, criar_usuario)
    invalido = post(cliente, "/cadastro/novo", {**minimo(fabrica, cpf="111.111.111-11"), "acao": "paciente"})
    assert "CPF inválido: confira os dígitos" in invalido.get_data(as_text=True)
    cpf = fabrica.cpf()
    primeiro = minimo(fabrica, cpf=cpf)
    post(cliente, "/cadastro/novo", {**primeiro, "acao": "paciente"})
    repetido = post(cliente, "/cadastro/novo", {**minimo(fabrica, cpf=cpf), "acao": "paciente"}).get_data(as_text=True)
    assert f"Este CPF já está em uso por {primeiro['nome']}, prontuário {primeiro['prontuario']}." in repetido
    assert (
        post(cliente, "/cadastro/conferir/cpf", {"cpf": "111.111.111-11"})
        .get_data(as_text=True)
        .startswith("CPF inválido")
    )
    assert "já está em uso por" in post(cliente, "/cadastro/conferir/cpf", {"cpf": cpf}).get_data(as_text=True)
    assert post(cliente, "/cadastro/conferir/cpf", {"cpf": fabrica.cpf()}).get_data(as_text=True) == ""
    assert post(cliente, "/cadastro/conferir/cns", {"cns": "123"}).get_data(as_text=True).startswith("CNS inválido")
    assert post(cliente, "/cadastro/conferir/rg", {"rg": "1"}).status_code == 404


@pytest.mark.requisito("CT-CAD-03", "INV-08", "RF-108")
def test_triade_mostra_os_candidatos_e_salva_com_confirmacao(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cliente = recepcao(engine_web, criar_usuario)
    triade = {"nome": fabrica.nome(), "nascimento": "1950-05-01", "mae": fabrica.nome()}
    primeiro = {**triade, "prontuario": "F1", "inicio": "2026-10-01"}
    post(cliente, "/cadastro/novo", {**primeiro, "acao": "paciente"})
    segundo = {**triade, "prontuario": "F2", "inicio": "2026-10-01"}
    corpo = post(cliente, "/cadastro/novo", {**segundo, "acao": "paciente"}).get_data(as_text=True)
    assert "Já existe paciente com o mesmo nome, nascimento e nome da mãe" in corpo and ">F1<" in corpo
    assert 'value="confirmar"' in corpo and contar(engine_web, "paciente") == 1
    assert post(cliente, "/cadastro/novo", {**segundo, "acao": "confirmar"}).status_code == 302
    assert contar(engine_web, "paciente") == 2


@pytest.mark.requisito("RF-919", "RF-920")
def test_rascunho_automatico_retomado_e_descartado(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cliente = recepcao(engine_web, criar_usuario)
    nome = fabrica.nome()
    estado = post(cliente, "/cadastro/rascunho", {"nome": nome, "tel-0-ddd": "64", "acao": "x"}).get_data(as_text=True)
    assert re.fullmatch(r"Rascunho salvo automaticamente às \d\d:\d\d\.\s*", estado)
    pagina = get(cliente, "/cadastro/novo").get_data(as_text=True)
    assert "Rascunho retomado" in pagina and f'value="{nome}"' in pagina and 'name="tel-0-ddd" value="64"' in pagina
    manual = post(cliente, "/cadastro/novo", {"nome": nome, "acao": "rascunho"}).get_data(as_text=True)
    assert "Rascunho salvo às" in manual
    assert post(cliente, "/cadastro/novo", {"acao": "descartar"}).status_code == 302
    assert "Rascunho retomado" not in get(cliente, "/cadastro/novo").get_data(as_text=True)


@pytest.mark.requisito("CT-CAD-04", "AD-23", "QAS-03")
def test_cep_preenche_o_endereco_ou_avisa_que_esta_fora_do_ar(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine
) -> None:
    provedor = ProvedorCepFalso()
    cliente = recepcao(engine_web, criar_usuario, provedor)
    fora = post(cliente, "/cadastro/cep", {"cep": "75800-000", "numero": "10"}).get_data(as_text=True)
    assert "Consulta de CEP fora do ar" in fora and 'name="numero" type="text" value="10"' in fora
    provedor.fora_do_ar = False
    provedor.enderecos["75800000"] = EnderecoCep("75800000", "Rua Fictícia", "Centro", JATAI, "GO", "Jataí")
    provedor.enderecos["01001000"] = EnderecoCep("01001000", "Praça da Sé", "Sé", "3550308", "SP", "São Paulo")
    preenchido = post(cliente, "/cadastro/cep", {"cep": "75800-000", "numero": "10"}).get_data(as_text=True)
    assert 'value="Rua Fictícia"' in preenchido and 'value="10"' in preenchido
    assert re.search(r'id="municipio"[^>]*value="Jataí"', preenchido)  # o nome, no campo com sugestões
    assert "não é de Goiás" in post(cliente, "/cadastro/cep", {"cep": "01001000"}).get_data(as_text=True)
    assert "não encontrado" in post(cliente, "/cadastro/cep", {"cep": "75899999"}).get_data(as_text=True)
    assert "8 dígitos" in post(cliente, "/cadastro/cep", {"cep": "758"}).get_data(as_text=True)


@pytest.mark.requisito("CT-CAD-05", "RF-202")
def test_erro_de_telefone_aparece_na_linha_dele(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cliente = recepcao(engine_web, criar_usuario)
    dados = minimo(fabrica, **{
        "tel-0-ddd": "64", "tel-0-numero": "999990001", "tel-0-tipo": "celular",
        "tel-3-ddd": "64", "tel-3-numero": "3631-0000", "tel-3-tipo": "celular",
    })  # fmt: skip
    corpo = post(cliente, "/cadastro/novo", {**dados, "acao": "paciente"}).get_data(as_text=True)
    assert re.search(r'name="tel-3-numero" value="3631-0000" aria-invalid="true"', corpo)
    assert "Celular tem 9 dígitos começando por 9" in corpo and contar(engine_web, "paciente") == 0


@pytest.mark.requisito("RF-111")
def test_municipios_da_naturalidade_por_uf(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine
) -> None:
    cliente = recepcao(engine_web, criar_usuario)
    assert '<option value="São Paulo"></option>' in get(cliente, "/cadastro/municipios?naturalidade_uf=SP").get_data(
        as_text=True
    )
    assert get(cliente, "/cadastro/municipios?naturalidade_uf=XX").status_code == 404


@pytest.mark.requisito("RF-301")
def test_sem_javascript_a_cobertura_salva_mostra_so_os_campos_dela(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cliente = recepcao(engine_web, criar_usuario)
    cns = fabrica.cns()
    corpo = post(cliente, "/cadastro/novo", {"cobertura": "sus", "cns": cns, "acao": "rascunho"}).get_data(as_text=True)
    assert re.search(r'data-cobertura="convenio" hidden', corpo) and not re.search(
        r'data-cobertura="sus" hidden', corpo
    )
    assert f'CNS já informado na identificação: <span class="numero">{cns}</span>' in corpo
    corpo = post(cliente, "/cadastro/novo", {"cobertura": "convenio", "acao": "rascunho"}).get_data(as_text=True)
    assert re.search(r'data-cobertura="sus" hidden', corpo) and not re.search(
        r'data-cobertura="convenio" hidden', corpo
    )


@pytest.mark.requisito("AD-23", "RF-103")
def test_aviso_de_cep_geral_para_cep_terminado_em_000(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    """Pedido em uso: 75800-000, o CEP geral de Jataí, não existe na base dos Correios; a consulta fica como é, e a
    tela avisa que CEP terminado em 000 costuma ser o da cidade inteira."""
    cliente = recepcao(engine_web, criar_usuario)  # consulta de CEP fora do ar: o aviso não depende dela
    geral = post(cliente, "/cadastro/cep", {"cep": "75800-000"}).get_data(as_text=True)
    assert "data-cep-geral" in geral and "<strong>CEP geral.</strong>" in geral
    assert "data-cep-geral" not in post(cliente, "/cadastro/cep", {"cep": "75800-123"}).get_data(as_text=True)
    assert "data-cep-geral" not in post(cliente, "/cadastro/cep", {"cep": "758000"}).get_data(as_text=True)
    resposta = post(cliente, "/cadastro/novo", {**minimo(fabrica, cep="75800-000"), "acao": "paciente"})
    ficha = get(cliente, resposta.headers["Location"]).get_data(as_text=True)
    assert ">CEP geral</span>" in ficha
    outra = post(cliente, "/cadastro/novo", {**minimo(fabrica, cep="75803-123"), "acao": "paciente"})
    assert ">CEP geral</span>" not in get(cliente, outra.headers["Location"]).get_data(as_text=True)


@pytest.mark.requisito("RF-111", "RF-101")
def test_municipio_digitado_com_sugestoes_vira_o_codigo(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    """Pedido em uso: o município era escolhido rolando uma lista; agora é digitado, com sugestões, e o servidor
    converte o nome no código IBGE da UF certa."""
    cliente = recepcao(engine_web, criar_usuario)
    invalido = post(cliente, "/cadastro/novo", {**minimo(fabrica, municipio="Cidade Fictícia"), "acao": "paciente"})
    corpo = invalido.get_data(as_text=True)
    assert re.search(r'id="municipio"[^>]*aria-invalid="true"', corpo) and "Escolha o município na lista." in corpo
    fora = post(cliente, "/cadastro/novo", {**minimo(fabrica, naturalidade_uf="GO", naturalidade="Campinas"),
                                           "acao": "paciente"}).get_data(as_text=True)  # fmt: skip
    assert re.search(r'id="naturalidade"[^>]*aria-invalid="true"', fora)  # Campinas não é de Goiás
    dados = minimo(fabrica, municipio="jatai", naturalidade_uf="SP", naturalidade="sao paulo")
    resposta = post(cliente, "/cadastro/novo", {**dados, "acao": "paciente"})
    assert resposta.status_code == 302
    with engine_web.connect() as c:
        linha = c.execute(text("SELECT municipio_id, naturalidade_municipio_id FROM paciente")).one()
    assert tuple(linha) == (JATAI, "3550308")
    pid = resposta.headers["Location"].split("/")[2].split("?")[0]
    edicao = get(cliente, f"/pacientes/{pid}/editar").get_data(as_text=True)
    assert re.search(r'id="municipio"[^>]*value="Jataí"', edicao)
    assert re.search(r'id="naturalidade"[^>]*value="São Paulo"', edicao)
    rascunho = post(cliente, "/cadastro/rascunho", {"municipio": JATAI}).get_data(as_text=True)  # código antigo
    assert "Rascunho salvo" in rascunho
    assert re.search(r'id="municipio"[^>]*value="Jataí"', get(cliente, "/cadastro/novo").get_data(as_text=True))


@pytest.mark.requisito("RF-202", "RF-101")
def test_tela_mostra_telefone_e_cep_formatados_e_o_banco_guarda_digitos(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cliente = recepcao(engine_web, criar_usuario)
    telefones = {"tel-0-ddd": "64", "tel-0-numero": "999990001", "tel-0-tipo": "celular",
                 "tel-1-ddd": "64", "tel-1-numero": "3631-0002", "tel-1-tipo": "fixo"}  # fmt: skip
    dados = minimo(fabrica, cep="75800000", **telefones)
    resposta = post(cliente, "/cadastro/novo", {**dados, "acao": "paciente"})
    ficha = get(cliente, resposta.headers["Location"]).get_data(as_text=True)
    assert "(64) 99999-0001" in ficha and "(64) 3631-0002" in ficha and ">75800-000</span>" in ficha
    with engine_web.connect() as c:
        assert c.execute(text("SELECT cep FROM paciente")).scalar_one() == "75800000"
        assert sorted(c.execute(text("SELECT numero FROM telefone")).scalars()) == ["36310002", "999990001"]
    rascunho = post(cliente, "/cadastro/novo", {"cep": "75800000", "tel-0-numero": "999990001", "acao": "rascunho"})
    corpo = rascunho.get_data(as_text=True)
    assert 'value="75800-000"' in corpo and 'value="99999-0001"' in corpo and 'data-mascara="telefone"' in corpo


@pytest.mark.requisito("RNF-406")
def test_menu_com_trocar_senha_no_perfil_e_botao_de_recolher(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine
) -> None:
    cliente = recepcao(engine_web, criar_usuario)
    pagina = get(cliente, "/").get_data(as_text=True)
    assert "Minha senha" not in pagina and ">Trocar senha</a>" in pagina
    assert 'data-recolher-menu aria-controls="menu-principal" aria-expanded="true"' in pagina
    assert 'data-abrir-menu aria-controls="menu-principal"' in pagina  # o de abrir fica no cabeçalho
    assert pagina.index('data-sobre="perfil-menu"') < pagina.index(">Trocar senha</a>")  # no pé do menu, sob o perfil
    assert "Trocar senha" in get(cliente, "/senha").get_data(as_text=True)
