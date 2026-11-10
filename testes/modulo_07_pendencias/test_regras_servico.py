"""Regras e serviço do MOD-07 sem banco: filtro pela matriz, ordem, contagem e quantas vezes cada fonte é consultada
(DDS §11, RNF-408, RF-1004)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from sar.composicao import compor
from sar.modulo_04_documentos.armazenamento import Pastas
from sar.modulo_07_pendencias import regras
from sar.modulo_07_pendencias.matriz import MATRIZ
from sar.modulo_07_pendencias.servicos import ServicoPendencias
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado
from sar.nucleo.portas import ItemPendencia, Prioridade
from sar.nucleo.uow import UnidadeDeTrabalho
from testes.apoio.documentos import AntimalwareFalso

AGORA = datetime(2026, 10, 13, 13, 0, tzinfo=UTC)
U, AL, N = Prioridade.URGENCIA, Prioridade.ALTA, Prioridade.NORMAL


def contexto(perfil: Perfil) -> Contexto:
    if perfil is Perfil.SISTEMA:
        return Contexto.sistema("teste", AGORA)
    return Contexto(1, perfil, 1, "10.0.0.5", AGORA, "a" * 32)


def item(codigo: str, prioridade: Prioridade, horas: int = 0, paciente: int | None = None) -> ItemPendencia:
    return ItemPendencia(codigo, prioridade, AGORA - timedelta(hours=horas), codigo, "/", paciente)


# ------------------------------------------------------------------ regras
@pytest.mark.requisito("RNF-408", "RF-1010", "CT-PEN-02")
def test_urgencia_no_topo_e_a_mais_antiga_primeiro() -> None:
    itens = [item("cadastro_incompleto", N, 50), item("evento_sem_comprovante", AL, 1),
             item("sessao_nao_confirmada", U, 2), item("evento_sem_comprovante", AL, 9),
             item("sessao_nao_confirmada", U, 30)]  # fmt: skip
    ordem = [(i.prioridade, i.desde) for i in regras.ordenar(itens)]
    assert ordem == [(U, AGORA - timedelta(hours=30)), (U, AGORA - timedelta(hours=2)),
                     (AL, AGORA - timedelta(hours=9)), (AL, AGORA - timedelta(hours=1)),
                     (N, AGORA - timedelta(hours=50))]  # fmt: skip


@pytest.mark.requisito("RF-1010", "CT-PEN-02")
def test_filtro_deixa_so_as_linhas_do_perfil() -> None:
    itens = [item("solicitacao_autorizacao", AL), item("presenca_sem_registro", N), item("cadastro_incompleto", N)]
    assert [i.codigo for i in regras.filtrar(itens, Perfil.RECEPCAO)] == ["cadastro_incompleto"]
    assert [i.codigo for i in regras.filtrar(itens, Perfil.ENFERMAGEM)] == ["presenca_sem_registro"]
    assert [i.codigo for i in regras.filtrar(itens, Perfil.ADMINISTRACAO)] == [
        "solicitacao_autorizacao", "cadastro_incompleto"]  # fmt: skip
    assert regras.filtrar(itens, Perfil.SISTEMA) == []


@pytest.mark.requisito("RF-1004", "RNF-625", "CT-ACE-02")
def test_item_com_paciente_nunca_chega_ao_ti() -> None:
    """Uma fonte que errasse e mandasse o paciente ao TI perde o item, em vez de vazar o dado."""
    itens = [item("documento_bloqueado", U, paciente=7), item("documento_bloqueado", U)]
    assert [i.paciente_id for i in regras.filtrar(itens, Perfil.TI)] == [None]
    assert len(regras.filtrar(itens, Perfil.ADMINISTRACAO)) == 2


@pytest.mark.requisito("RNF-408", "CT-PEN-02")
def test_contagem_por_tipo_com_prioridade_variavel() -> None:
    itens = [item("pedido_titular", AL, paciente=1), item("pedido_titular", U, paciente=2),
             item("pedido_titular", AL, paciente=3), item("cadastro_incompleto", N, paciente=1)]  # fmt: skip
    contagens = regras.contar_por_tipo(itens)
    assert contagens == [("pedido_titular", U, 1), ("pedido_titular", AL, 2), ("cadastro_incompleto", N, 1)]
    assert regras.totais(contagens) == {U: 1, AL: 2, N: 1}
    assert regras.totais([]) == {U: 0, AL: 0, N: 0}


@pytest.mark.requisito("RF-922", "DD-30")
def test_por_paciente_devolve_todos_os_pedidos() -> None:
    itens = [item("cadastro_incompleto", N, paciente=1), item("sem_alocacao", AL, paciente=1),
             item("cadastro_incompleto", N, paciente=9)]  # fmt: skip
    grupos = regras.por_paciente(itens, [1, 2])
    assert [i.codigo for i in grupos[1]] == ["sem_alocacao", "cadastro_incompleto"]
    assert grupos[2] == []
    assert 9 not in grupos


# ------------------------------------------------------------------ serviço, com fontes falsas
def executar_sem_banco[T](operacao: Callable[[UnidadeDeTrabalho], T]) -> T:
    return operacao(UOW_PROIBIDA)  # as fontes falsas não usam a unidade de trabalho


class _UowProibida:
    def __getattr__(self, nome: str) -> Any:
        raise AssertionError(f"a fonte consultou o banco ({nome}) para quem não vê a linha")


UOW_PROIBIDA: Any = _UowProibida()


@dataclass
class FonteFalsa:
    codigo: str
    itens: list[ItemPendencia] = field(default_factory=list)
    chamadas: list[str] = field(default_factory=list)

    def contar(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> int:
        self.chamadas.append("contar")
        return len(self.itens)

    def listar(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> list[ItemPendencia]:
        self.chamadas.append("listar")
        return list(self.itens)

    def listar_por_pacientes(
        self, uow: UnidadeDeTrabalho, contexto: Contexto, paciente_ids: Sequence[int]
    ) -> list[ItemPendencia]:
        self.chamadas.append(f"por_pacientes:{list(paciente_ids)}")
        return [i for i in self.itens if i.paciente_id in paciente_ids]


def servico(*fontes: FonteFalsa) -> ServicoPendencias:
    return ServicoPendencias(executar_sem_banco, fontes)


@pytest.mark.requisito("RF-1010", "CT-PEN-03")
def test_so_consulta_as_fontes_que_o_perfil_ve() -> None:
    autorizacao = FonteFalsa("solicitacao_autorizacao", [item("solicitacao_autorizacao", AL)])
    cadastro = FonteFalsa("cadastro_incompleto", [item("cadastro_incompleto", N, paciente=1)])
    pendencias = servico(autorizacao, cadastro)
    assert [i.codigo for i in pendencias.listar(contexto(Perfil.RECEPCAO))] == ["cadastro_incompleto"]
    assert autorizacao.chamadas == []
    assert [i.codigo for i in pendencias.listar(contexto(Perfil.ADMINISTRACAO))] == [
        "solicitacao_autorizacao", "cadastro_incompleto"]  # fmt: skip


@pytest.mark.requisito("RF-1010", "CT-PEN-03")
def test_linha_de_outro_perfil_e_acesso_negado() -> None:
    pendencias = servico(FonteFalsa("solicitacao_autorizacao"))
    with pytest.raises(AcessoNegado):
        pendencias.listar(contexto(Perfil.RECEPCAO), "solicitacao_autorizacao")
    with pytest.raises(AcessoNegado):
        pendencias.listar(contexto(Perfil.RECEPCAO), "linha_que_nao_existe")
    assert pendencias.listar(contexto(Perfil.ADMINISTRACAO), "solicitacao_autorizacao") == []


@pytest.mark.requisito("AD-20")
def test_contexto_de_sistema_nao_ve_pendencias() -> None:
    with pytest.raises(AcessoNegado):
        servico().resumo(contexto(Perfil.SISTEMA))


@pytest.mark.requisito("RNF-408", "CT-PEN-02")
def test_resumo_conta_sem_listar_salvo_a_prioridade_variavel() -> None:
    titular = FonteFalsa("pedido_titular", [item("pedido_titular", U, paciente=1), item("pedido_titular", AL, 2)])
    sessao = FonteFalsa("sessao_nao_confirmada", [item("sessao_nao_confirmada", U, 3)])
    cadastro = FonteFalsa("cadastro_incompleto")
    resumo = servico(titular, sessao, cadastro).resumo(contexto(Perfil.RECEPCAO))
    assert [(t.codigo, t.prioridade, t.quantidade) for t in resumo.tipos] == [
        ("sessao_nao_confirmada", U, 1), ("pedido_titular", U, 1), ("pedido_titular", AL, 1)]  # fmt: skip
    assert resumo.totais == {U: 2, AL: 1, N: 0} and resumo.total == 3
    assert sessao.chamadas == ["contar"] and cadastro.chamadas == ["contar"] and titular.chamadas == ["listar"]
    assert resumo.tipos[0].nome == "Sessão de turno não confirmada"


@pytest.mark.requisito("RF-922", "DD-30", "CT-PEN-04")
def test_dos_pacientes_uma_chamada_por_fonte_e_so_fontes_de_paciente() -> None:
    cadastro = FonteFalsa("cadastro_incompleto", [item("cadastro_incompleto", N, paciente=1)])
    sessao = FonteFalsa("sessao_nao_confirmada", [item("sessao_nao_confirmada", U)])
    grupos = servico(cadastro, sessao).dos_pacientes(contexto(Perfil.RECEPCAO), [1, 2, 1])
    assert cadastro.chamadas == ["por_pacientes:[1, 2]"] and sessao.chamadas == []
    assert {k: [i.codigo for i in v] for k, v in grupos.items()} == {1: ["cadastro_incompleto"], 2: []}


@pytest.mark.requisito("RF-1004", "CT-ACE-02")
def test_ti_nao_recebe_pendencia_de_paciente() -> None:
    cadastro = FonteFalsa("cadastro_incompleto", [item("cadastro_incompleto", N, paciente=1)])
    assert servico(cadastro).dos_pacientes(contexto(Perfil.TI), [1]) == {1: []}
    assert cadastro.chamadas == []


@pytest.mark.requisito("DD-54", "DD-55")
def test_fonte_fora_da_matriz_ou_repetida_e_erro_de_composicao() -> None:
    with pytest.raises(ValueError):
        servico(FonteFalsa("linha_inventada"))
    with pytest.raises(ValueError):
        servico(FonteFalsa("cadastro_incompleto"), FonteFalsa("cadastro_incompleto"))


# ------------------------------------------------------------------ fontes reais, ligadas pela composição
@pytest.fixture
def fontes_compostas(tmp_path: Path) -> Any:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    componentes = compor(engine, bytes(32), pastas=Pastas(tmp_path / "c", tmp_path / "q"),
                         antimalware=AntimalwareFalso())  # fmt: skip
    yield componentes.fontes_pendencia
    engine.dispose()


@pytest.mark.requisito("DD-54", "DD-55")
def test_composicao_liga_uma_fonte_por_linha_da_matriz(fontes_compostas: Any) -> None:
    ligadas = {fonte.codigo for fonte in fontes_compostas}
    faltam = {linha.codigo for linha in MATRIZ} - ligadas
    assert faltam <= {"job_atrasado", "disco_acima_do_limite"}  # as do MOD-09 entram com o agendador


@pytest.mark.requisito("RF-1004", "RF-1010", "CT-PEN-03")
@pytest.mark.parametrize("perfil", [p for p in Perfil if p is not Perfil.SISTEMA], ids=lambda p: p.value)
def test_fonte_real_nao_consulta_o_banco_para_quem_nao_ve_a_linha(fontes_compostas: Any, perfil: Perfil) -> None:
    ctx = contexto(perfil)
    for fonte in fontes_compostas:
        if regras.ve(perfil, fonte.codigo):
            continue
        assert fonte.listar(UOW_PROIBIDA, ctx) == [], fonte.codigo
        assert fonte.listar_por_pacientes(UOW_PROIBIDA, ctx, [1]) == [], fonte.codigo
