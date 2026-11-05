"""Telas do Incremento 5 com o banco e o conversor: dados da clínica (RF-1201, RF-1202), modelos (DD-42), emissão a
partir da ficha (RF-801 a RF-808), relatórios (RF-901 a RF-916) e pedidos do titular (RF-1009)."""

from __future__ import annotations

import io
import re
from collections.abc import Iterator
from datetime import date, datetime

import pytest
from flask.testing import FlaskClient
from PIL import Image
from sqlalchemy import Engine, text
from werkzeug.test import TestResponse

from sar.web.formatos import FUSO
from testes.apoio.acesso import CriarUsuario
from testes.apoio.cadastro import dados_completos, pessoa
from testes.apoio.cadastro import montar as montar_cadastro
from testes.apoio.fabrica import Fabrica
from testes.apoio.modelos import conversor_no_ar, inicial, no_texto, texto_do_pdf
from testes.apoio.web import ORIGEM, get, logado, montar, post

pytestmark = pytest.mark.integracao

CLINICA = {"nome": "Clínica Fictícia de Teste", "endereco": "Rua das Flores, 100 - Centro", "cep": "75803-000",
           "uf": "GO", "municipio": "5211909", "telefone": "(64) 3600-0000", "cnpj": ""}  # fmt: skip


@pytest.fixture
def ambiente(
    cadastro_zerado: dict[str, int], criar_usuario: CriarUsuario, engine_web: Engine, engine_migracao: Engine
) -> Iterator[dict[str, int]]:
    conversor_no_ar()  # pula sem o conversor (o CI exige)
    ids = dict(cadastro_zerado)
    ids["visualizador"] = criar_usuario("webe_visual", perfil="visualizador")
    criar_usuario("webe_admin", perfil="administracao")
    criar_usuario("webe_recepcao", perfil="recepcao")
    yield ids
    with engine_migracao.begin() as c:
        for tabela in ("modelo_documento", "instituicao", "emissao_documento", "requisicao_titular"):
            c.execute(text(f"DELETE FROM {tabela}"))  # noqa: S608 — nomes fixos do teste


def enviar_arquivo(cliente: FlaskClient, caminho: str, campo: str, conteudo: bytes, nome: str) -> TestResponse:
    return cliente.post(caminho, data={campo: (io.BytesIO(conteudo), nome)}, base_url=ORIGEM,
                        headers={"Origin": ORIGEM}, content_type="multipart/form-data")  # fmt: skip


def png() -> bytes:
    saida = io.BytesIO()
    Image.new("RGB", (60, 40), "navy").save(saida, format="PNG")
    return saida.getvalue()


def paciente(engine: Engine, ids: dict[str, int], fabrica: Fabrica) -> tuple[int, str]:
    dados = dados_completos(fabrica)
    return montar_cadastro(engine).pacientes.criar(pessoa(ids), dados, date(2026, 10, 1)), dados.nome or ""


# ------------------------------------------------------------------ dados da clínica e modelos
@pytest.mark.requisito("RF-1201", "RF-1202", "DD-50")
def test_administracao_cadastra_os_dados_da_clinica_e_o_logotipo(ambiente: dict[str, int], engine_web: Engine) -> None:
    admin = logado(montar(engine_web), "webe_admin")
    pagina = get(admin, "/clinica").get_data(as_text=True)
    assert 'href="/clinica"' in pagina and "nenhum documento é emitido" in pagina and "Jataí" in pagina
    assert "O CNPJ não confere" in post(admin, "/clinica", {**CLINICA, "cnpj": "11.222.333/0001-80"}).get_data(
        as_text=True)  # fmt: skip
    assert post(admin, "/clinica", CLINICA).headers["Location"].endswith("/clinica?resultado=salvo")
    assert "Logotipo atualizado" not in get(admin, "/clinica").get_data(as_text=True)
    recusa = enviar_arquivo(admin, "/clinica/logotipo", "logotipo", b"GIF89a nada", "logo.gif")
    assert "PNG ou JPEG" in recusa.get_data(as_text=True)
    assert enviar_arquivo(admin, "/clinica/logotipo", "logotipo", png(), "logo.png").status_code == 302
    imagem = get(admin, "/clinica/logotipo.png")
    assert imagem.status_code == 200 and imagem.data.startswith(b"\x89PNG")
    recepcao = logado(montar(engine_web), "webe_recepcao")
    assert get(recepcao, "/clinica").status_code == 403 and 'href="/clinica"' not in get(recepcao, "/").get_data(
        as_text=True)  # fmt: skip


