"""Períodos e coberturas no MySQL: RF-301, RF-302, RF-605, INV-01, INV-02, INV-09, DD-49, DD-101."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from sar.modulo_02_cadastro.contrato import DadosCobertura, Situacao, TipoCobertura
from sar.nucleo.contexto import Perfil
from sar.nucleo.erros import AcessoNegado, NaoEncontrado, RegraViolada
from testes.apoio.cadastro import Cadastro, dados_completos, montar, pessoa
from testes.apoio.fabrica import Fabrica

pytestmark = pytest.mark.integracao

SUS = DadosCobertura(TipoCobertura.SUS)
JANEIRO = date(2026, 1, 5)


def convenio(cadastro: Cadastro, usuarios: dict[str, int], nome: str = "Ipasgo") -> int:
    return cadastro.configuracao.incluir_convenio(pessoa(usuarios, "admin", Perfil.ADMINISTRACAO), nome)


def encerrar(engine: Engine, paciente_id: int, tipo: str, data: str) -> None:
    """O evento chega na Etapa 6; aqui ele é gravado direto, pelo usuário de migração."""
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE periodo_tratamento SET evento_tipo = :t, evento_data = :d WHERE paciente_id = :p AND aberto = 1"
            ),
            {"t": tipo, "d": data, "p": paciente_id},
        )


def codigo(chamada: object) -> str:
    assert callable(chamada)
    with pytest.raises(RegraViolada) as erro:
        chamada()
    return erro.value.codigo


# ------------------------------------------------------------------ coberturas
@pytest.mark.requisito("RF-301", "RF-302", "DD-101", "RNF-605")
def test_uma_cobertura_por_periodo_e_a_troca_pelo_retorno(
    cadastro_zerado: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    ipasgo = convenio(cadastro, cadastro_zerado)
    pid = cadastro.pacientes.criar(
        recepcao, dados_completos(fabrica), JANEIRO, cobertura=DadosCobertura(TipoCobertura.CONVENIO, ipasgo, " 123 ")
    )
    periodo = cadastro.pacientes.ver_ficha(recepcao, pid).periodos[0].id
    # Antes, a segunda cobertura entrava como nova vigência e o período ficava com duas.
    assert codigo(lambda: cadastro.pacientes.registrar_cobertura(recepcao, periodo, SUS)) == "INV-09"
    encerrar(engine_migracao, pid, "alta", "2026-03-31")
    cadastro.pacientes.abrir_periodo(recepcao, pid, date(2026, 4, 1), SUS)
    coberturas = [p.cobertura for p in cadastro.pacientes.ver_ficha(recepcao, pid).periodos]
    assert [(c.tipo, c.convenio_nome, c.carteirinha) for c in coberturas if c] == [
        (TipoCobertura.CONVENIO, "Ipasgo", "123"),
        (TipoCobertura.SUS, None, None),
    ]
    with engine_web.connect() as c:
        auditadas = c.execute(text("SELECT COUNT(*) FROM auditoria WHERE operacao = 'cadastro.cobertura.registrar'"))
        assert auditadas.scalar_one() == 2


@pytest.mark.requisito("INV-09", "RF-301", "DD-49", "DD-101")
def test_cobertura_em_periodo_encerrado_ou_com_convenio_inativo_e_recusada(
    cadastro_zerado: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    admin = pessoa(cadastro_zerado, "admin", Perfil.ADMINISTRACAO)
    amil = convenio(cadastro, cadastro_zerado, "Amil")
    cadastro.configuracao.inativar_convenio(admin, amil)
    pid = cadastro.pacientes.criar(recepcao, dados_completos(fabrica), JANEIRO)
    periodo = cadastro.pacientes.ver_ficha(recepcao, pid).periodos[0].id
    registrar = cadastro.pacientes.registrar_cobertura
    inativo = DadosCobertura(TipoCobertura.CONVENIO, amil)
    assert codigo(lambda: registrar(recepcao, periodo, inativo)) == "cobertura.convenio_inativo"
    assert codigo(lambda: registrar(recepcao, periodo, DadosCobertura(TipoCobertura.CONVENIO))) == "cobertura.convenio"
    with pytest.raises(NaoEncontrado):
        registrar(recepcao, periodo, DadosCobertura(TipoCobertura.CONVENIO, amil + 999))
    with pytest.raises(NaoEncontrado):
        registrar(recepcao, periodo + 999, SUS)
    encerrar(engine_migracao, pid, "alta", "2026-06-30")
    # Antes, o período encerrado ainda aceitava cobertura com início até a data do evento.
    assert codigo(lambda: registrar(recepcao, periodo, SUS)) == "cobertura.periodo_encerrado"
    assert cadastro.pacientes.ver_ficha(recepcao, pid).periodos[0].cobertura is None


@pytest.mark.requisito("INV-09", "DD-101")
def test_coberturas_simultaneas_no_periodo_sem_cobertura_gravam_uma_so(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    pid = cadastro.pacientes.criar(recepcao, dados_completos(fabrica), JANEIRO)
    periodo = cadastro.pacientes.ver_ficha(recepcao, pid).periodos[0].id

    def registrar(_: int) -> str:
        try:
            cadastro.pacientes.registrar_cobertura(recepcao, periodo, SUS)
        except RegraViolada as erro:
            return erro.codigo
        return "ok"

    with ThreadPoolExecutor(4) as grupo:
        assert sorted(grupo.map(registrar, range(4))) == ["INV-09"] * 3 + ["ok"]


@pytest.mark.requisito("INV-09", "DD-101")
def test_banco_recusa_segunda_cobertura_no_mesmo_periodo(
    cadastro_zerado: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    pid = cadastro.pacientes.criar(pessoa(cadastro_zerado), dados_completos(fabrica), JANEIRO, cobertura=SUS)
    with pytest.raises(IntegrityError, match="uq_cobertura__periodo"), engine_migracao.begin() as c:
        periodo = "SELECT id FROM periodo_tratamento WHERE paciente_id = :p"
        c.execute(text(f"INSERT INTO cobertura (periodo_id, tipo) SELECT ({periodo}), 'sus'"), {"p": pid})


# ------------------------------------------------------------------ períodos
@pytest.mark.requisito("RF-605", "INV-02", "INV-01")
def test_retorno_abre_novo_periodo_so_depois_do_encerramento(
    cadastro_zerado: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    abrir = cadastro.pacientes.abrir_periodo
    pid = cadastro.pacientes.criar(recepcao, dados_completos(fabrica), JANEIRO)
    assert codigo(lambda: abrir(recepcao, pid, date(2026, 5, 1))) == "INV-02"
    encerrar(engine_migracao, pid, "transferencia", "2026-03-10")
    assert cadastro.pacientes.ver_ficha(recepcao, pid).situacao is Situacao.INATIVO
    assert codigo(lambda: abrir(recepcao, pid, date(2026, 3, 9))) == "periodo.antes_do_fim_anterior"
    novo = abrir(recepcao, pid, date(2026, 5, 1), SUS)
    ficha = cadastro.pacientes.ver_ficha(recepcao, pid)
    assert ficha.situacao is Situacao.SEM_ALOCACAO
    assert [(p.id == novo, p.cobertura is not None) for p in ficha.periodos] == [(False, False), (True, True)]
    encerrar(engine_migracao, pid, "obito", "2026-07-01")
    assert codigo(lambda: abrir(recepcao, pid, date(2026, 8, 1))) == "INV-01"
    with pytest.raises(NaoEncontrado):
        abrir(recepcao, pid + 999_999, date(2026, 8, 1))


@pytest.mark.requisito("INV-02")
def test_aberturas_simultaneas_deixam_um_periodo_aberto_so(
    cadastro_zerado: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    pid = cadastro.pacientes.criar(recepcao, dados_completos(fabrica), JANEIRO)
    encerrar(engine_migracao, pid, "alta", "2026-02-01")
    datas = [date(2026, 3, d) for d in (1, 2, 3, 4)]

    def abrir(inicio: date) -> str:
        try:
            cadastro.pacientes.abrir_periodo(recepcao, pid, inicio)
        except RegraViolada as erro:
            return erro.codigo
        return "ok"

    with ThreadPoolExecutor(4) as grupo:
        assert sorted(grupo.map(abrir, datas)) == ["INV-02"] * 3 + ["ok"]
    with engine_web.connect() as c:
        abertos = c.execute(
            text("SELECT COUNT(*) FROM periodo_tratamento WHERE aberto = 1 AND paciente_id = :p"), {"p": pid}
        )
        assert abertos.scalar_one() == 1


@pytest.mark.requisito("CT-ACE-01")
def test_so_recepcao_e_administracao_abrem_periodo_e_registram_cobertura(
    cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> None:
    cadastro = montar(engine_web)
    pid = cadastro.pacientes.criar(pessoa(cadastro_zerado), dados_completos(fabrica), JANEIRO)
    periodo = cadastro.pacientes.ver_ficha(pessoa(cadastro_zerado), pid).periodos[0].id
    for perfil in (Perfil.VISUALIZADOR, Perfil.TI, Perfil.ENFERMAGEM):
        contexto = pessoa(cadastro_zerado, "admin", perfil)
        with pytest.raises(AcessoNegado):
            cadastro.pacientes.abrir_periodo(contexto, pid, date(2026, 5, 1))
        with pytest.raises(AcessoNegado):
            cadastro.pacientes.registrar_cobertura(contexto, periodo, SUS)
