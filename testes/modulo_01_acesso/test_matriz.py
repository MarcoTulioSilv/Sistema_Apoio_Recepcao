"""Matriz de permissões (DDS §4): conformidade com o documento e CT-ACE-01, gerado da própria matriz."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from sar.modulo_01_acesso.contrato import PermissionGuard
from sar.modulo_01_acesso.matriz import COLUNAS, MATRIZ, Acesso, Entrada, linha
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado

DDS = Path(__file__).resolve().parents[2] / "docs" / "DDS_recepcao-v1_1.md"
GUARDA = PermissionGuard()
AGORA = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def contexto(perfil: Perfil) -> Contexto:
    if perfil is Perfil.SISTEMA:
        return Contexto.sistema("teste", AGORA)
    return Contexto(1, perfil, 1, "10.0.0.5", AGORA, "a" * 32)


def entradas_do_dds() -> list[Entrada]:
    """Lê as tabelas do §4 do DDS com a mesma notação que o código usa."""
    texto = DDS.read_text(encoding="utf-8")
    secao = texto[texto.index("\n## 4. ") : texto.index("\n## 5. ")]
    entradas: list[Entrada] = []
    for bruta in secao.splitlines():
        if not bruta.startswith("| `"):
            continue  # cabeçalhos e a linha "Faixas etárias, tipos de documento, escalas" (só por migração)
        colunas = [c.strip() for c in bruta.strip().strip("|").split("|")]
        operacao, celulas, auditada = colunas[0], colunas[1:7], colunas[7]
        entradas.extend(linha(operacao, *celulas, auditada=auditada.startswith("Sim")))
    return entradas


def chave(e: Entrada) -> tuple[object, ...]:
    return (e.codigo, e.condicao, tuple(sorted((p.value, c) for p, c in e.celulas.items())), e.auditada)


@pytest.mark.requisito("CT-ACE-01", "DD-55", "AD-20")
def test_matriz_do_codigo_e_identica_a_do_dds() -> None:
    do_dds, do_codigo = {chave(e) for e in entradas_do_dds()}, {chave(e) for e in MATRIZ}
    assert len(do_dds) > 90  # o parser leu as tabelas, e não uma seção vazia
    assert sorted(do_dds - do_codigo, key=str) == [], "no DDS e não no código"
    assert sorted(do_codigo - do_dds, key=str) == [], "no código e não no DDS"


@pytest.mark.requisito("CT-ACE-01")
def test_cada_operacao_e_condicao_aparece_uma_vez() -> None:
    chaves = [(e.codigo, e.condicao) for e in MATRIZ]
    assert len(chaves) == len(set(chaves))


@pytest.mark.requisito("CT-ACE-01", "AD-20")
@pytest.mark.parametrize("perfil", COLUNAS, ids=lambda p: p.value)
@pytest.mark.parametrize("entrada", MATRIZ, ids=lambda e: f"{e.codigo}[{e.condicao}]" if e.condicao else e.codigo)
def test_guarda_decide_cada_operacao_para_cada_perfil(entrada: Entrada, perfil: Perfil) -> None:
    ctx = contexto(perfil)
    celula = entrada.celulas.get(perfil)
    executa = celula is not None and celula.acesso is Acesso.EXECUTA
    assert GUARDA.pode(ctx, entrada.codigo, entrada.condicao) is executa
    assert GUARDA.pode_solicitar(ctx, entrada.codigo, entrada.condicao) is (
        celula is not None and celula.acesso is Acesso.SOLICITA
    )
    if executa:
        assert GUARDA.exigir(ctx, entrada.codigo, entrada.condicao) == celula
    else:
        with pytest.raises(AcessoNegado):
            GUARDA.exigir(ctx, entrada.codigo, entrada.condicao)


@pytest.mark.requisito("RF-1004", "CT-ACE-02", "RNF-625")
def test_ti_so_alcanca_operacoes_sem_dado_de_paciente() -> None:
    """O TI fica no acesso, na configuração, nos jobs, na verificação dos documentos (só identificadores) e na
    carga pela linha de comando (só contagens). Nada de cadastro, operação, emissão, relatório ou titular."""
    permitidos = ("acesso.", "config.", "pendencia.", "agendamento.", "documento.integridade.", "carga.simular",
                  "carga.efetivar")  # fmt: skip
    do_ti = [e.codigo for e in MATRIZ if Perfil.TI in e.celulas]
    assert do_ti and all(codigo.startswith(permitidos) for codigo in do_ti), do_ti


@pytest.mark.requisito("DEC-55", "CT-ACE-03")
def test_enfermagem_nao_alcanca_documento_nem_ficha() -> None:
    proibidos = ("documento.", "cadastro.paciente.ver_ficha", "emissao.")
    assert not [e.codigo for e in MATRIZ if Perfil.ENFERMAGEM in e.celulas and e.codigo.startswith(proibidos)]


@pytest.mark.requisito("AD-20")
def test_contexto_de_sistema_nao_entra_por_tela() -> None:
    assert not GUARDA.pode(contexto(Perfil.SISTEMA), "acesso.sessao.entrar")


@pytest.mark.requisito("AD-20")
def test_operacao_desconhecida_ou_sem_condicao_e_erro_de_programacao() -> None:
    with pytest.raises(LookupError):
        GUARDA.pode(contexto(Perfil.RECEPCAO), "cadastro.paciente.apagar")
    with pytest.raises(LookupError):
        GUARDA.pode(contexto(Perfil.ADMINISTRACAO), "config.parametro.alterar")  # tem variantes
    with pytest.raises(LookupError):
        GUARDA.pode(contexto(Perfil.ADMINISTRACAO), "config.parametro.alterar", "todos")
    assert GUARDA.pode(contexto(Perfil.ADMINISTRACAO), "config.parametro.alterar", "operacionais")
    assert not GUARDA.pode(contexto(Perfil.ADMINISTRACAO), "config.parametro.alterar", "técnicos")
    assert GUARDA.pode_solicitar(contexto(Perfil.RECEPCAO), "operacao.pareamento.refazer", "mês fechado")


@pytest.mark.requisito("RNF-625")
def test_nota_da_celula_orienta_o_servico() -> None:
    assert GUARDA.exigir(contexto(Perfil.TI), "acesso.auditoria.consultar").nota == "pseudonimizado"
    assert GUARDA.exigir(contexto(Perfil.ADMINISTRACAO), "acesso.aviso_integridade.ver").nota == "simples"
    assert GUARDA.exigir(contexto(Perfil.RECEPCAO), "cadastro.rascunho.retomar").nota == "próprio"
