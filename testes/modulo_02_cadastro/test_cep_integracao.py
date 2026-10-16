"""CEP no cadastro, com o banco: CT-CAD-04 (QAS-03), RF-103, RF-109 e a consulta do preenchimento."""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import Engine, text

from sar.modulo_02_cadastro.pendencias import FonteCadastroIncompleto
from sar.modulo_02_cadastro.regras import CEP_NAO_VERIFICADO
from sar.nucleo.contexto import Perfil
from sar.nucleo.erros import AcessoNegado, IndisponivelExterno, RegraViolada
from sar.nucleo.portas import EnderecoCep
from testes.apoio.cadastro import INICIO, dados_completos, montar, pessoa
from testes.apoio.fabrica import Fabrica

pytestmark = pytest.mark.integracao

CEP = "75800000"
JATAI_VIACEP = EnderecoCep(CEP, "Rua Fictícia", "Centro", "5211909", "GO", "Jataí")


@pytest.mark.requisito("CT-CAD-04", "QAS-03", "RF-109")
def test_cep_fora_do_ar_conclui_o_cadastro_com_pendencia_e_verifica_depois(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)  # o provedor começa fora do ar
    recepcao = pessoa(cadastro_zerado)
    pid = cadastro.pacientes.criar(recepcao, replace(dados_completos(fabrica), cep="75800-000"), INICIO)
    ficha = cadastro.pacientes.ver_ficha(recepcao, pid)
    assert (ficha.dados.cep, ficha.cep_verificado) == (CEP, False) and CEP_NAO_VERIFICADO in ficha.pendencias
    [item] = cadastro.executar(lambda uow: FonteCadastroIncompleto().listar(uow, recepcao))
    assert "CEP não verificado" in item.descricao
    with pytest.raises(IndisponivelExterno):
        cadastro.pacientes.verificar_cep(recepcao, pid)  # ainda fora: a pessoa tenta mais tarde

    cadastro.provedor_cep.fora_do_ar = False
    cadastro.provedor_cep.enderecos[CEP] = JATAI_VIACEP
    assert cadastro.pacientes.verificar_cep(recepcao, pid)
    assert CEP_NAO_VERIFICADO not in cadastro.pacientes.ver_ficha(recepcao, pid).pendencias
    with engine_web.connect() as c:
        sql = "SELECT alteracoes FROM auditoria WHERE operacao = 'cadastro.paciente.atualizar'"
        assert c.execute(text(sql)).scalars().all() == ['{"cep_verificado":[false,true]}']


@pytest.mark.requisito("RF-103", "QAS-03")
def test_cep_no_ar_verifica_na_gravacao_e_desconhecido_vira_pendencia(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    cadastro.provedor_cep.fora_do_ar = False
    cadastro.provedor_cep.enderecos[CEP] = JATAI_VIACEP
    recepcao = pessoa(cadastro_zerado)
    conhecido = cadastro.pacientes.criar(recepcao, replace(dados_completos(fabrica), cep=CEP), INICIO)
    desconhecido = cadastro.pacientes.criar(recepcao, replace(dados_completos(fabrica), cep="75899999"), INICIO)
    assert cadastro.pacientes.ver_ficha(recepcao, conhecido).cep_verificado
    assert not cadastro.pacientes.ver_ficha(recepcao, desconhecido).cep_verificado  # não bloqueia (QAS-03)
    with pytest.raises(RegraViolada) as erro:
        cadastro.pacientes.verificar_cep(recepcao, cadastro.pacientes.criar(recepcao, dados_completos(fabrica), INICIO))
    assert erro.value.codigo == "cep.ausente"


@pytest.mark.requisito("AD-23", "RNF-612")
def test_atualizar_sem_mudar_o_cep_nao_consulta_de_novo(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    cadastro.provedor_cep.fora_do_ar = False
    cadastro.provedor_cep.enderecos[CEP] = JATAI_VIACEP
    recepcao = pessoa(cadastro_zerado)
    dados = replace(dados_completos(fabrica), cep=CEP)
    pid = cadastro.pacientes.criar(recepcao, dados, INICIO)
    cadastro.pacientes.atualizar(recepcao, pid, 1, replace(dados, bairro="Centro"))
    assert cadastro.provedor_cep.consultados == [CEP]  # consulta individual, só quando o CEP muda
    assert cadastro.pacientes.ver_ficha(recepcao, pid).cep_verificado


@pytest.mark.requisito("AD-23", "RF-1205")
def test_consulta_do_preenchimento_resolve_o_municipio(cadastro_zerado: dict[str, int], engine_web: Engine) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    with pytest.raises(IndisponivelExterno):
        cadastro.cep.consultar(recepcao, CEP)
    cadastro.provedor_cep.fora_do_ar = False
    cadastro.provedor_cep.enderecos[CEP] = JATAI_VIACEP
    cadastro.provedor_cep.enderecos["75801000"] = EnderecoCep("75801000", None, "Vila Fictícia", None, "GO", "JATAI")
    cadastro.provedor_cep.enderecos["75802000"] = EnderecoCep("75802000", None, None, None, "XX", "Lugar")
    sugerido = cadastro.cep.consultar(recepcao, "75800-000")
    assert sugerido is not None and sugerido.municipio is not None
    assert (sugerido.logradouro, sugerido.municipio.codigo) == ("Rua Fictícia", "5211909")
    pelo_nome = cadastro.cep.consultar(recepcao, "75801000")  # BrasilAPI: sem código, pelo nome e pela UF
    assert pelo_nome is not None and pelo_nome.municipio is not None and pelo_nome.municipio.codigo == "5211909"
    sem_municipio = cadastro.cep.consultar(recepcao, "75802000")
    assert sem_municipio is not None and sem_municipio.municipio is None
    assert cadastro.cep.consultar(recepcao, "75899999") is None
    with pytest.raises(RegraViolada):
        cadastro.cep.consultar(recepcao, "7580")
    with pytest.raises(AcessoNegado):
        cadastro.cep.consultar(pessoa(cadastro_zerado, "ti", Perfil.TI), CEP)
