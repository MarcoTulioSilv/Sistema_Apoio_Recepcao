"""Busca, ficha, edição e anulação no navegador: teclado e axe-core (RNF-406), sem erro de script (DD-09)."""

from __future__ import annotations

from datetime import date

import pytest
from playwright.sync_api import Page, expect
from sqlalchemy import Engine, text

from sar.modulo_02_cadastro.contrato import DadosCobertura, DadosPaciente, TipoCobertura
from testes.apoio.acesso import CriarUsuario
from testes.apoio.cadastro import INICIO, montar, pessoa
from testes.apoio.fabrica import Fabrica
from testes.web.conftest import entrar_no_navegador, sem_violacao

pytestmark = pytest.mark.sistema

SUS = DadosCobertura(TipoCobertura.SUS)


@pytest.mark.requisito("RNF-406", "RF-107", "RF-601", "RF-1008")
def test_da_busca_a_ficha_e_aos_pedidos(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], endereco: str, page: Page, fabrica: Fabrica
) -> None:
    erros: list[str] = []
    page.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: erros.append(str(e)))
    criar_usuario("sistpac_rec")
    entrar_no_navegador(page, endereco, "sistpac_rec")
    nome, prontuario = fabrica.nome(), fabrica.prontuario()
    page.get_by_role("link", name="Novo cadastro").click()
    page.get_by_label("Nome completo").fill(nome)
    page.get_by_label("Prontuário").fill(prontuario)
    page.get_by_label("Início do tratamento").fill("2026-01-05")
    page.get_by_role("button", name="Salvar paciente").click()
    expect(page.get_by_role("heading", name=nome, level=1)).to_be_visible()  # vai direto para a ficha
    expect(page.get_by_role("status")).to_contain_text("Paciente cadastrado.")
    sem_violacao(page)

    page.get_by_role("link", name="Pacientes").click()
    sem_violacao(page)
    page.get_by_label("Nome, prontuário, CPF ou CNS").fill(prontuario)  # filtra enquanto digita, sem Enter
    expect(page.locator("[data-paciente]")).to_have_count(1)
    expect(page.get_by_role("table", name="Pacientes")).to_contain_text(nome)
    sem_violacao(page)
    page.get_by_role("link", name=f"Abrir ficha de {nome}").click()

    page.locator("summary", has_text="Encerrar tratamento").click()  # <details> com cara de botão: abre sem script
    page.get_by_label("Evento").select_option("alta")
    page.get_by_label("Data", exact=True).fill("2026-03-01")
    sem_violacao(page)
    page.get_by_role("button", name="Confirmar evento").click()
    expect(page.get_by_role("status")).to_contain_text("Evento registrado.")
    expect(page.get_by_text("Comprovante pendente")).to_be_visible()
    page.locator("summary", has_text="Incluir contato").click()
    page.get_by_label("Nome do contato").fill(fabrica.nome())
    page.get_by_role("button", name="Incluir contato").click()
    expect(page.get_by_role("status")).to_contain_text("Contato incluído.")
    page.locator("summary", has_text="Editar o contato").click()
    contato = page.locator("[data-contato]")
    contato.get_by_label("Parentesco").select_option("Filho ou filha")
    contato.get_by_role("button", name="Salvar contato").click()
    expect(page.get_by_role("status")).to_contain_text("Contato alterado.")
    expect(page.locator("[data-contato]")).to_contain_text("Filho ou filha")
    sem_violacao(page)

    page.get_by_role("link", name="Editar dados").click()
    expect(page.get_by_label("Nome completo")).to_have_value(nome)
    sem_violacao(page)
    page.get_by_label("Bairro").fill("Centro")
    page.get_by_role("button", name="Salvar alterações").click()
    expect(page.get_by_role("status")).to_contain_text("Dados do paciente atualizados.")

    page.get_by_role("link", name="Pedir anulação deste cadastro").click()
    sem_violacao(page)
    page.get_by_label("Motivo da anulação").fill("Cadastro feito em duplicidade")
    page.get_by_role("button", name="Pedir a anulação à administração").click()
    expect(page.get_by_role("status")).to_contain_text("Pedido enviado à administração")
    assert erros == []


