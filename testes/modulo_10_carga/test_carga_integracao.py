"""Carga inicial com o banco (DDS §14, PT §4.7): planilhas sintéticas com os defeitos reais (PT §5.3), pelo usuário
de banco da web (DD-58), com o contexto do TI.

O relógio dos contextos é terça, 13/10/2026, às 10h em Jataí.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from sar.cli import main
from sar.composicao import SemCep, montar_barramento, montar_executor
from sar.modulo_01_acesso.servicos import ServicoAuditoria
from sar.modulo_02_cadastro.pendencias import ServicoChecklist
from sar.modulo_02_cadastro.servicos import ServicoPacientes
from sar.modulo_06_configuracao.servicos import ServicoReferencias
from sar.modulo_08_dados.cifra import CifraAesGcm
from sar.modulo_08_dados.relogio import RelogioSistema
from sar.modulo_10_carga.contrato import Modo
from sar.modulo_10_carga.servicos import PLANILHA_BASE, ServicoCarga, associado
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado, RegraViolada
from sar.nucleo.portas import Finalidade
from testes.apoio import planilhas
from testes.apoio.acesso import SENHA, CriarUsuario
from testes.apoio.cadastro import AGORA, montar, pessoa
from testes.apoio.fabrica import VALORES_SENSIVEIS, Fabrica

pytestmark = pytest.mark.integracao

CHAVE = bytes(range(32))


def sortear_os_primeiros(ids: list[int], quantos: int) -> list[int]:
    return sorted(ids)[:quantos]


def servico(engine: Engine) -> ServicoCarga:
    executar = montar_executor(engine, montar_barramento(RelogioSistema()))
    auditoria = ServicoAuditoria()
    referencias = ServicoReferencias()
    pacientes = ServicoPacientes(executar, auditoria, referencias, SemCep())
    return ServicoCarga(executar, auditoria, pacientes, referencias, CifraAesGcm(CHAVE), sortear_os_primeiros)


def ti(usuarios: dict[str, int]) -> Contexto:
    return Contexto(usuarios["ti"], Perfil.TI, None, "cli.carga", AGORA, "e" * 32)


@pytest.fixture
def carga(cadastro_zerado: dict[str, int], trilha_zerada: Engine) -> Iterator[dict[str, int]]:
    """Cadastro vazio e o convênio da ficha que não é SUS (IPASGO), como a administração teria cadastrado."""
    with trilha_zerada.begin() as c:
        c.execute(text("INSERT INTO convenio (nome, ativo) VALUES ('IPASGO', 1)"))
    yield cadastro_zerado


@pytest.fixture
def sinteticas(fabrica: Fabrica, tmp_path: Path) -> tuple[planilhas.Sinteticas, Path]:
    gerado = planilhas.gerar(fabrica)
    return gerado, gerado.gravar(tmp_path / "carga")


def contar(engine: Engine, sql: str, **parametros: object) -> int:
    with engine.connect() as c:
        return int(c.execute(text(sql), parametros).scalar_one())


def linhas_da_carga(engine: Engine) -> dict[int, tuple[object, ...]]:
    with engine.connect() as c:
        sql = "SELECT numero_linha, paciente_id, excecao_codigo, avisos, amostra_rodada, lote_id FROM carga_linha"
        return {int(linha[0]): tuple(linha[1:]) for linha in c.execute(text(sql))}


def paciente_do_prontuario(engine: Engine, prontuario: str) -> dict[str, object]:
    with engine.connect() as c:
        sql = "SELECT id, municipio_id, cep, cep_verificado, cpf, sexo FROM paciente WHERE prontuario = :p"
        return dict(c.execute(text(sql), {"p": prontuario}).mappings().one())


# ------------------------------------------------------------------ CT-MIG-01: contagem fecha, nenhuma linha some
@pytest.mark.requisito("CT-MIG-01", "RNF-103", "RF-1101", "RF-1102", "RF-1103", "RF-1106", "DD-114")
def test_efetivacao_fecha_a_conta_e_cada_ficha_tem_o_desfecho_esperado(
    carga: dict[str, int], engine_web: Engine, sinteticas: tuple[planilhas.Sinteticas, Path]
) -> None:
    gerado, pasta = sinteticas
    resumo = servico(engine_web).efetivar(ti(carga), pasta)
    assert resumo.modo is Modo.EFETIVACAO
    assert resumo.contagens["fecha"]
    assert resumo.contagens["p1"] == gerado.esperados()
    p4 = resumo.contagens["p4"]
    assert (p4["linhas"], p4["sem_prontuario"]) == (gerado.linhas_p4, 1)
    assert p4["fora_da_base"] >= gerado.fora_da_base_p4  # as históricas, mais a da ficha que nem chegou a ligar
    assert resumo.contagens["p3"]["casadas"] == gerado.casadas_p3
    assert contar(engine_web, "SELECT COUNT(*) FROM paciente") == gerado.esperados()["importados"]

    linhas = linhas_da_carga(engine_web)
    assert len(linhas) == len(gerado.fichas)  # toda ficha fica na área de trabalho até o aceite (DD-69)
    for ficha in gerado.fichas:
        paciente_id, excecao, avisos, _, _ = linhas[ficha.linha]
        esperado, avisos_esperados = planilhas.DEFEITOS.get(ficha.defeito or "", (planilhas.IMPORTADO, ()))
        if esperado == planilhas.IMPORTADO:
            assert (paciente_id is not None, excecao) == (True, None), ficha.defeito
        else:
            assert (paciente_id, excecao) == (None, esperado), ficha.defeito
        assert set(avisos_esperados) <= set(json.loads(avisos) if isinstance(avisos, str) else avisos or []), (
            ficha.defeito
        )


@pytest.mark.requisito("RF-1106", "DD-69", "DD-07", "RNF-624")
def test_ficha_original_fica_cifrada_e_amarrada_a_linha(
    carga: dict[str, int], engine_web: Engine, sinteticas: tuple[planilhas.Sinteticas, Path]
) -> None:
    gerado, pasta = sinteticas
    resumo = servico(engine_web).efetivar(ti(carga), pasta)
    ficha = gerado.fichas[0]
    with engine_web.connect() as c:
        cifrado, nonce = c.execute(
            text("SELECT conteudo_cifrado, nonce FROM carga_linha WHERE numero_linha = :n"), {"n": ficha.linha}
        ).one()
    assert ficha.nome.encode() not in cifrado
    claro = json.loads(CifraAesGcm(CHAVE).decifrar(Finalidade.CARGA, nonce, cifrado,
                                                    associado(resumo.lote_id, PLANILHA_BASE, ficha.linha)))  # fmt: skip
    assert ficha.nome in claro["p1"][0][1] or any(ficha.nome in str(v) for _, v in claro["p1"])
    assert claro["p4"]  # a linha da P4 que se ligou à ficha, para a conferência lado a lado
    with pytest.raises(Exception):  # noqa: B017 — outra linha não decifra (DD-07)
        CifraAesGcm(CHAVE).decifrar(Finalidade.CARGA, nonce, cifrado, associado(resumo.lote_id, PLANILHA_BASE, 999))


# ------------------------------------------------------------------ CT-MIG-02: IBGE por consulta
@pytest.mark.requisito("CT-MIG-02", "RF-1104", "DD-53")
def test_ibge_de_6_digitos_por_consulta_inclusive_fora_da_regra_do_digito(
    carga: dict[str, int], engine_web: Engine, sinteticas: tuple[planilhas.Sinteticas, Path]
) -> None:
    gerado, pasta = sinteticas
    servico(engine_web).efetivar(ti(carga), pasta)
    buriti = next(f for f in gerado.fichas if f.defeito == "ibge_fora_da_regra")
    assert paciente_do_prontuario(engine_web, buriti.prontuario or "")["municipio_id"] == "5203939"
    normal = gerado.fichas[0]
    assert paciente_do_prontuario(engine_web, normal.prontuario or "")["municipio_id"] == normal.municipio.codigo_ibge
    inexistente = next(f for f in gerado.fichas if f.defeito == "ibge_inexistente")
    assert paciente_do_prontuario(engine_web, inexistente.prontuario or "")["municipio_id"] is None


@pytest.mark.requisito("DD-53", "RF-1104")
def test_codigo_7_digitos_pela_tabela(cadastro_zerado: dict[str, int], engine_web: Engine) -> None:
    referencias = ServicoReferencias()
    executar = montar(engine_web).executar
    achado = executar(lambda uow: referencias.codigo_7_digitos(uow, "520393"))
    assert achado is not None and (achado.codigo, achado.uf) == ("5203939", "GO")
    assert executar(lambda uow: referencias.codigo_7_digitos(uow, "529999")) is None
    with pytest.raises(ValueError, match="6 dígitos"):
        executar(lambda uow: referencias.codigo_7_digitos(uow, "52039"))


# ------------------------------------------------------------------ CT-MIG-03: a simulação só deixa o relatório
@pytest.mark.requisito("CT-MIG-03", "DD-66", "RF-1106")
def test_simulacao_nao_deixa_nada_alem_do_relatorio(
    carga: dict[str, int], engine_web: Engine, sinteticas: tuple[planilhas.Sinteticas, Path]
) -> None:
    gerado, pasta = sinteticas
    carga_ = servico(engine_web)
    resumo = carga_.simular(ti(carga), pasta)
    assert resumo.modo is Modo.SIMULACAO and resumo.contagens["fecha"]
    assert resumo.contagens["p1"] == gerado.esperados()
    for tabela in ("paciente", "periodo_tratamento", "telefone", "contato", "cobertura"):
        assert contar(engine_web, f"SELECT COUNT(*) FROM {tabela}") == 0, tabela  # noqa: S608 — nome fixo
    assert contar(engine_web, "SELECT COUNT(*) FROM auditoria WHERE operacao = 'cadastro.paciente.criar'") == 0
    assert contar(engine_web, "SELECT COUNT(*) FROM auditoria WHERE operacao = 'carga.simular'") == 1
    linhas = linhas_da_carga(engine_web)
    assert all(paciente_id is None for paciente_id, *_ in linhas.values())
    assert all(excecao is not None or avisos for _, excecao, avisos, *_ in linhas.values())  # só o relatório
    # A simulação seguinte substitui o relatório da anterior (minimização).
    carga_.simular(ti(carga), pasta)
    assert len({lote for *_, lote in linhas_da_carga(engine_web).values()}) == 1


# ------------------------------------------------------------------ CT-MIG-04: uma efetivação só
@pytest.mark.requisito("CT-MIG-04", "DD-66", "DD-72")
def test_segunda_efetivacao_e_recusada(
    carga: dict[str, int], engine_web: Engine, sinteticas: tuple[planilhas.Sinteticas, Path]
) -> None:
    _, pasta = sinteticas
    carga_ = servico(engine_web)
    carga_.efetivar(ti(carga), pasta)
    pacientes = contar(engine_web, "SELECT COUNT(*) FROM paciente")
    for rodar in (carga_.efetivar, carga_.simular):
        with pytest.raises(RegraViolada) as erro:
            rodar(ti(carga), pasta)
        assert erro.value.codigo == "carga.ja_efetivada"
    assert contar(engine_web, "SELECT COUNT(*) FROM paciente") == pacientes


@pytest.mark.requisito("CT-MIG-04", "DD-72", "INV-15")
def test_o_banco_barra_a_segunda_efetivacao(carga: dict[str, int], engine_web: Engine) -> None:
    sql = text("INSERT INTO carga_lote (modo, situacao, iniciado_em) VALUES ('efetivacao', 'concluida', NOW(6))")
    with engine_web.begin() as c:
        c.execute(sql)
    with pytest.raises(IntegrityError, match="uq_carga_lote__uma_efetivacao"), engine_web.begin() as c:
        c.execute(sql)


# ------------------------------------------------------------------ quem pode e o que fica pendente
@pytest.mark.requisito("RF-1004", "DD-65")
def test_so_o_ti_roda_a_carga(
    carga: dict[str, int], engine_web: Engine, sinteticas: tuple[planilhas.Sinteticas, Path]
) -> None:
    _, pasta = sinteticas
    for contexto in (pessoa(carga), pessoa(carga, "admin", Perfil.ADMINISTRACAO),
                     Contexto.sistema("cli.carga", AGORA)):  # fmt: skip
        with pytest.raises(AcessoNegado):
            servico(engine_web).simular(contexto, pasta)


@pytest.mark.requisito("RF-1105", "RF-1107", "RF-1108", "DD-67", "DD-68", "DEC-58")
def test_importado_entra_pelas_regras_da_tela_com_as_pendencias(
    carga: dict[str, int], engine_web: Engine, sinteticas: tuple[planilhas.Sinteticas, Path]
) -> None:
    gerado, pasta = sinteticas
    servico(engine_web).efetivar(ti(carga), pasta)
    cadastro = montar(engine_web)
    ficha = cadastro.pacientes.ver_ficha(
        pessoa(carga), int(paciente_do_prontuario(engine_web, gerado.fichas[0].prontuario or "")["id"])
    )
    assert {"sexo", "naturalidade_municipio", "cep_nao_verificado"} <= set(ficha.pendencias)  # RF-1105, RF-1108
    assert not ficha.cep_verificado  # DD-68: nenhuma consulta em massa
    assert ficha.periodos[0].inicio == gerado.fichas[0].inicio  # período aberto desde o início (DD-67)
    errado = next(f for f in gerado.fichas if f.defeito == "cpf_digito_errado")
    assert paciente_do_prontuario(engine_web, errado.prontuario or "")["cpf"] is None  # DEC-58: não é gravado
    importados = contar(engine_web, "SELECT COUNT(*) FROM paciente")
    exigencias = cadastro.executar(lambda uow: ServicoChecklist().exigencias(uow, None, date(2026, 10, 13)))
    assert len(exigencias) == importados  # RF-1107: todos com o checklist de documentos a cumprir
    assert contar(engine_web, "SELECT COUNT(*) FROM documento") == 0
    criacoes = contar(engine_web, "SELECT COUNT(*) FROM auditoria WHERE operacao = 'cadastro.paciente.criar' "
                                  "AND usuario_id = :u AND motivo = 'carga inicial'", u=carga["ti"])  # fmt: skip
    assert criacoes == importados  # cada paciente na trilha, em nome do TI


@pytest.mark.requisito("P-29", "DD-66")
def test_efetivacao_sorteia_a_primeira_amostra(
    carga: dict[str, int], engine_web: Engine, sinteticas: tuple[planilhas.Sinteticas, Path]
) -> None:
    _, pasta = sinteticas
    servico(engine_web).efetivar(ti(carga), pasta)
    sorteadas = [linha for linha in linhas_da_carga(engine_web).values() if linha[3] == 1]
    assert len(sorteadas) == 15
    assert all(paciente_id is not None for paciente_id, *_ in sorteadas)  # só pacientes importados


# ------------------------------------------------------------------ CT-MIG-05: o terminal do TI só vê contagens
@pytest.mark.requisito("CT-MIG-05", "DD-65", "DD-113", "RF-1004", "RNF-624")
def test_terminal_do_ti_mostra_so_contagens(
    carga: dict[str, int],
    criar_usuario: CriarUsuario,
    sinteticas: tuple[planilhas.Sinteticas, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    gerado, pasta = sinteticas
    criar_usuario("ti_da_carga", perfil="ti")
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": SENHA)
    assert main(["carga", "simular", str(pasta), "--login", "ti_da_carga"]) == 0
    saida = capsys.readouterr()
    texto = saida.out + saida.err
    assert "A conta fecha: sim" in texto
    assert f"{gerado.esperados()['importados']} importada(s)" in texto
    assert "evento_saida" in texto  # o código, não quem é
    vazados = [v for v in VALORES_SENSIVEIS if len(v) >= 6 and v in texto]
    assert not vazados, "CT-MIG-05: dado de paciente no terminal do TI"


@pytest.mark.requisito("DD-66", "DD-113")
def test_terminal_recusa_efetivar_sem_confirmar_e_senha_errada(
    carga: dict[str, int],
    criar_usuario: CriarUsuario,
    sinteticas: tuple[planilhas.Sinteticas, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    engine_web: Engine,
) -> None:
    _, pasta = sinteticas
    criar_usuario("ti_da_carga_2", perfil="ti")
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": "senha errada")
    assert main(["carga", "efetivar", str(pasta), "--login", "ti_da_carga_2"]) == 1
    assert "--definitiva" in capsys.readouterr().err
    assert main(["carga", "efetivar", str(pasta), "--login", "ti_da_carga_2", "--definitiva"]) == 1
    assert "não conferem" in capsys.readouterr().err
    assert contar(engine_web, "SELECT COUNT(*) FROM carga_lote") == 0
