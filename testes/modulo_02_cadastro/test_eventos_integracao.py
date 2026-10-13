"""Eventos no MySQL: RF-601 a RF-606, CT-CAD-07 (DEC-65, DD-31), INV-01, INV-02 e a correção por autorização."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

import pytest
from sqlalchemy import Engine, text

from sar.modulo_02_cadastro.contrato import Situacao, TipoEvento
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado, NaoEncontrado, RegraViolada
from sar.nucleo.portas import Impedimento, OperacaoPeriodo
from sar.nucleo.uow import UnidadeDeTrabalho
from testes.apoio.cadastro import Cadastro, dados_completos, montar, pessoa
from testes.apoio.fabrica import Fabrica

pytestmark = pytest.mark.integracao

JANEIRO = date(2026, 1, 5)
ALTA, OBITO = TipoEvento.ALTA, TipoEvento.OBITO


@dataclass
class PresencaFalsa:
    """Faz o papel do MOD-03 (Incremento 3): presença confirmada numa data impede encerrar antes dela."""

    presenca: date
    consultas: list[tuple[date, OperacaoPeriodo]] = field(default_factory=list)
    encerramentos: list[date] = field(default_factory=list)

    def impedimentos(
        self, uow: UnidadeDeTrabalho, paciente_id: int, data: date, operacao: OperacaoPeriodo
    ) -> list[Impedimento]:
        self.consultas.append((data, operacao))
        if data < self.presenca:
            return [Impedimento("presenca_posterior", "Presença confirmada depois da data", (self.presenca,))]
        return []

    def ao_encerrar(self, uow: UnidadeDeTrabalho, contexto: Contexto, paciente_id: int, data: date) -> None:
        self.encerramentos.append(data)


def codigo(chamada: object) -> str:
    assert callable(chamada)
    with pytest.raises(RegraViolada) as erro:
        chamada()
    return erro.value.codigo


def novo(cadastro: Cadastro, usuarios: dict[str, int], fabrica: Fabrica) -> tuple[int, int]:
    pid = cadastro.pacientes.criar(pessoa(usuarios), dados_completos(fabrica), JANEIRO)
    return pid, cadastro.pacientes.ver_ficha(pessoa(usuarios), pid).periodos[-1].id


def admin(usuarios: dict[str, int]) -> Contexto:
    return pessoa(usuarios, "admin", Perfil.ADMINISTRACAO)


# ------------------------------------------------------------------ registro
@pytest.mark.requisito("RF-601", "RF-602", "RF-603", "RNF-605")
def test_registrar_evento_encerra_o_periodo(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    pid, periodo = novo(cadastro, cadastro_zerado, fabrica)
    registrar = cadastro.eventos.registrar
    assert codigo(lambda: registrar(recepcao, pid, ALTA, date(2026, 3, 1), "Casa")) == "evento.local_nao_se_aplica"
    assert codigo(lambda: registrar(recepcao, pid, ALTA, date(2026, 1, 4), None)) == "evento.antes_do_inicio"
    assert codigo(lambda: registrar(recepcao, pid, ALTA, date(2026, 10, 14), None)) == "evento.data_futura"
    registrar(recepcao, pid, TipoEvento.TRANSFERENCIA, date(2026, 3, 1), " Hospital de Rio Verde ")
    ficha = cadastro.pacientes.ver_ficha(recepcao, pid)
    [p] = ficha.periodos
    assert (p.evento_tipo, p.evento_data, p.evento_local, p.comprovante_anexado) == (
        TipoEvento.TRANSFERENCIA, date(2026, 3, 1), "Hospital de Rio Verde", False
    )  # fmt: skip
    assert ficha.situacao is Situacao.INATIVO
    assert codigo(lambda: registrar(recepcao, pid, ALTA, date(2026, 3, 2), None)) == "evento.periodo_encerrado"
    with engine_web.connect() as c:
        sql = "SELECT entidade_id FROM auditoria WHERE operacao = 'cadastro.evento.registrar'"
        assert c.execute(text(sql)).scalars().all() == [str(periodo)]


@pytest.mark.requisito("INV-01", "RF-604")
def test_depois_do_obito_nada_mais_e_registrado(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    pid, _ = novo(cadastro, cadastro_zerado, fabrica)
    cadastro.eventos.registrar(recepcao, pid, OBITO, date(2026, 5, 1), "Hospital Fictício")
    assert cadastro.pacientes.ver_ficha(recepcao, pid).situacao is Situacao.FALECIDO
    assert codigo(lambda: cadastro.eventos.registrar(recepcao, pid, ALTA, date(2026, 5, 2), None)) == "INV-01"
    with pytest.raises(NaoEncontrado):
        cadastro.eventos.registrar(recepcao, pid + 999_999, ALTA, date(2026, 5, 2), None)


# ------------------------------------------------------------------ CT-CAD-07: impedimentos
@pytest.mark.requisito("CT-CAD-07", "RF-604", "DD-31")
def test_evento_retroativo_com_presenca_posterior_e_impedido(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    presenca = PresencaFalsa(date(2026, 4, 10))
    cadastro.verificadores.append(presenca)
    recepcao = pessoa(cadastro_zerado)
    pid, _ = novo(cadastro, cadastro_zerado, fabrica)
    with pytest.raises(RegraViolada) as erro:
        cadastro.eventos.registrar(recepcao, pid, ALTA, date(2026, 4, 1), None)
    assert erro.value.codigo == "evento.impedimentos"
    [impedimento] = erro.value.detalhe["impedimentos"]
    assert (impedimento.codigo, tuple(impedimento.datas)) == ("presenca_posterior", (date(2026, 4, 10),))
    assert cadastro.pacientes.ver_ficha(recepcao, pid).periodos[0].evento_tipo is None  # nada gravado
    assert presenca.encerramentos == []
    cadastro.eventos.registrar(recepcao, pid, ALTA, date(2026, 4, 10), None)  # no dia da presença: vale
    assert presenca.encerramentos == [date(2026, 4, 10)]  # e as trocas e extras depois dela são canceladas
    assert presenca.consultas == [
        (date(2026, 4, 1), OperacaoPeriodo.ENCERRAR),
        (date(2026, 4, 10), OperacaoPeriodo.ENCERRAR),
    ]


# ------------------------------------------------------------------ correção e remoção por autorização
@pytest.mark.requisito("RF-606", "CT-AUD-06", "DEC-42")
def test_correcao_pedida_pela_recepcao_e_aprovada_pela_administracao(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    pid, periodo = novo(cadastro, cadastro_zerado, fabrica)
    cadastro.eventos.registrar(recepcao, pid, ALTA, date(2026, 3, 1), None)
    pedido = cadastro.eventos.solicitar_correcao(recepcao, periodo, TipoEvento.TRANSFERENCIA, date(2026, 3, 2),
                                                 "Hospital Fictício", "Era transferência")  # fmt: skip
    [pendente] = cadastro.autorizacoes.pendentes(admin(cadastro_zerado))
    assert "Alta em 01/03/2026 → Transferência em 02/03/2026" in pendente.descricao
    assert cadastro.autorizacoes.aprovar(admin(cadastro_zerado), pedido) == "executada"
    [p] = cadastro.pacientes.ver_ficha(recepcao, pid).periodos
    assert (p.evento_tipo, p.evento_data, p.evento_local) == (
        TipoEvento.TRANSFERENCIA,
        date(2026, 3, 2),
        "Hospital Fictício",
    )
    with engine_web.connect() as c:
        sql = "SELECT usuario_id, autorizador_id FROM auditoria WHERE operacao = 'cadastro.evento.corrigir'"
        assert [tuple(r) for r in c.execute(text(sql))] == [(cadastro_zerado["recepcao"], cadastro_zerado["admin"])]


@pytest.mark.requisito("RF-606", "DEC-53", "P-01")
def test_correcao_do_tipo_pela_administracao_executa_na_hora_e_desliga_o_comprovante(
    cadastro_zerado: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    pid, periodo = novo(cadastro, cadastro_zerado, fabrica)
    cadastro.eventos.registrar(admin(cadastro_zerado), pid, ALTA, date(2026, 3, 1), None)
    documento = uuid.uuid4().bytes
    with engine_migracao.begin() as c:
        c.execute(
            text(
                "INSERT INTO documento (id, paciente_id, tipo, versao, arquivo, chave_cifrada, nonce, hash_sha256,"
                " paginas, origem, capturado_em, capturado_por, local_digitalizacao) VALUES (:d, :p, 'documento_alta',"
                " 1, :a, REPEAT('k', 60), REPEAT('n', 12), REPEAT('h', 64), 1, 'scanner', NOW(6), :u, 'Recepção')"
            ),
            {"d": documento, "p": pid, "a": uuid.uuid4().hex[:36].ljust(36, "0"), "u": cadastro_zerado["admin"]},
        )
        c.execute(
            text("UPDATE periodo_tratamento SET evento_documento_id = :d WHERE id = :p"), {"d": documento, "p": periodo}
        )
    assert cadastro.pacientes.ver_ficha(admin(cadastro_zerado), pid).periodos[0].comprovante_anexado
    cadastro.eventos.solicitar_correcao(admin(cadastro_zerado), periodo, ALTA, date(2026, 3, 3), None, "Data errada")
    assert cadastro.pacientes.ver_ficha(admin(cadastro_zerado), pid).periodos[0].comprovante_anexado  # mesmo tipo
    cadastro.eventos.solicitar_correcao(admin(cadastro_zerado), periodo, TipoEvento.DESISTENCIA, date(2026, 3, 3),
                                        None, "Era desistência")  # fmt: skip
    [p] = cadastro.pacientes.ver_ficha(admin(cadastro_zerado), pid).periodos
    assert (p.evento_tipo, p.comprovante_anexado) == (TipoEvento.DESISTENCIA, False)


@pytest.mark.requisito("RF-606", "CT-AUD-06")
def test_correcao_invalidada_se_o_evento_mudou_depois_do_pedido(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    pid, periodo = novo(cadastro, cadastro_zerado, fabrica)
    cadastro.eventos.registrar(recepcao, pid, ALTA, date(2026, 3, 1), None)
    pedido = cadastro.eventos.solicitar_correcao(recepcao, periodo, ALTA, date(2026, 3, 5), None, "Data errada")
    cadastro.eventos.solicitar_correcao(admin(cadastro_zerado), periodo, ALTA, date(2026, 3, 2), None, "Outra data")
    assert cadastro.autorizacoes.aprovar(admin(cadastro_zerado), pedido) == "invalidada"
    assert cadastro.pacientes.ver_ficha(recepcao, pid).periodos[0].evento_data == date(2026, 3, 2)


@pytest.mark.requisito("RF-606", "CT-CAD-07", "INV-01")
def test_regras_da_correcao(cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    pid, periodo = novo(cadastro, cadastro_zerado, fabrica)
    corrigir = cadastro.eventos.solicitar_correcao
    assert codigo(lambda: corrigir(recepcao, periodo, ALTA, date(2026, 3, 1), None, "x")) == "evento.inexistente"
    cadastro.eventos.registrar(recepcao, pid, ALTA, date(2026, 4, 20), None)
    cadastro.pacientes.abrir_periodo(recepcao, pid, date(2026, 5, 1))
    assert codigo(lambda: corrigir(recepcao, periodo, OBITO, date(2026, 4, 20), None, "x")) == "INV-01"
    assert codigo(lambda: corrigir(recepcao, periodo, ALTA, date(2026, 5, 2), None, "x")) == (
        "evento.depois_do_periodo_seguinte"
    )
    cadastro.verificadores.append(PresencaFalsa(date(2026, 4, 15)))
    assert codigo(lambda: corrigir(recepcao, periodo, ALTA, date(2026, 4, 10), None, "x")) == "evento.impedimentos"
    corrigir(recepcao, periodo, ALTA, date(2026, 4, 25), None, "Data errada")  # adiar não esbarra em presença
    with pytest.raises(NaoEncontrado):
        corrigir(recepcao, periodo + 999_999, ALTA, date(2026, 4, 25), None, "x")


@pytest.mark.requisito("RF-606", "INV-02")
def test_remocao_reabre_o_ultimo_periodo_e_so_ele(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    pid, primeiro = novo(cadastro, cadastro_zerado, fabrica)
    cadastro.eventos.registrar(recepcao, pid, ALTA, date(2026, 2, 1), None)
    segundo = cadastro.pacientes.abrir_periodo(recepcao, pid, date(2026, 3, 1))
    cadastro.eventos.registrar(recepcao, pid, OBITO, date(2026, 6, 1), None)
    remover = cadastro.eventos.solicitar_remocao
    assert codigo(lambda: remover(recepcao, primeiro, "Engano")) == "evento.nao_e_o_ultimo"
    pedido = remover(recepcao, segundo, "Óbito registrado no paciente errado")
    [pendente] = cadastro.autorizacoes.pendentes(admin(cadastro_zerado))
    assert "Óbito em 01/06/2026" in pendente.descricao and "reabrir" in pendente.descricao
    assert cadastro.autorizacoes.aprovar(admin(cadastro_zerado), pedido) == "executada"
    ficha = cadastro.pacientes.ver_ficha(recepcao, pid)
    assert ficha.situacao is Situacao.SEM_ALOCACAO and ficha.periodos[-1].evento_tipo is None


@pytest.mark.requisito("CT-ACE-01", "CT-ACE-03")
def test_permissoes_do_evento(cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica) -> None:
    cadastro = montar(engine_web)
    pid, periodo = novo(cadastro, cadastro_zerado, fabrica)
    cadastro.eventos.registrar(pessoa(cadastro_zerado), pid, ALTA, date(2026, 3, 1), None)
    for perfil in (Perfil.VISUALIZADOR, Perfil.TI, Perfil.ENFERMAGEM):
        contexto = pessoa(cadastro_zerado, "admin", perfil)
        with pytest.raises(AcessoNegado):
            cadastro.eventos.registrar(contexto, pid, ALTA, date(2026, 3, 1), None)
        with pytest.raises(AcessoNegado):
            cadastro.eventos.solicitar_correcao(contexto, periodo, ALTA, date(2026, 3, 2), None, "x")
        with pytest.raises(AcessoNegado):
            cadastro.eventos.solicitar_remocao(contexto, periodo, "x")