@pytest.mark.requisito("DD-42", "DD-103", "CT-EMI-01")
def test_ciclo_do_modelo_pela_tela(ambiente: dict[str, int], engine_web: Engine) -> None:
    admin = logado(montar(engine_web), "webe_admin")
    pagina = get(admin, "/modelos").get_data(as_text=True)
    assert "Termo de responsabilidade — implante de cateter" in pagina and "(modelo inicial)" in pagina
    assert "{{ nome }}" in pagina  # a lista de variáveis
    baixado = get(admin, "/modelos/DOC-02/0/arquivo")
    assert baixado.data == inicial() and "attachment" in baixado.headers["Content-Disposition"]
    previa = get(admin, "/modelos/DOC-02/0/previa")
    assert previa.mimetype == "application/pdf" and "inline" in previa.headers["Content-Disposition"]
    assert "MARIA APARECIDA EXEMPLO" in texto_do_pdf(previa.data)

    hostil = enviar_arquivo(admin, "/modelos/DOC-02", "arquivo", no_texto("{{ cpf }}"), "cateter.docx")
    assert "A variável {{ cpf }} não existe para este documento" in hostil.get_data(as_text=True)
    aceito = enviar_arquivo(admin, "/modelos/DOC-02", "arquivo", no_texto("{{ nome }} (revisado)"), "cateter.docx")
    assert "resultado=enviado" in aceito.headers["Location"]
    assert post(admin, "/modelos/DOC-02/1/ativar", {}).status_code == 302
    linha = re.search(r'data-versao="1"[^>]*>', get(admin, "/modelos").get_data(as_text=True))
    assert linha is not None and 'data-estado="ativa"' in linha.group(0)
    recepcao = logado(montar(engine_web), "webe_recepcao")
    assert get(recepcao, "/modelos").status_code == 403


