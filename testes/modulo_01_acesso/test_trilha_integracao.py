"""Verificação, aviso de integridade, âncora e expurgo no MySQL, cada um pelo usuário de banco do processo que
o executa em produção (DD-58): verificação e expurgo no worker, aviso e âncora pela tela (web)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text

from sar.cli import main
from sar.composicao import compor_auditoria, montar_barramento, montar_executor
from sar.modulo_01_acesso.contrato import AvisoDiagnostico, AvisoSimples
from sar.modulo_01_acesso.servicos import ServicoAuditoria, ServicoIntegridade
from sar.modulo_08_dados.relogio import RelogioSistema
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado, RegraViolada
from sar.nucleo.uow import UnidadeDeTrabalho

pytestmark = pytest.mark.integracao

AGORA = datetime(2026, 10, 6, 2, 0, tzinfo=UTC)
SISTEMA = Contexto.sistema("job.verificar_cadeia", AGORA)


def gravar(engine: Engine, quantidade: int, instante: datetime = AGORA) -> None:
    executar = montar_executor(engine, montar_barramento(RelogioSistema()))
    auditoria = ServicoAuditoria()
    contexto = Contexto.sistema("teste", instante)
    for i in range(quantidade):

        def operacao(uow: UnidadeDeTrabalho, i: int = i) -> None:
            auditoria.registrar(uow, contexto, "teste.operacao", "teste", str(i), {"i": (None, i)})

        executar(operacao)


def consulta(engine: Engine, sql: str) -> list[tuple[object, ...]]:
    with engine.connect() as c:
        return [tuple(linha) for linha in c.execute(text(sql))]


def pessoa(usuario_id: int, perfil: Perfil) -> Contexto:
    return Contexto(usuario_id, perfil, None, "10.0.0.9", AGORA, "c" * 32)


@pytest.mark.requisito("RNF-615", "CT-AUD-03", "QAS-13")
def test_registro_alterado_no_banco_e_apontado_e_abre_um_aviso(
    trilha_zerada: Engine, engine_web: Engine, engine_worker: Engine
) -> None:
    gravar(engine_web, 5)
    with trilha_zerada.begin() as c:
        c.execute(text("UPDATE auditoria SET motivo = 'adulterado' WHERE id = 3"))
    auditoria = compor_auditoria(engine_worker)

    resultado = auditoria.verificar_cadeia(SISTEMA)
    assert (resultado.integra, resultado.primeiro_divergente_id, resultado.motivo) == (False, 3, "hash")
    auditoria.verificar_cadeia(SISTEMA)  # de novo: não duplica o aviso

    assert consulta(trilha_zerada, "SELECT registro_divergente_id FROM aviso_integridade") == [(3,)]
    assert consulta(trilha_zerada, "SELECT COUNT(*) FROM auditoria_ancora") == [(0,)]  # divergente: sem âncora
    assert consulta(trilha_zerada, "SELECT operacao FROM auditoria ORDER BY id DESC LIMIT 1") == [
        ("acesso.cadeia.verificar",)
    ]


@pytest.mark.requisito("RNF-615", "DDS-13.1")
def test_cadeia_integra_registra_a_ancora_ate_a_cabeca_lida(trilha_zerada: Engine, engine_worker: Engine) -> None:
    gravar(engine_worker, 4)
    resultado = compor_auditoria(engine_worker).verificar_cadeia(SISTEMA)
    assert (resultado.integra, resultado.verificados) == (True, 4)
    [(ate, hash_ancora)] = consulta(trilha_zerada, "SELECT ate_registro_id, hash FROM auditoria_ancora")
    assert (ate, hash_ancora) == consulta(trilha_zerada, "SELECT id, hash_registro FROM auditoria WHERE id = 4")[0]
    # a própria verificação entrou na trilha depois da âncora, e a próxima verificação a confere
    assert compor_auditoria(engine_worker).verificar_cadeia(SISTEMA).verificados == 5


@pytest.mark.requisito("RNF-615", "CT-AUD-03")
def test_registro_apagado_no_fim_e_apontado(trilha_zerada: Engine, engine_worker: Engine) -> None:
    gravar(engine_worker, 4)
    with trilha_zerada.begin() as c:
        c.execute(text("DELETE FROM auditoria WHERE id = 4"))
    resultado = compor_auditoria(engine_worker).verificar_cadeia(SISTEMA)
    assert (resultado.primeiro_divergente_id, resultado.motivo) == (4, "cabeca")


@pytest.mark.requisito("RNF-628", "CT-AUD-05")
def test_expurgo_preserva_a_verificacao_a_partir_do_ponto_de_corte(
    trilha_zerada: Engine, engine_worker: Engine, engine_expurgo: Engine
) -> None:
    gravar(engine_worker, 3, AGORA - timedelta(days=6 * 365))  # mais de 5 anos
    gravar(engine_worker, 2, AGORA - timedelta(days=30))
    auditoria = compor_auditoria(engine_worker, engine_expurgo)
    assert auditoria.verificar_cadeia(SISTEMA).integra  # âncora até o 5; a verificação é o 6

    assert auditoria.expurgar(Contexto.sistema("job.expurgo", AGORA)) == 3

    assert consulta(trilha_zerada, "SELECT MIN(id), COUNT(*) FROM auditoria") == [(4, 3)]
    hash_do_3 = consulta(trilha_zerada, "SELECT hash_anterior FROM auditoria WHERE id = 4")[0][0]
    assert consulta(trilha_zerada, "SELECT primeiro_id_remanescente, hash_anterior FROM auditoria_corte") == [
        (4, hash_do_3)
    ]
    resultado = auditoria.verificar_cadeia(SISTEMA)
    assert (resultado.integra, resultado.verificados) == (True, 3)
    assert auditoria.expurgar(Contexto.sistema("job.expurgo", AGORA)) == 0  # nada mais tem 5 anos


@pytest.mark.requisito("RF-1011", "DEC-43")
def test_aviso_simples_para_administracao_e_diagnostico_para_ti(
    usuarios: dict[str, int], engine_web: Engine, engine_worker: Engine, trilha_zerada: Engine
) -> None:
    gravar(engine_worker, 3)
    with trilha_zerada.begin() as c:
        c.execute(text("UPDATE auditoria SET entidade = 'adulterado' WHERE id = 2"))
    compor_auditoria(engine_worker).verificar_cadeia(SISTEMA)
    integridade = ServicoIntegridade(
        montar_executor(engine_web, montar_barramento(RelogioSistema())), ServicoAuditoria()
    )
    admin, ti = pessoa(usuarios["admin"], Perfil.ADMINISTRACAO), pessoa(usuarios["ti"], Perfil.TI)

    [simples] = integridade.ver_avisos(admin)
    [diagnostico] = integridade.ver_avisos(ti)
    assert type(simples) is AvisoSimples  # sem o elo divergente
    assert isinstance(diagnostico, AvisoDiagnostico) and diagnostico.registro_divergente_id == 2
    with pytest.raises(AcessoNegado):
        integridade.ver_avisos(pessoa(usuarios["recepcao"], Perfil.RECEPCAO))

    with pytest.raises(AcessoNegado):
        integridade.encerrar_aviso(ti, simples.id, "explicação")
    with pytest.raises(RegraViolada):
        integridade.encerrar_aviso(admin, simples.id, "   ")
    integridade.encerrar_aviso(admin, simples.id, "TI restaurou o registro a partir do backup")
    with pytest.raises(RegraViolada):
        integridade.encerrar_aviso(admin, simples.id, "de novo")
    assert integridade.ver_avisos(admin) == []
    assert consulta(trilha_zerada, "SELECT encerrado_por FROM aviso_integridade") == [(usuarios["admin"],)]


@pytest.mark.requisito("DDS-13.2")
def test_administracao_anota_a_ancora_uma_vez(
    usuarios: dict[str, int], engine_web: Engine, engine_worker: Engine, trilha_zerada: Engine
) -> None:
    gravar(engine_worker, 2)
    compor_auditoria(engine_worker).verificar_cadeia(SISTEMA)
    [(ancora_id,)] = consulta(trilha_zerada, "SELECT id FROM auditoria_ancora")
    integridade = ServicoIntegridade(
        montar_executor(engine_web, montar_barramento(RelogioSistema())), ServicoAuditoria()
    )
    admin = pessoa(usuarios["admin"], Perfil.ADMINISTRACAO)

    with pytest.raises(AcessoNegado):
        integridade.anotar_ancora(pessoa(usuarios["ti"], Perfil.TI), int(str(ancora_id)))
    integridade.anotar_ancora(admin, int(str(ancora_id)))
    with pytest.raises(RegraViolada):
        integridade.anotar_ancora(admin, int(str(ancora_id)))
    assert consulta(trilha_zerada, "SELECT anotada_por FROM auditoria_ancora") == [(usuarios["admin"],)]


@pytest.mark.requisito("DDS-12.1")
def test_linha_de_comando_verifica_e_sai_com_erro_na_divergencia(
    trilha_zerada: Engine, engine_worker: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    gravar(engine_worker, 2)
    assert main(["verificar-cadeia"]) == 0
    assert "Cadeia íntegra: 2 registro(s)" in capsys.readouterr().out
    with trilha_zerada.begin() as c:
        c.execute(text("UPDATE auditoria SET motivo = 'adulterado' WHERE id = 1"))
    assert main(["verificar-cadeia"]) == 1
    assert "Divergência no registro 1 (hash)" in capsys.readouterr().err
