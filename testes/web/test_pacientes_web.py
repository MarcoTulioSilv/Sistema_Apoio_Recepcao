"""Busca e ficha do paciente pela web, com o banco de testes: RF-107, RF-109, RF-601 a RF-606, RF-1008, CT-ACE-02."""

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


def cliente(
    engine: Engine, criar_usuario: CriarUsuario, perfil: str, provedor: ProvedorCepFalso | None = None
) -> FlaskClient:
    login = f"webpac_{perfil[:5]}"
    criar_usuario(login, perfil=perfil)
    return logado(montar(engine, provedor), login)


def novo_paciente(c: FlaskClient, fabrica: Fabrica, **extra: str) -> tuple[int, dict[str, str]]:
    dados = {
        "nome": fabrica.nome(),
        "prontuario": fabrica.prontuario(),
        "inicio": "2026-01-05",
        "acao": "paciente",
        **extra,
    }
    resposta = post(c, "/cadastro/novo", dados)
    achado = re.search(r"/pacientes/(\d+)", resposta.headers.get("Location", ""))
    assert achado, resposta.get_data(as_text=True)[:500]
    return int(achado.group(1)), dados


def periodo_atual(engine: Engine, paciente_id: int) -> int:
    with engine.connect() as c:
        sql = "SELECT id FROM periodo_tratamento WHERE paciente_id = :p ORDER BY inicio DESC LIMIT 1"
        return int(c.execute(text(sql), {"p": paciente_id}).scalar_one())


