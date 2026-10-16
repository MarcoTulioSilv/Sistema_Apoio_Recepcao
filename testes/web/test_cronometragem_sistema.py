"""Cadastro completo cronometrado com dados fictícios (transição §5, Incremento 2).

Mede o sistema, não a pessoa: o navegador digita num ritmo fixo, todos os campos da ficha, com o endereço vindo
do CEP. Mostra que a tela e o servidor cabem com folga no RNF-403 (menos de 5 min) e no RNF-404 (localizar em
menos de 15 s). A medição que vale para esses requisitos é com a recepcionista, na homologação (PT §6.5), pelo
roteiro em docs/ROTEIRO_cadastro_cronometrado.md. Rodar com -s para ver os tempos."""

from __future__ import annotations

import time

import pytest
from playwright.sync_api import Page, expect
from sqlalchemy import Engine, text

from sar.nucleo.contexto import Perfil
from sar.nucleo.portas import EnderecoCep
from testes.apoio.acesso import CriarUsuario
from testes.apoio.cadastro import ProvedorCepFalso, montar, pessoa
from testes.apoio.fabrica import Fabrica
from testes.web.conftest import entrar_no_navegador

pytestmark = pytest.mark.sistema

RITMO = 40  # ms por tecla: ~25 caracteres por segundo, de propósito acima do de uma pessoa
LIMITE_CADASTRO = 300.0  # RNF-403
LIMITE_LOCALIZAR = 15.0  # RNF-404


def digitar(page: Page, rotulo: str, texto: str, exato: bool = False) -> None:
    campo = page.get_by_label(rotulo, exact=exato)
    campo.click()
    campo.press_sequentially(texto, delay=RITMO)


@pytest.mark.requisito("RNF-406")
def test_cadastro_completo_e_localizacao_cronometrados(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], endereco: str, page: Page, engine_web: Engine,
    fabrica: Fabrica, provedor_cep: ProvedorCepFalso, record_property: pytest.RecordProperty,
) -> None:  # fmt: skip
    convenio = montar(engine_web).configuracao.incluir_convenio(
        pessoa(cadastro_zerado, "admin", Perfil.ADMINISTRACAO), "Ipasgo"
    )
    provedor_cep.fora_do_ar = False
    provedor_cep.enderecos["75800000"] = EnderecoCep("75800000", "Rua Fictícia", "Centro", "5211909", "GO", "Jataí")
    p = fabrica.paciente()
    criar_usuario("cron_rec")
    entrar_no_navegador(page, endereco, "cron_rec")

    inicio = time.monotonic()
    page.get_by_role("link", name="Novo cadastro").click()
    digitar(page, "Nome completo", p.nome)
    digitar(page, "Prontuário", p.prontuario)
    page.get_by_label("Início do tratamento").fill("2026-10-01")
    page.get_by_label("Data de nascimento").fill(p.data_nascimento.isoformat())
    page.get_by_label("Sexo").select_option("F")
    digitar(page, "Nome da mãe", p.nome_mae)
    digitar(page, "CPF", f"{p.cpf[:3]}.{p.cpf[3:6]}.{p.cpf[6:9]}-{p.cpf[9:]}")
    digitar(page, "Cartão do SUS (CNS)", p.cns)
    digitar(page, "RG", "1234567", exato=True)
    digitar(page, "Órgão emissor do RG", "SSP/GO")
    page.get_by_label("Naturalidade: município").select_option(label="Rio Verde")
    digitar(page, "CEP", "75800-000", exato=True)
    page.get_by_label("CEP", exact=True).press("Tab")
    expect(page.get_by_label("Logradouro")).to_have_value("Rua Fictícia")  # preenchido pelo CEP
    page.locator('input[name="numero"]').press_sequentially("120", delay=RITMO)
    digitar(page, "Complemento", "Casa 2")
    page.get_by_label("Cobertura").select_option("convenio")
    page.get_by_label("Convênio", exact=True).select_option(str(convenio))
    digitar(page, "Carteirinha do convênio", "0012345678")
    page.locator('input[name="tel-0-ddd"]').press_sequentially("64", delay=RITMO)
    page.locator('input[name="tel-0-numero"]').press_sequentially("999990001", delay=RITMO)
    page.get_by_role("button", name="Adicionar telefone", exact=True).click()
    page.locator('input[name="tel-1-ddd"]').press_sequentially("64", delay=RITMO)
    page.locator('input[name="tel-1-numero"]').press_sequentially("36310002", delay=RITMO)
    page.locator('select[name="tel-1-tipo"]').select_option("recado")
    page.locator('input[name="contato-0-nome"]').press_sequentially(fabrica.nome(), delay=RITMO)
    page.locator('select[name="contato-0-parentesco"]').select_option("Filho ou filha")
    page.locator('input[name="contato-0-tel-0-ddd"]').press_sequentially("64", delay=RITMO)
    page.locator('input[name="contato-0-tel-0-numero"]').press_sequentially("988880003", delay=RITMO)
    page.get_by_role("button", name="Salvar paciente").click()
    expect(page.get_by_role("status")).to_contain_text("Paciente cadastrado.")
    cadastro = time.monotonic() - inicio

    inicio = time.monotonic()
    page.get_by_role("link", name="Pacientes").click()
    page.get_by_label("Nome, prontuário, CPF ou CNS").press_sequentially(p.nome.split()[0], delay=RITMO)
    page.get_by_role("link", name=f"Abrir ficha de {p.nome}").click()
    expect(page.get_by_role("heading", name=p.nome, level=1)).to_be_visible()
    localizar = time.monotonic() - inicio

    print(f"\nCadastro completo: {cadastro:.1f} s (limite {LIMITE_CADASTRO:.0f} s, RNF-403)")
    print(f"Localizar e abrir a ficha: {localizar:.1f} s (limite {LIMITE_LOCALIZAR:.0f} s, RNF-404)")
    record_property("cadastro_segundos", round(cadastro, 1))
    record_property("localizar_segundos", round(localizar, 1))
    with engine_web.connect() as c:
        linha = c.execute(text("SELECT cep_verificado, cpf, cns FROM paciente")).one()
        assert (linha.cep_verificado, linha.cpf, linha.cns) == (1, p.cpf, p.cns)
        assert c.execute(text("SELECT COUNT(*) FROM telefone")).scalar_one() == 3
        assert c.execute(text("SELECT COUNT(*) FROM contato")).scalar_one() == 1
        assert c.execute(text("SELECT tipo FROM cobertura")).scalar_one() == "convenio"
    assert cadastro < LIMITE_CADASTRO and localizar < LIMITE_LOCALIZAR
