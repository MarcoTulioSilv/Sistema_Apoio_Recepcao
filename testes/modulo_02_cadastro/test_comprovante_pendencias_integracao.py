"""Comprovante do evento (§6.5, DEC-53, RF-607), pendências do cadastro (§11.1, DD-54) e marco de retenção
(DD-01), no MySQL."""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from sar.composicao import montar_barramento, montar_executor
from sar.modulo_02_cadastro.contrato import DadosPaciente, TipoEvento, vinculo_do_evento
from sar.modulo_02_cadastro.pendencias import (
    FonteCadastroIncompleto,
    FonteEventoSemComprovante,
    FontePossivelDuplicidade,
    ServicoMarcoRetencao,
)
from sar.modulo_08_dados.relogio import RelogioSistema
from sar.nucleo.contexto import Perfil
from sar.nucleo.documentos import DOCUMENTO_DO_EVENTO
from sar.nucleo.eventos import DocumentoIncorporado, DocumentoRevinculado, EventoDominio
from sar.nucleo.portas import Prioridade
from testes.apoio.cadastro import Cadastro, dados_completos, inserir_documento, montar, pessoa
from testes.apoio.fabrica import Fabrica
from testes.apoio.vazamento import ColetorLogs

pytestmark = pytest.mark.integracao

JANEIRO = date(2026, 1, 5)
MIGRACAO_0002 = Path(__file__).resolve().parents[2] / "sar/modulo_08_dados/migracoes/versions/0002_dados_fixos.py"


def publicar(engine: Engine, evento: EventoDominio) -> None:
    """Como o MOD-04 fará ao incorporar: publica na unidade de trabalho com o barramento da composição."""
    montar_executor(engine, montar_barramento(RelogioSistema()))(lambda uow: uow.publicar(evento))


def com_evento(cadastro: Cadastro, usuarios: dict[str, int], fabrica: Fabrica, tipo: TipoEvento) -> tuple[int, int]:
    recepcao = pessoa(usuarios)
    pid = cadastro.pacientes.criar(recepcao, dados_completos(fabrica), JANEIRO)
    cadastro.eventos.registrar(recepcao, pid, tipo, date(2026, 3, 1), None)
    return pid, cadastro.pacientes.ver_ficha(recepcao, pid).periodos[-1].id


# ------------------------------------------------------------------ tabela da DEC-53
@pytest.mark.requisito("DEC-53", "RN-08")
def test_documento_exigido_por_evento_bate_com_a_migracao() -> None:
    spec = importlib.util.spec_from_file_location("dados_fixos_0002", MIGRACAO_0002)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    exigidos = {evento: codigo for codigo, _, _, _, evento, _, _ in modulo.TIPOS_DOCUMENTO if evento is not None}
    assert exigidos == DOCUMENTO_DO_EVENTO
    assert set(DOCUMENTO_DO_EVENTO) == {t.value for t in TipoEvento}


