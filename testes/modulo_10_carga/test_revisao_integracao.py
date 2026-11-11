"""Revisão da carga pela aplicação (DDS §14.3, §14.5): relatório de exceções, tratamento, conferência amostral e
aceite, pela recepção e pela administração. O TI nunca vê nada disso (RF-1004)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from sar.modulo_10_carga.contrato import CAMPOS_CONFERIDOS, Modo, ResultadoConferencia, Tratamento
from sar.modulo_10_carga.servicos import ServicoCarga
from sar.nucleo.contexto import Perfil
from sar.nucleo.erros import AcessoNegado, ConfirmacaoNecessaria, NaoEncontrado, RegraViolada
from testes.apoio import planilhas
from testes.apoio.cadastro import INICIO, dados_completos, montar, pessoa
from testes.apoio.fabrica import Fabrica
from testes.modulo_10_carga.conftest import contar, servico, ti

pytestmark = pytest.mark.integracao


@pytest.fixture
def efetivada(
    carga: dict[str, int], engine_web: Engine, sinteticas: tuple[planilhas.Sinteticas, Path]
) -> tuple[ServicoCarga, planilhas.Sinteticas, dict[str, int]]:
    gerado, pasta = sinteticas
    carga_ = servico(engine_web)
    carga_.efetivar(ti(carga), pasta)
    return carga_, gerado, carga


def conferir_tudo(carga_: ServicoCarga, usuarios: dict[str, int], divergente: bool = False) -> None:
    recepcao = pessoa(usuarios)
    for sorteado in carga_.amostra(recepcao).pacientes:
        for i, (campo, _) in enumerate(CAMPOS_CONFERIDOS):
            resultado = ResultadoConferencia.DIVERGENTE if divergente and i == 0 else ResultadoConferencia.CONFERIDO
            carga_.registrar_conferencia(recepcao, sorteado.linha_id, campo, resultado)
        divergente = False  # só a primeira ficha diverge


def tratar_todas(carga_: ServicoCarga, usuarios: dict[str, int]) -> None:
    recepcao = pessoa(usuarios)
    relatorio = carga_.relatorio(recepcao)
    assert relatorio is not None
    for linha in relatorio.linhas:
        if linha.excecao:
            carga_.tratar_excecao(recepcao, linha.linha_id, Tratamento.DESCARTADA, "duplicata conferida", None)


# ------------------------------------------------------------------ relatório (RF-1106)
@pytest.mark.requisito("RF-1106", "RF-1004", "DD-65")
def test_relatorio_mostra_a_ficha_original_so_para_recepcao_e_administracao(
    efetivada: tuple[ServicoCarga, planilhas.Sinteticas, dict[str, int]],
) -> None:
    carga_, gerado, usuarios = efetivada
    relatorio = carga_.relatorio(pessoa(usuarios))
    assert relatorio is not None and relatorio.modo is Modo.EFETIVACAO
    por_linha = {linha.numero_linha: linha for linha in relatorio.linhas}
    saida = next(f for f in gerado.fichas if f.defeito == "evento_de_saida")
    linha = por_linha[saida.linha]
    assert linha.excecao == "evento_saida" and linha.tratamento is None
    assert any(saida.nome in (valor or "") for _, valor in linha.original.p1)  # a ficha como estava
    assert linha.original.p3  # e o evento que a mandou às exceções
    assert relatorio.pendentes == gerado.esperados()["excecoes"]
    assert carga_.relatorio(pessoa(usuarios, "admin", Perfil.ADMINISTRACAO)) is not None
    with pytest.raises(AcessoNegado):
        carga_.relatorio(ti(usuarios))


@pytest.mark.requisito("RF-1106", "DD-66")
def test_relatorio_da_simulacao_antes_da_efetivacao(
    carga: dict[str, int], engine_web: Engine, sinteticas: tuple[planilhas.Sinteticas, Path]
) -> None:
    gerado, pasta = sinteticas
    carga_ = servico(engine_web)
    assert carga_.relatorio(pessoa(carga)) is None
    carga_.simular(ti(carga), pasta)
    relatorio = carga_.relatorio(pessoa(carga))
    assert relatorio is not None and relatorio.modo is Modo.SIMULACAO
    assert sum(1 for linha in relatorio.linhas if linha.excecao) == gerado.esperados()["excecoes"]
    with pytest.raises(RegraViolada) as erro:  # na simulação não há o que tratar: corrige-se a planilha
        carga_.tratar_excecao(
            pessoa(carga), relatorio.linhas[0].linha_id, Tratamento.DESCARTADA, "motivo qualquer", None
        )
    assert erro.value.codigo == "carga.sem_efetivacao"


# ------------------------------------------------------------------ tratamento das exceções (§14.3, item 4)
@pytest.mark.requisito("RF-1106", "P-28", "DD-114")
def test_excecao_importada_a_mao_ou_descartada_com_motivo(
    efetivada: tuple[ServicoCarga, planilhas.Sinteticas, dict[str, int]], engine_web: Engine, fabrica: Fabrica
) -> None:
    carga_, _, usuarios = efetivada
    recepcao = pessoa(usuarios)
    relatorio = carga_.relatorio(recepcao)
    assert relatorio is not None
    excecoes = [linha for linha in relatorio.linhas if linha.excecao]
    primeira, segunda = excecoes[0], excecoes[1]
    with pytest.raises(RegraViolada) as erro:
        carga_.tratar_excecao(recepcao, primeira.linha_id, Tratamento.DESCARTADA, "  ", None)
    assert erro.value.codigo == "carga.motivo"
    carga_.tratar_excecao(recepcao, primeira.linha_id, Tratamento.DESCARTADA, "paciente já saiu", None)

    # P-28: a recepção cadastra pela tela e liga o cadastro à linha.
    dados = dados_completos(fabrica)
    montar(engine_web).pacientes.criar(recepcao, dados, INICIO)
    carga_.tratar_excecao(recepcao, segunda.linha_id, Tratamento.IMPORTADA_MANUAL, None, dados.prontuario)
    tratadas = {li.linha_id: li for li in (carga_.relatorio(recepcao) or relatorio).linhas}
    assert tratadas[primeira.linha_id].tratamento is Tratamento.DESCARTADA
    assert tratadas[segunda.linha_id].tratamento is Tratamento.IMPORTADA_MANUAL
    assert tratadas[segunda.linha_id].paciente_id is not None

    with pytest.raises(RegraViolada) as erro:  # o mesmo cadastro não serve a duas linhas
        carga_.tratar_excecao(recepcao, primeira.linha_id, Tratamento.IMPORTADA_MANUAL, None, dados.prontuario)
    assert erro.value.codigo == "carga.paciente_ja_ligado"
    with pytest.raises(RegraViolada) as erro:
        carga_.tratar_excecao(recepcao, primeira.linha_id, Tratamento.IMPORTADA_MANUAL, None, "inexistente")
    assert erro.value.codigo == "carga.paciente_nao_encontrado"
    importada = next(li for li in relatorio.linhas if not li.excecao)  # só avisos: nada a tratar
    with pytest.raises(RegraViolada) as erro:
        carga_.tratar_excecao(recepcao, importada.linha_id, Tratamento.DESCARTADA, "não se aplica", None)
    assert erro.value.codigo == "carga.linha_sem_excecao"
    with pytest.raises(AcessoNegado):
        carga_.tratar_excecao(ti(usuarios), primeira.linha_id, Tratamento.DESCARTADA, "o TI não trata", None)


# ------------------------------------------------------------------ conferência amostral (§14.3, P-29)
@pytest.mark.requisito("P-29", "RF-1106", "ND-50")
def test_conferencia_lado_a_lado_e_andamento_da_amostra(
    efetivada: tuple[ServicoCarga, planilhas.Sinteticas, dict[str, int]],
) -> None:
    carga_, _, usuarios = efetivada
    recepcao = pessoa(usuarios)
    amostra = carga_.amostra(recepcao)
    assert (len(amostra.pacientes), amostra.rodadas, amostra.completa) == (15, 1, False)
    sorteado = amostra.pacientes[0]
    conferencia = carga_.conferencia(recepcao, sorteado.linha_id)
    assert [c.campo for c in conferencia.campos] == [campo for campo, _ in CAMPOS_CONFERIDOS]
    valores = {c.campo: c.valor_cadastro for c in conferencia.campos}
    assert valores["nome"] == sorteado.nome and valores["prontuario"] == sorteado.prontuario
    assert any((sorteado.nome or "-") in (v or "") for _, v in conferencia.original.p1)
    carga_.registrar_conferencia(recepcao, sorteado.linha_id, "nome", ResultadoConferencia.CONFERIDO)
    carga_.registrar_conferencia(recepcao, sorteado.linha_id, "telefones", ResultadoConferencia.DIVERGENTE)
    depois = next(p for p in carga_.amostra(recepcao).pacientes if p.linha_id == sorteado.linha_id)
    assert (depois.conferidos, depois.divergentes, depois.completo) == (1, 1, False)
    with pytest.raises(RegraViolada):
        carga_.registrar_conferencia(recepcao, sorteado.linha_id, "sexo", ResultadoConferencia.CONFERIDO)
    nao_sorteada = carga_.relatorio(recepcao)
    assert nao_sorteada is not None
    fora = next(li for li in nao_sorteada.linhas if li.excecao)
    with pytest.raises(NaoEncontrado):
        carga_.conferencia(recepcao, fora.linha_id)


@pytest.mark.requisito("P-29")
def test_sorteia_mais_15_so_com_a_amostra_conferida_e_divergencia(
    efetivada: tuple[ServicoCarga, planilhas.Sinteticas, dict[str, int]],
) -> None:
    carga_, gerado, usuarios = efetivada
    recepcao = pessoa(usuarios)
    with pytest.raises(RegraViolada) as erro:
        carga_.sortear_mais(recepcao)
    assert erro.value.codigo == "carga.amostra_incompleta"
    conferir_tudo(carga_, usuarios, divergente=True)
    sorteados = carga_.sortear_mais(recepcao)
    assert sorteados == min(15, gerado.esperados()["importados"] - 15)
    amostra = carga_.amostra(recepcao)
    assert (amostra.rodadas, len(amostra.pacientes), amostra.completa) == (2, 15 + sorteados, False)


# ------------------------------------------------------------------ aceite (§14.3, itens 4 e 5; DD-69)
@pytest.mark.requisito("DD-69", "DD-66", "RF-1106", "P-29")
def test_aceite_exige_tudo_tratado_e_conferido_e_apaga_a_area_de_trabalho(
    efetivada: tuple[ServicoCarga, planilhas.Sinteticas, dict[str, int]], engine_web: Engine
) -> None:
    carga_, gerado, usuarios = efetivada
    admin = pessoa(usuarios, "admin", Perfil.ADMINISTRACAO)
    importados = gerado.esperados()["importados"]
    with pytest.raises(AcessoNegado):
        carga_.aceitar(pessoa(usuarios), importados)
    with pytest.raises(RegraViolada) as erro:
        carga_.aceitar(admin, importados)
    assert erro.value.codigo == "carga.excecao_sem_tratamento"
    tratar_todas(carga_, usuarios)
    with pytest.raises(RegraViolada) as erro:
        carga_.aceitar(admin, importados)
    assert erro.value.codigo == "carga.amostra_incompleta"
    conferir_tudo(carga_, usuarios)

    with pytest.raises(ConfirmacaoNecessaria) as confirmar:  # R-16: a recepção contou outro número
        carga_.aceitar(admin, importados - 7)
    assert confirmar.value.dados == {"carregados": importados, "confirmados": importados - 7}
    carga_.aceitar(admin, importados - 7, confirmar_diferenca=True)

    assert contar(engine_web, "SELECT COUNT(*) FROM carga_linha") == 0  # DD-69
    assert contar(engine_web, "SELECT COUNT(*) FROM carga_conferencia") == 0
    assert contar(engine_web, "SELECT ativos_confirmados FROM carga_lote WHERE situacao = 'aceita'") == importados - 7
    assert contar(engine_web, "SELECT COUNT(*) FROM auditoria WHERE operacao = 'carga.aceitar'") == 1
    relatorio = carga_.relatorio(admin)
    assert relatorio is not None and relatorio.aceito_em is not None and relatorio.linhas == ()
    for tentativa in (lambda: carga_.aceitar(admin, importados), lambda: carga_.sortear_mais(admin)):
        with pytest.raises(RegraViolada) as erro:
            tentativa()
        assert erro.value.codigo == "carga.aceita"
    assert carga_.amostra(admin).pacientes == ()
