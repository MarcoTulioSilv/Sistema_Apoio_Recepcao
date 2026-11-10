"""Pendências com o banco, pela composição completa (DDS §11, RF-1010, RF-1004, linhas 1, 11 e 12 da §11.1).

Relógio dos contextos: terça, 13/10/2026, 10h em Jataí.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from sar.composicao import Componentes, compor
from sar.modulo_04_documentos.armazenamento import Pastas
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado
from sar.nucleo.portas import ItemPendencia, Prioridade
from testes.apoio.acesso import HASHER
from testes.apoio.cadastro import AGORA, INICIO, ProvedorCepFalso, dados_completos, pessoa
from testes.apoio.documentos import AntimalwareFalso
from testes.apoio.fabrica import Fabrica
from testes.apoio.relogio_controlado import RelogioControlado

pytestmark = pytest.mark.integracao

U, AL, N = Prioridade.URGENCIA, Prioridade.ALTA, Prioridade.NORMAL


@dataclass
class Cenario:
    c: Componentes
    ids: dict[str, int]
    paciente_id: int
    nome: str
    engine_migracao: Engine

    def ctx(self, perfil: Perfil, chave: str = "recepcao") -> Contexto:
        return pessoa(self.ids, chave, perfil)

    def abrir_aviso(self, registro: int = 41) -> None:
        with self.engine_migracao.begin() as conexao:
            conexao.execute(text("INSERT INTO aviso_integridade (detectado_em, registro_divergente_id) "
                                 "VALUES (:d, :r)"), {"d": AGORA.replace(tzinfo=None), "r": registro})  # fmt: skip


@pytest.fixture
def cenario(
    engine_web: Engine, trilha_zerada: Engine, cadastro_zerado: dict[str, int], fabrica: Fabrica, tmp_path: Path
) -> Iterator[Cenario]:
    componentes = compor(engine_web, bytes(32), hasher=HASHER, provedor_cep=ProvedorCepFalso(),
                         relogio=RelogioControlado(AGORA), pastas=Pastas(tmp_path / "c", tmp_path / "q"),
                         antimalware=AntimalwareFalso())  # fmt: skip
    dados = dados_completos(fabrica)  # sem sexo, RG e endereço: cadastro incompleto (linha 1)
    paciente_id = componentes.pacientes.criar(pessoa(cadastro_zerado), dados, INICIO)
    yield Cenario(componentes, cadastro_zerado, paciente_id, dados.nome, trilha_zerada)


def codigos(itens: list[ItemPendencia]) -> list[str]:
    return [i.codigo for i in itens]


@pytest.mark.requisito("RF-1010", "RNF-408", "RF-1008", "CT-PEN-03")
def test_cada_perfil_ve_so_as_suas_linhas_na_ordem(cenario: Cenario) -> None:
    pendencias = cenario.c.pendencias
    cenario.c.anulacao.solicitar(cenario.ctx(Perfil.RECEPCAO), cenario.paciente_id, "Cadastrado em duplicidade")
    cenario.abrir_aviso()

    recepcao = pendencias.listar(cenario.ctx(Perfil.RECEPCAO))
    assert "cadastro_incompleto" in codigos(recepcao)
    assert not {"solicitacao_autorizacao", "falha_cadeia"} & set(codigos(recepcao))

    admin = pendencias.listar(cenario.ctx(Perfil.ADMINISTRACAO, "admin"))
    # urgência no topo; entre as altas, a mais antiga primeiro: o paciente está sem alocação desde o início
    assert codigos(admin)[:3] == ["falha_cadeia", "sem_alocacao", "solicitacao_autorizacao"]
    assert [i.prioridade for i in admin] == sorted((i.prioridade for i in admin), key=[U, AL, N].index)
    pedido = next(i for i in admin if i.codigo == "solicitacao_autorizacao")
    assert pedido.paciente_id == cenario.paciente_id and pedido.destino.startswith("/autorizacoes/")

    assert pendencias.listar(cenario.ctx(Perfil.VISUALIZADOR)) == []
    assert codigos(pendencias.listar(cenario.ctx(Perfil.ENFERMAGEM))) == ["sem_alocacao"]  # linha 6
    with pytest.raises(AcessoNegado):
        pendencias.listar(cenario.ctx(Perfil.RECEPCAO), "solicitacao_autorizacao")

    resumo = pendencias.resumo(cenario.ctx(Perfil.ADMINISTRACAO, "admin"))
    assert resumo.tipos[0].codigo == "falha_cadeia" and resumo.totais[U] == 1 and resumo.totais[AL] == 2


@pytest.mark.requisito("RF-1004", "RNF-625", "RF-1011", "CT-ACE-02", "CT-PEN-05")
def test_ti_ve_o_diagnostico_sem_dado_de_paciente(cenario: Cenario) -> None:
    cenario.c.anulacao.solicitar(cenario.ctx(Perfil.RECEPCAO), cenario.paciente_id, "Cadastrado em duplicidade")
    cenario.abrir_aviso(registro=41)
    ti = cenario.ctx(Perfil.TI, "ti")

    itens = cenario.c.pendencias.listar(ti)
    assert codigos(itens) == ["falha_cadeia"]
    assert itens[0].paciente_id is None and itens[0].identificador_interno == "41"
    assert "41" in itens[0].descricao
    assert cenario.c.pendencias.dos_pacientes(ti, [cenario.paciente_id]) == {cenario.paciente_id: []}
    resumo = cenario.c.pendencias.resumo(ti)
    textos = " ".join(f"{t.nome} {t.codigo}" for t in resumo.tipos) + " ".join(i.descricao for i in itens)
    assert cenario.nome.split()[0] not in textos

    admin = cenario.c.pendencias.listar(cenario.ctx(Perfil.ADMINISTRACAO, "admin"), "falha_cadeia")
    assert admin[0].identificador_interno is None and "41" not in admin[0].descricao  # aviso simples


@pytest.mark.requisito("RF-1011", "CT-PEN-05")
def test_pendencia_da_cadeia_encerra_com_o_aviso(cenario: Cenario) -> None:
    cenario.abrir_aviso()
    admin = cenario.ctx(Perfil.ADMINISTRACAO, "admin")
    assert codigos(cenario.c.pendencias.listar(admin, "falha_cadeia")) == ["falha_cadeia"]
    aviso = cenario.c.integridade.ver_avisos(admin)[0]
    cenario.c.integridade.encerrar_aviso(admin, aviso.id, "Restauração de teste conferida com o TI")
    assert cenario.c.pendencias.listar(admin, "falha_cadeia") == []


@pytest.mark.requisito("RF-1008", "CT-PEN-05")
def test_pendencia_da_autorizacao_encerra_com_a_decisao(cenario: Cenario) -> None:
    pedido = cenario.c.anulacao.solicitar(cenario.ctx(Perfil.RECEPCAO), cenario.paciente_id, "Cadastro em dobro")
    admin = cenario.ctx(Perfil.ADMINISTRACAO, "admin")
    assert len(cenario.c.pendencias.listar(admin, "solicitacao_autorizacao")) == 1
    cenario.c.autorizacoes.recusar(admin, pedido, "Não é duplicidade")
    assert cenario.c.pendencias.listar(admin, "solicitacao_autorizacao") == []


@pytest.mark.requisito("RF-922", "DD-30", "CT-PEN-04")
def test_pendencias_por_paciente(cenario: Cenario, fabrica: Fabrica) -> None:
    outro = cenario.c.pacientes.criar(pessoa(cenario.ids), dados_completos(fabrica), INICIO)
    cenario.c.anulacao.solicitar(cenario.ctx(Perfil.RECEPCAO), cenario.paciente_id, "Cadastrado em duplicidade")

    recepcao = cenario.c.pendencias.dos_pacientes(cenario.ctx(Perfil.RECEPCAO), [cenario.paciente_id, outro])
    assert set(recepcao) == {cenario.paciente_id, outro}
    assert all(i.paciente_id == pid for pid, itens in recepcao.items() for i in itens)
    assert "solicitacao_autorizacao" not in codigos(recepcao[cenario.paciente_id])

    admin = cenario.c.pendencias.dos_pacientes(cenario.ctx(Perfil.ADMINISTRACAO, "admin"), [cenario.paciente_id])
    assert "solicitacao_autorizacao" in codigos(admin[cenario.paciente_id])