# ------------------------------------------------------------------ comprovante
@pytest.mark.requisito("RF-607", "INV-11", "DEC-53")
def test_documento_incorporado_pelo_evento_vira_o_comprovante(
    cadastro_zerado: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    pid, periodo = com_evento(cadastro, cadastro_zerado, fabrica, TipoEvento.OBITO)
    certidao = inserir_documento(engine_migracao, pid, "certidao_obito", cadastro_zerado["recepcao"])
    publicar(engine_web, DocumentoIncorporado(certidao, pid, "certidao_obito", vinculo_do_evento(periodo)))
    assert cadastro.pacientes.ver_ficha(pessoa(cadastro_zerado), pid).periodos[0].comprovante_anexado
    with engine_web.connect() as c:
        sql = "SELECT usuario_id, alteracoes FROM auditoria WHERE operacao = 'cadastro.evento.comprovante'"
        assert [tuple(r) for r in c.execute(text(sql))] == [(None, '{"comprovante":[false,true]}')]

    publicar(engine_web, DocumentoRevinculado(certidao, pid, pid + 1))  # levado a outro paciente (RF-713)
    assert not cadastro.pacientes.ver_ficha(pessoa(cadastro_zerado), pid).periodos[0].comprovante_anexado


@pytest.mark.requisito("RF-607", "DEC-53", "DD-81")
def test_documento_que_nao_serve_ao_evento_nao_e_ligado_e_nao_desfaz_a_incorporacao(
    cadastro_zerado: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    pid, periodo = com_evento(cadastro, cadastro_zerado, fabrica, TipoEvento.ALTA)
    outro, _ = com_evento(cadastro, cadastro_zerado, fabrica, TipoEvento.ALTA)
    errado = inserir_documento(engine_migracao, pid, "certidao_obito", cadastro_zerado["recepcao"])
    de_outro = inserir_documento(engine_migracao, outro, "documento_alta", cadastro_zerado["recepcao"])
    coletor = ColetorLogs()
    logging.getLogger("sar").addHandler(coletor)
    try:
        publicar(engine_web, DocumentoIncorporado(errado, pid, "certidao_obito", vinculo_do_evento(periodo)))
        publicar(engine_web, DocumentoIncorporado(de_outro, outro, "documento_alta", vinculo_do_evento(periodo)))
        publicar(engine_web, DocumentoIncorporado(errado, pid, "certidao_obito", "outra_coisa:1"))  # não é do cadastro
    finally:
        logging.getLogger("sar").removeHandler(coletor)
    assert not cadastro.pacientes.ver_ficha(pessoa(cadastro_zerado), pid).periodos[0].comprovante_anexado
    resultados = [linha for linha in coletor.linhas if "cadastro.evento.comprovante" in linha]
    assert len(resultados) == 2 and "tipo_nao_exigido" in resultados[0] and "outro_paciente" in resultados[1]


# ------------------------------------------------------------------ pendências
@pytest.mark.requisito("RF-109", "RF-102", "QAS-03")
def test_cadastro_incompleto_so_de_quem_esta_em_tratamento(
    cadastro_zerado: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    minimo = cadastro.pacientes.criar(recepcao, DadosPaciente(nome=fabrica.nome(), prontuario="F1"), JANEIRO)
    completo = replace(
        dados_completos(fabrica), sexo=None, rg="1", rg_orgao="SSP", naturalidade_municipio="5211909",
        logradouro="Rua A", numero="1", bairro="Centro", cep="75800000",
    )  # fmt: skip
    so_cep = cadastro.pacientes.criar(recepcao, completo, JANEIRO)
    saiu, _ = com_evento(cadastro, cadastro_zerado, fabrica, TipoEvento.ALTA)  # incompleto, mas fora (DEC-71)
    executar = cadastro.executar
    fonte = FonteCadastroIncompleto()
    itens = executar(lambda uow: fonte.listar(uow, recepcao))
    assert {i.paciente_id for i in itens} == {minimo, so_cep} and saiu not in {i.paciente_id for i in itens}
    por_paciente = {i.paciente_id: i for i in itens}
    assert por_paciente[minimo].descricao.startswith("Faltam: nascimento, sexo, nome da mãe, CPF, CNS")
    assert por_paciente[so_cep].descricao == "Faltam: sexo; CEP não verificado"
    assert (por_paciente[so_cep].prioridade, por_paciente[so_cep].destino) == (
        Prioridade.NORMAL,
        f"/pacientes/{so_cep}",
    )
    assert executar(lambda uow: fonte.contar(uow, recepcao)) == 2
    assert [i.paciente_id for i in executar(lambda uow: fonte.listar_por_pacientes(uow, recepcao, [so_cep]))] == [
        so_cep
    ]
    with engine_migracao.begin() as c:
        c.execute(text("UPDATE paciente SET anulado_em = NOW(6) WHERE id = :p"), {"p": minimo})
    assert [i.paciente_id for i in executar(lambda uow: fonte.listar(uow, recepcao))] == [so_cep]


@pytest.mark.requisito("RF-607", "INV-11", "RN-08")
def test_evento_sem_comprovante_em_qualquer_situacao(
    cadastro_zerado: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    pid, periodo = com_evento(cadastro, cadastro_zerado, fabrica, TipoEvento.DESISTENCIA)
    recepcao = pessoa(cadastro_zerado)
    fonte = FonteEventoSemComprovante()
    [item] = cadastro.executar(lambda uow: fonte.listar(uow, recepcao))
    assert (item.paciente_id, item.prioridade) == (pid, Prioridade.ALTA)
    assert item.descricao == "Desistência em 01/03/2026 sem termo de interrupção"
    termo = inserir_documento(engine_migracao, pid, "termo_interrupcao", cadastro_zerado["recepcao"])
    publicar(engine_web, DocumentoIncorporado(termo, pid, "termo_interrupcao", vinculo_do_evento(periodo)))
    assert cadastro.executar(lambda uow: fonte.listar(uow, recepcao)) == []


@pytest.mark.requisito("RF-108", "INV-08")
def test_possivel_duplicidade_ate_o_descarte(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    original = dados_completos(fabrica)
    a = cadastro.pacientes.criar(recepcao, original, JANEIRO)
    copia = replace(dados_completos(fabrica), nome=original.nome, data_nascimento=original.data_nascimento,
                    nome_mae=original.nome_mae)  # fmt: skip
    b = cadastro.pacientes.criar(recepcao, copia, JANEIRO, confirmar_duplicidade=True)
    fonte = FontePossivelDuplicidade()
    itens = cadastro.executar(lambda uow: fonte.listar(uow, recepcao))
    assert sorted(i.paciente_id for i in itens) == sorted([a, b])
    assert {i.descricao for i in itens} == {
        f"Tríade coincide com o prontuário {copia.prontuario}",
        f"Tríade coincide com o prontuário {original.prontuario}",
    }
    assert [i.paciente_id for i in cadastro.executar(lambda uow: fonte.listar_por_pacientes(uow, recepcao, [b]))] == [b]
    cadastro.pacientes.descartar_duplicidade(recepcao, a, b)
    assert cadastro.executar(lambda uow: fonte.listar(uow, recepcao)) == []


@pytest.mark.requisito("RNF-625", "CT-ACE-02")
@pytest.mark.parametrize("perfil", [Perfil.TI, Perfil.VISUALIZADOR, Perfil.ENFERMAGEM])
def test_pendencias_do_cadastro_nao_chegam_a_outros_perfis(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica, perfil: Perfil
) -> None:
    cadastro = montar(engine_web)
    pid, _ = com_evento(cadastro, cadastro_zerado, fabrica, TipoEvento.ALTA)
    contexto = pessoa(cadastro_zerado, "ti", perfil)
    for fonte in (FonteCadastroIncompleto(), FonteEventoSemComprovante(), FontePossivelDuplicidade()):
        assert cadastro.executar(lambda uow, f=fonte: f.listar(uow, contexto)) == []
        assert cadastro.executar(lambda uow, f=fonte: f.listar_por_pacientes(uow, contexto, [pid])) == []


# ------------------------------------------------------------------ marco de retenção (DD-01)
@pytest.mark.requisito("DD-01")
def test_marco_de_retencao(cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    marco = ServicoMarcoRetencao()
    pid = cadastro.pacientes.criar(recepcao, dados_completos(fabrica), JANEIRO)
    em_tratamento = cadastro.executar(lambda uow: marco.marco(uow, pid))
    assert (em_tratamento.em_tratamento, em_tratamento.ultimo_encerramento) == (True, None)
    cadastro.eventos.registrar(recepcao, pid, TipoEvento.ALTA, date(2026, 3, 1), None)
    encerrado = cadastro.executar(lambda uow: marco.marco(uow, pid))
    assert (encerrado.em_tratamento, encerrado.ultimo_encerramento) == (False, date(2026, 3, 1))
    cadastro.pacientes.abrir_periodo(recepcao, pid, date(2026, 5, 1))  # novo período anula o prazo
    assert cadastro.executar(lambda uow: marco.marco(uow, pid)).em_tratamento