# ------------------------------------------------------------------ emissão pela ficha
@pytest.mark.requisito("RF-801", "RF-805", "RF-808", "RNF-206", "DD-43")
def test_documentos_emitidos_da_ficha_em_pdf_para_imprimir(
    ambiente: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    pid, nome = paciente(engine_web, ambiente, fabrica)
    recepcao, admin = logado(montar(engine_web), "webe_recepcao"), logado(montar(engine_web), "webe_admin")
    ficha = get(recepcao, f"/pacientes/{pid}").get_data(as_text=True)
    assert "Documentos para imprimir" in ficha and 'target="_blank"' in ficha and "Registrar pedido do titular" in ficha

    sem_clinica = post(recepcao, f"/pacientes/{pid}/emitir/DOC-02", {})
    assert sem_clinica.status_code == 422 and "dados da clínica ainda não foram cadastrados" in sem_clinica.get_data(
        as_text=True)  # fmt: skip
    post(admin, "/clinica", CLINICA)

    emitido = post(recepcao, f"/pacientes/{pid}/emitir/DOC-02", {})
    assert emitido.mimetype == "application/pdf" and emitido.headers["Content-Disposition"].startswith("inline")
    assert emitido.headers["Cache-Control"] == "no-store" and nome.upper() in texto_do_pdf(emitido.data)
    assert nome in texto_do_pdf(post(recepcao, f"/pacientes/{pid}/emitir/DOC-01", {}).data)

    assert post(recepcao, f"/pacientes/{pid}/emitir/DOC-07", {}).mimetype == "application/pdf"
    aviso = post(recepcao, f"/pacientes/{pid}/emitir/DOC-07", {}).get_data(as_text=True)
    assert "já foi emitido 1 vez(es) neste mês" in aviso and "Emitir mesmo assim" in aviso
    assert post(recepcao, f"/pacientes/{pid}/emitir/DOC-07", {"confirmar": "1"}).mimetype == "application/pdf"

    sem_foto = post(recepcao, f"/pacientes/{pid}/emitir/cracha", {}).get_data(as_text=True)
    assert "O paciente não tem foto" in sem_foto
    assert post(recepcao, f"/pacientes/{pid}/emitir/DOC-99", {}).status_code == 404
    visualizador = logado(montar(engine_web), "webe_visual")
    assert "Documentos para imprimir" not in get(visualizador, f"/pacientes/{pid}").get_data(as_text=True)
    assert post(visualizador, f"/pacientes/{pid}/emitir/DOC-02", {}).status_code == 403


# ------------------------------------------------------------------ relatórios
@pytest.mark.requisito("RF-901", "RF-912", "RF-913", "P-20", "RNF-607")
def test_relatorios_pela_tela_com_filtros_e_exportacao(
    ambiente: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    paciente(engine_web, ambiente, fabrica)
    recepcao, admin = logado(montar(engine_web), "webe_recepcao"), logado(montar(engine_web), "webe_admin")
    lista = get(recepcao, "/relatorios").get_data(as_text=True)
    assert "Frequência mensal" in lista and "Pacientes por sexo" not in lista  # P-20: só os operacionais
    assert get(recepcao, "/relatorios/sexo?gerar=1&data=2026-10-13").status_code == 403

    sexo = get(admin, "/relatorios/sexo?gerar=1&data=2026-10-13").get_data(as_text=True)
    assert "Pacientes por sexo" in sexo and "Data de referência:" in sexo and "Baixar planilha" in sexo
    assert "Informe a data de referência" in get(admin, "/relatorios/sexo?gerar=1").get_data(as_text=True)
    mensal = get(admin, "/relatorios/frequencia_mensal?gerar=1&competencia=2026-10").get_data(as_text=True)
    assert 'data-relatorio="frequencia_mensal"' in mensal  # sem implantação, nenhuma sessão é devida (DD-91)
    assert "Baixar planilha" not in get(recepcao, "/relatorios/previa?gerar=1").get_data(as_text=True)

    planilha = post(admin, "/relatorios/sexo/exportar", {"data": "2026-10-13", "formato": "xlsx"})
    assert planilha.headers["Content-Disposition"] == 'attachment; filename="sexo-' + planilha.headers[
        "Content-Disposition"].split('sexo-')[1] and planilha.data.startswith(b"PK")  # fmt: skip
    assert post(recepcao, "/relatorios/sexo/exportar", {"data": "2026-10-13", "formato": "pdf"}).status_code == 403
    with engine_web.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM auditoria WHERE operacao = 'relatorio.exportar'")).scalar_one() == 1


# ------------------------------------------------------------------ titular
@pytest.mark.requisito("RF-1009", "DD-18")
def test_pedido_do_titular_da_ficha_ate_a_resposta(
    ambiente: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    pid, nome = paciente(engine_web, ambiente, fabrica)
    recepcao, admin = logado(montar(engine_web), "webe_recepcao"), logado(montar(engine_web), "webe_admin")
    post(admin, "/clinica", CLINICA)
    assert "O que o paciente pediu" in get(recepcao, f"/titular/novo/{pid}").get_data(as_text=True)
    hoje = datetime.now(FUSO).date().isoformat()
    registrado = post(recepcao, f"/titular/novo/{pid}", {"tipo": "confirmacao_acesso", "canal": "presencial",
                                                         "recebida": hoje})  # fmt: skip
    assert registrado.status_code == 302
    pedido = int(registrado.headers["Location"].split("/titular/")[1].split("?")[0])
    lista = get(recepcao, "/titular").get_data(as_text=True)
    assert nome in lista and "15 dias" in lista
    detalhe_recepcao = get(recepcao, f"/titular/{pedido}").get_data(as_text=True)
    assert "Gerar a cópia" not in detalhe_recepcao and "Concluir o pedido" not in detalhe_recepcao

    copia = post(admin, f"/titular/{pedido}/copia", {"entrega": "em_maos"})
    assert copia.mimetype == "application/pdf" and "attachment" in copia.headers["Content-Disposition"]
    assert "DECLARAÇÃO DE ATENDIMENTO" in texto_do_pdf(copia.data).upper()
    curto = post(admin, f"/titular/{pedido}/concluir", {"desfecho": "ok"})
    assert curto.status_code == 422 and "pelo menos 10 caracteres" in curto.get_data(as_text=True)
    assert (
        post(admin, f"/titular/{pedido}/concluir", {"desfecho": "Cópia entregue em mãos ao titular."}).status_code
        == 302
    )
    assert "Atendido" in get(admin, f"/titular/{pedido}").get_data(as_text=True)

    eliminacao = post(recepcao, f"/titular/novo/{pid}", {"tipo": "eliminacao", "canal": "carta", "recebida": hoje})
    outro = int(eliminacao.headers["Location"].split("/titular/")[1].split("?")[0])
    assert "art. 16, I" in get(admin, f"/titular/{outro}").get_data(as_text=True)  # o fundamento já vem preenchido