@pytest.mark.requisito("RF-107", "DD-81", "CT-ACE-02")
def test_busca_por_post_e_ficha_por_perfil(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    recepcao = cliente(engine_web, criar_usuario, "recepcao")
    pid, dados = novo_paciente(recepcao, fabrica)
    assert 'href="/pacientes"' in get(recepcao, "/").get_data(as_text=True)
    achados = post(recepcao, "/pacientes/buscar", {"termo": dados["nome"]}).get_data(as_text=True)
    assert f'href="/pacientes/{pid}"' in achados and dados["prontuario"] in achados
    assert "Nenhum paciente encontrado" in post(recepcao, "/pacientes/buscar", {"termo": "zzzz"}).get_data(as_text=True)

    enfermagem = cliente(engine_web, criar_usuario, "enfermagem")
    so_lista = post(enfermagem, "/pacientes/buscar", {"termo": dados["nome"]}).get_data(as_text=True)
    assert dados["prontuario"] in so_lista and f'href="/pacientes/{pid}"' not in so_lista  # busca sim, ficha não
    assert get(enfermagem, f"/pacientes/{pid}").status_code == 403

    visualizador = cliente(engine_web, criar_usuario, "visualizador")
    ficha = get(visualizador, f"/pacientes/{pid}").get_data(as_text=True)
    assert dados["nome"] in ficha and "Editar dados" not in ficha and "Encerrar tratamento" not in ficha

    ti = cliente(engine_web, criar_usuario, "ti")
    for caminho in ("/pacientes", f"/pacientes/{pid}", f"/pacientes/{pid}/editar", f"/pacientes/{pid}/anular"):
        assert get(ti, caminho).status_code == 403, caminho
    assert post(ti, "/pacientes/buscar", {"termo": dados["nome"]}).status_code == 403
    assert get(recepcao, "/pacientes/999999").status_code == 404


@pytest.mark.requisito("RF-109", "DD-17", "DD-22")
def test_edicao_dos_dados_com_versao(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    recepcao = cliente(engine_web, criar_usuario, "recepcao")
    cpf = fabrica.cpf()
    pid, dados = novo_paciente(recepcao, fabrica, cpf=cpf)
    formulario = get(recepcao, f"/pacientes/{pid}/editar").get_data(as_text=True)
    assert f'value="{dados["nome"]}"' in formulario and 'name="inicio"' not in formulario  # o início é do período
    assert 'name="versao" value="1"' in formulario
    assert post(recepcao, "/cadastro/conferir/cpf", {"cpf": cpf, "paciente_id": str(pid)}).get_data(as_text=True) == ""
    parcial = f"{cpf[:3]}.{cpf[3:6]}"  # busca enquanto digita: CPF pelo começo, com pontuação
    assert f'data-paciente="{pid}"' in post(recepcao, "/pacientes/lista", {"termo": parcial}).get_data(as_text=True)
    base = {"nome": dados["nome"], "prontuario": dados["prontuario"], "cpf": cpf, "naturalidade_uf": "GO"}
    resposta = post(recepcao, f"/pacientes/{pid}/editar", {**base, "bairro": "Centro", "versao": "1"})
    assert resposta.headers["Location"] == f"/pacientes/{pid}?resultado=atualizado"
    assert "Centro" in get(recepcao, resposta.headers["Location"]).get_data(as_text=True)
    conflito = post(recepcao, f"/pacientes/{pid}/editar", {**base, "bairro": "Vila", "versao": "1"}).get_data(
        as_text=True
    )
    assert "Outra pessoa alterou este cadastro" in conflito and 'name="versao" value="2"' in conflito
    invalido = post(recepcao, f"/pacientes/{pid}/editar", {**base, "cpf": "111.111.111-11", "versao": "2"})
    assert "CPF inválido" in invalido.get_data(as_text=True)


@pytest.mark.requisito("RF-201", "RF-202", "CT-CAD-05")
def test_telefones_e_contatos_pela_ficha(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    recepcao = cliente(engine_web, criar_usuario, "recepcao")
    pid, _ = novo_paciente(recepcao, fabrica)
    nome_contato = fabrica.nome()
    post(recepcao, f"/pacientes/{pid}/telefones", {"ddd": "64", "numero": "99999-0001", "tipo": "celular"})
    post(recepcao, f"/pacientes/{pid}/contatos", {"nome": nome_contato, "parentesco": "Filho ou filha"})
    with engine_web.connect() as c:
        contato = c.execute(text("SELECT id FROM contato")).scalar_one()
    resposta = post(recepcao, f"/pacientes/{pid}/telefones", {"ddd": "64", "numero": "3631-0002", "tipo": "fixo",
                                                             "contato_id": str(contato)})  # fmt: skip
    ficha = get(recepcao, resposta.headers["Location"]).get_data(as_text=True)
    assert "Telefone incluído." in ficha and "(64) 99999-0001" in ficha and "(64) 3631-0002" in ficha
    erro = post(recepcao, f"/pacientes/{pid}/telefones", {"ddd": "64", "numero": "3631-0002", "tipo": "celular"})
    assert "Celular tem 9 dígitos" in erro.get_data(as_text=True)
    with engine_web.connect() as c:
        telefone = c.execute(text("SELECT id FROM telefone WHERE paciente_id = :p"), {"p": pid}).scalar_one()
    post(recepcao, f"/pacientes/{pid}/telefones/{telefone}/remover", {})
    removido = post(recepcao, f"/pacientes/{pid}/contatos/{contato}/remover", {})
    assert "Contato removido" in get(recepcao, removido.headers["Location"]).get_data(as_text=True)
    with engine_web.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM telefone")).scalar_one() == 0


@pytest.mark.requisito("RF-601", "RF-603", "RF-605", "RF-607", "RF-302", "DD-101")
def test_evento_retorno_e_cobertura_pela_ficha(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    recepcao = cliente(engine_web, criar_usuario, "recepcao")
    pid, _ = novo_paciente(recepcao, fabrica)
    futuro = post(recepcao, f"/pacientes/{pid}/evento", {"tipo": "alta", "data": "2099-01-01"}).get_data(as_text=True)
    assert "A data do evento não pode ser futura." in futuro
    resposta = post(recepcao, f"/pacientes/{pid}/evento", {"tipo": "alta", "data": "2026-03-01", "local": ""})
    ficha = get(recepcao, resposta.headers["Location"]).get_data(as_text=True)
    assert "Alta em 01/03/2026" in ficha and "Comprovante pendente" in ficha and "Registrar retorno" in ficha
    resposta = post(recepcao, f"/pacientes/{pid}/periodos", {"inicio": "2026-05-01", "cobertura": "sus"})
    assert resposta.headers["Location"].endswith("resultado=periodo")
    periodo = periodo_atual(engine_web, pid)
    ficha = get(recepcao, f"/pacientes/{pid}").get_data(as_text=True)
    # Com a cobertura no período aberto e o outro encerrado, nenhum dos dois oferece registrar cobertura (DD-101).
    assert "Registrar cobertura" not in ficha and "Registrar nova cobertura" not in ficha
    segunda = post(recepcao, f"/pacientes/{pid}/periodos/{periodo}/coberturas", {"cobertura": "sus"})
    assert "Este período já tem cobertura." in segunda.get_data(as_text=True)
    with engine_web.connect() as c:
        quantas = c.execute(text("SELECT COUNT(*) FROM cobertura WHERE periodo_id = :p"), {"p": periodo})
        assert quantas.scalar_one() == 1


@pytest.mark.requisito("RF-606", "DEC-42", "P-01", "CT-ACE-03")
def test_correcao_de_evento_pedida_e_aprovada_na_hora_pela_administracao(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    recepcao = cliente(engine_web, criar_usuario, "recepcao")
    pid, _ = novo_paciente(recepcao, fabrica)
    post(recepcao, f"/pacientes/{pid}/evento", {"tipo": "alta", "data": "2026-03-01"})
    periodo = periodo_atual(engine_web, pid)
    sem_motivo = post(recepcao, f"/pacientes/{pid}/periodos/{periodo}/evento/corrigir",
                      {"tipo": "alta", "data": "2026-03-02", "motivo": " "})  # fmt: skip
    assert "Explique o motivo do pedido" in sem_motivo.get_data(as_text=True)
    pedido = post(
        recepcao,
        f"/pacientes/{pid}/periodos/{periodo}/evento/corrigir",
        {"tipo": "transferencia", "data": "2026-03-02", "local": "Hospital Fictício", "motivo": "Era transferência"},
    )
    assert "Pedido enviado à administração" in get(recepcao, pedido.headers["Location"]).get_data(as_text=True)
    admin = cliente(engine_web, criar_usuario, "administracao")
    fila = get(admin, "/autorizacoes").get_data(as_text=True)
    assert "Alta em 01/03/2026 → Transferência em 02/03/2026" in fila
    direto = post(admin, f"/pacientes/{pid}/periodos/{periodo}/evento/remover", {"motivo": "Registrado por engano"})
    ficha = get(admin, direto.headers["Location"]).get_data(as_text=True)
    assert "aprovado na hora" in ficha and "Comprovante pendente" not in ficha  # o período voltou a ficar aberto


@pytest.mark.requisito("RF-1008", "DD-89", "CT-CAD-06")
def test_anulacao_pela_ficha(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    recepcao = cliente(engine_web, criar_usuario, "recepcao")
    pid, dados = novo_paciente(recepcao, fabrica)
    tela = get(recepcao, f"/pacientes/{pid}/anular").get_data(as_text=True)
    assert "Só para cadastro criado por engano" in tela and "Pedir a anulação à administração" in tela
    pedido = post(recepcao, f"/pacientes/{pid}/anular", {"motivo": "Cadastrado em duplicidade"})
    assert pedido.headers["Location"].endswith("resultado=pedido")
    admin = cliente(engine_web, criar_usuario, "administracao")
    assert "Anular o cadastro agora" in get(admin, f"/pacientes/{pid}/anular").get_data(as_text=True)
    anulado = post(admin, f"/pacientes/{pid}/anular", {"motivo": "Cadastrado em duplicidade"})
    assert "Cadastro anulado" in get(admin, anulado.headers["Location"]).get_data(as_text=True)
    assert get(admin, f"/pacientes/{pid}").status_code == 404
    assert "Nenhum paciente" in post(admin, "/pacientes/buscar", {"termo": dados["prontuario"]}).get_data(as_text=True)


@pytest.mark.requisito("CT-CAD-04", "CT-CAD-03", "INV-08")
def test_cep_verificado_de_novo_e_duplicidade_descartada_pela_ficha(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    provedor = ProvedorCepFalso()
    recepcao = cliente(engine_web, criar_usuario, "recepcao", provedor)
    triade = {"nascimento": "1950-05-01", "mae": fabrica.nome()}
    pid, dados = novo_paciente(recepcao, fabrica, cep="75800-000", **triade)
    ficha = get(recepcao, f"/pacientes/{pid}").get_data(as_text=True)
    assert "CEP não verificado" in ficha
    fora = post(recepcao, f"/pacientes/{pid}/cep", {}).get_data(as_text=True)
    assert "Consulta de CEP fora do ar" in fora
    provedor.fora_do_ar = False
    provedor.enderecos["75800000"] = EnderecoCep("75800000", None, None, "5211909", "GO", "Jataí")
    verificado = post(recepcao, f"/pacientes/{pid}/cep", {})
    assert "CEP não verificado" not in get(recepcao, verificado.headers["Location"]).get_data(as_text=True)

    outro, _ = novo_paciente(recepcao, fabrica, nome=dados["nome"], acao="confirmar", **triade)
    assert "Possível duplicidade" in get(recepcao, f"/pacientes/{outro}").get_data(as_text=True)
    descarte = post(recepcao, f"/pacientes/{outro}/duplicidade/{pid}", {})
    assert "Possível duplicidade" not in get(recepcao, descarte.headers["Location"]).get_data(as_text=True)


@pytest.mark.requisito("RF-201", "RF-202", "INV-12", "RNF-605", "DD-102")
def test_edicao_de_telefone_e_contato_pela_ficha(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    recepcao = cliente(engine_web, criar_usuario, "recepcao")
    pid, _ = novo_paciente(recepcao, fabrica)
    livre = post(recepcao, f"/pacientes/{pid}/contatos", {"nome": fabrica.nome(), "parentesco": "Padrasto"})
    assert "Escolha o parentesco na lista." in livre.get_data(as_text=True)  # antes, o texto livre entrava
    post(recepcao, f"/pacientes/{pid}/contatos", {"nome": fabrica.nome(), "parentesco": "Filho ou filha"})
    with engine_web.connect() as c:
        contato = c.execute(text("SELECT id FROM contato")).scalar_one()
    post(recepcao, f"/pacientes/{pid}/telefones", {"ddd": "64", "numero": "3631-0002", "tipo": "fixo",
                                                  "contato_id": str(contato)})  # fmt: skip
    with engine_web.connect() as c:
        telefone = c.execute(text("SELECT id FROM telefone")).scalar_one()
    ficha = get(recepcao, f"/pacientes/{pid}").get_data(as_text=True)
    assert f'action="/pacientes/{pid}/telefones/{telefone}/alterar"' in ficha and 'value="3631-0002"' in ficha
    assert "<option selected>Filho ou filha</option>" in ficha and 'name="parentesco" maxlength' not in ficha

    resposta = post(recepcao, f"/pacientes/{pid}/telefones/{telefone}/alterar",
                    {"ddd": "64", "numero": "99999-0003", "tipo": "celular"})  # fmt: skip
    assert "Telefone alterado." in get(recepcao, resposta.headers["Location"]).get_data(as_text=True)
    invalido = post(recepcao, f"/pacientes/{pid}/telefones/{telefone}/alterar",
                    {"ddd": "64", "numero": "3631-0002", "tipo": "celular"})  # fmt: skip
    assert "Celular tem 9 dígitos" in invalido.get_data(as_text=True)

    novo_nome = fabrica.nome()
    alterar = f"/pacientes/{pid}/contatos/{contato}/alterar"
    resposta = post(recepcao, alterar, {"nome": novo_nome, "parentesco": "Outro parente"})
    ficha = get(recepcao, resposta.headers["Location"]).get_data(as_text=True)
    assert "Contato alterado." in ficha and novo_nome in ficha and "· Outro parente" in ficha
    vazio = post(recepcao, f"/pacientes/{pid}/contatos/{contato}/alterar", {"nome": " ", "parentesco": ""})
    assert "Informe o nome do contato." in vazio.get_data(as_text=True)
    with engine_web.connect() as c:
        dono = c.execute(text("SELECT paciente_id, contato_id, numero, tipo FROM telefone")).one()
        assert tuple(dono) == (None, contato, "999990003", "celular")  # continua do contato (INV-12)
        alteracoes = (
            c.execute(
                text(
                    "SELECT alteracoes FROM auditoria WHERE entidade IN ('telefone', 'contato')"
                    " ORDER BY id DESC LIMIT 2"
                )
            )
            .scalars()
            .all()
        )
    assert '"parentesco":["Filho ou filha","Outro parente"]' in alteracoes[0]
    assert '"numero":["36310002","999990003"]' in alteracoes[1]

    visualizador = cliente(engine_web, criar_usuario, "visualizador")
    assert "/alterar" not in get(visualizador, f"/pacientes/{pid}").get_data(as_text=True)
    assert post(visualizador, f"/pacientes/{pid}/contatos/{contato}/alterar", {"nome": "x"}).status_code == 403


@pytest.mark.requisito("RF-107", "DD-10", "DD-81")
def test_lista_paginada_e_filtro(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    recepcao = cliente(engine_web, criar_usuario, "recepcao")
    for i in range(32):
        post(recepcao, "/cadastro/novo", {"nome": f"Lista {i:02d} Fictício", "prontuario": f"P{i:03d}",
                                          "inicio": "2026-01-05", "acao": "paciente"})  # fmt: skip
    pagina = get(recepcao, "/pacientes").get_data(as_text=True)
    assert pagina.count("data-paciente=") == 30 and "data-mais" in pagina and "deslocamento=30" in pagina
    assert "Lista 00 Fictício" in pagina and "Lista 30 Fictício" not in pagina  # em ordem de nome
    resto = post(recepcao, "/pacientes/lista?deslocamento=30", {"termo": ""}).get_data(as_text=True)
    assert resto.count("data-paciente=") == 2 and "Fim da lista: 32 pacientes." in resto and "data-mais" not in resto
    filtrado = post(recepcao, "/pacientes/lista", {"termo": "lista 1"}).get_data(as_text=True)
    assert filtrado.count("data-paciente=") == 10 and "<html" not in filtrado  # só as linhas, para o htmx
    assert post(recepcao, "/pacientes/lista", {"termo": "P00"}).get_data(as_text=True).count("data-paciente=") == 10
    assert "Nenhum paciente" in post(recepcao, "/pacientes/lista", {"termo": "zzz"}).get_data(as_text=True)
    assert (
        post(recepcao, "/pacientes/lista?deslocamento=abc", {"termo": ""})
        .get_data(as_text=True)
        .count("data-paciente=")
        == 30
    )
    ti = cliente(engine_web, criar_usuario, "ti")
    assert post(ti, "/pacientes/lista", {"termo": ""}).status_code == 403


@pytest.mark.requisito("DD-90", "DD-10", "DEC-55")
def test_trilha_registra_a_abertura_e_a_busca_confirmada_nao_cada_tecla(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    """Defeito encontrado em uso: a filtragem enquanto se digita gerava um registro na trilha a cada pausa (oito em
    oito segundos numa busca simples)."""
    recepcao = cliente(engine_web, criar_usuario, "recepcao")
    for i in range(32):
        post(recepcao, "/cadastro/novo", {"nome": f"Trilha {i:02d} Fictício", "prontuario": f"T{i:03d}",
                                          "inicio": "2026-01-05", "acao": "paciente"})  # fmt: skip

    def buscas() -> list[str]:
        with engine_web.connect() as c:
            sql = "SELECT alteracoes FROM auditoria WHERE operacao = 'cadastro.paciente.buscar' ORDER BY id"
            return [str(a) for a in c.execute(text(sql)).scalars()]

    get(recepcao, "/pacientes")  # abrir a tela: um registro
    assert buscas() == ['{"quantidade":[null,30]}']
    for parcial in ("tri", "tril", "trilh", "trilha 0"):  # digitando: nenhum
        post(recepcao, "/pacientes/lista", {"termo": parcial})
    post(recepcao, "/pacientes/lista?deslocamento=30", {"termo": ""})  # rolagem: nenhum
    assert len(buscas()) == 1
    curto = post(recepcao, "/pacientes/lista", {"termo": "tr"})
    assert curto.status_code == 204 and curto.get_data() == b""  # 1 ou 2 caracteres: a lista fica como está
    post(recepcao, "/pacientes/buscar", {"termo": "trilha 0"})  # busca confirmada (Enter ou Buscar): um
    assert buscas() == ['{"quantidade":[null,30]}', '{"quantidade":[null,10]}']
    assert all("trilha" not in b.lower() for b in buscas())  # o termo não vai à trilha
    with engine_web.connect() as c:
        pid = c.execute(text("SELECT id FROM paciente ORDER BY nome LIMIT 1")).scalar_one()
    get(recepcao, f"/pacientes/{pid}")  # o acesso ao dado continua auditado na ficha
    with engine_web.connect() as c:
        sql = "SELECT COUNT(*) FROM auditoria WHERE operacao = 'cadastro.paciente.ver_ficha' AND entidade_id = :p"
        assert c.execute(text(sql), {"p": str(pid)}).scalar_one() == 1