@pytest.mark.requisito("RNF-406", "RF-107")
def test_lista_com_rolagem_continua_e_filtro_enquanto_digita(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], endereco: str, page: Page, engine_web: Engine,
    fabrica: Fabrica,
) -> None:  # fmt: skip
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    for i in range(35):
        cadastro.pacientes.criar(
            recepcao, DadosPaciente(nome=f"Paciente {i:02d} Fictício", prontuario=f"L{i:03d}"), INICIO
        )
    erros: list[str] = []
    page.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
    criar_usuario("sistpac_rec2")
    entrar_no_navegador(page, endereco, "sistpac_rec2")
    page.get_by_role("link", name="Pacientes").click()
    linhas = page.locator("[data-paciente]")
    expect(linhas).to_have_count(30)  # primeira página
    sem_violacao(page)
    page.locator("[data-mais]").scroll_into_view_if_needed()  # a linha final aparece: vem a próxima página
    expect(linhas).to_have_count(35)
    expect(page.locator("[data-fim]")).to_have_text("Fim da lista: 35 pacientes.")
    page.get_by_label("Nome, prontuário, CPF ou CNS").fill("paciente 3")
    expect(linhas).to_have_count(5)  # 30 a 34
    page.get_by_label("Nome, prontuário, CPF ou CNS").fill("L01")  # prontuário pelo começo
    expect(linhas).to_have_count(10)
    page.get_by_label("Nome, prontuário, CPF ou CNS").fill("")
    expect(linhas).to_have_count(30)
    sem_violacao(page)
    assert erros == []


@pytest.mark.requisito("RNF-406", "DD-101")
def test_resumo_da_ficha_com_alturas_iguais_e_tratamento_rolando_por_dentro(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], endereco: str, page: Page, engine_web: Engine,
    engine_migracao: Engine, fabrica: Fabrica,
) -> None:  # fmt: skip
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    pid = cadastro.pacientes.criar(recepcao, DadosPaciente(nome=fabrica.nome(), prontuario=fabrica.prontuario()),
                                   date(2024, 1, 2), cobertura=SUS)  # fmt: skip
    for fim, retorno in (("2024-12-31", date(2025, 2, 3)), ("2025-12-31", date(2026, 2, 2))):
        with engine_migracao.begin() as c:  # o evento chega gravado direto: aqui só importa a ficha cheia
            c.execute(text("UPDATE periodo_tratamento SET evento_tipo = 'alta', evento_data = :d"
                           " WHERE paciente_id = :p AND aberto = 1"), {"d": fim, "p": pid})  # fmt: skip
        cadastro.pacientes.abrir_periodo(recepcao, pid, retorno, SUS)
    criar_usuario("sistpac_rec3")
    page.set_viewport_size({"width": 1900, "height": 1000})
    entrar_no_navegador(page, endereco, "sistpac_rec3")
    page.goto(f"{endereco}/pacientes/{pid}")
    resumo = page.locator("[data-resumo-ficha]")
    alturas = {
        round(resumo.locator(seletor).first.bounding_box()["height"])  # type: ignore[index]
        for seletor in (".moldura-foto", "section[aria-labelledby=dados-t]", "section[aria-labelledby=trat-t]")
    }
    assert len(alturas) == 1  # os três quadros com a mesma altura fixa
    periodos = page.get_by_role("region", name="Períodos de tratamento")
    assert periodos.evaluate("e => e.scrollHeight > e.clientHeight")  # três períodos não cabem: rola por dentro
    expect(periodos.locator("[data-periodo]")).to_have_count(3)
    expect(page.get_by_role("heading", name="Tratamento")).to_be_in_viewport()
    sem_violacao(page)
