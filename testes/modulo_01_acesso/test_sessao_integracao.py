"""Sessão no MySQL (DD-05, DD-19, P-02): CT-ACE-05, CT-ACE-06 e CT-ACE-07."""

from __future__ import annotations

import contextlib
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text

from sar.composicao import montar_barramento, montar_executor
from sar.modulo_01_acesso.contrato import SessaoEncerrada
from sar.modulo_01_acesso.servicos import GerenciadorSessao, ServicoAuditoria, ServicoAutenticacao
from sar.nucleo.contexto import Perfil
from sar.nucleo.eventos import UsuarioInativado
from sar.nucleo.uow import UnidadeDeTrabalho
from testes.apoio.acesso import HASHER, SENHA, CriarUsuario, ParametrosPadrao
from testes.apoio.relogio_controlado import RelogioControlado

pytestmark = pytest.mark.integracao


@pytest.fixture
def relogio() -> RelogioControlado:
    return RelogioControlado(datetime(2026, 10, 8, 11, 0, tzinfo=UTC))


class Acesso:
    def __init__(self, engine: Engine, relogio: RelogioControlado) -> None:
        self.executar = montar_executor(engine, montar_barramento(relogio))
        auditoria, parametros = ServicoAuditoria(), ParametrosPadrao()
        self.auth = ServicoAutenticacao(self.executar, auditoria, parametros, relogio, HASHER)
        self.sessoes = GerenciadorSessao(self.executar, auditoria, parametros, relogio)


def sessoes_de(engine: Engine, usuario_id: int) -> list[tuple[object, ...]]:
    with engine.connect() as c:
        sql = "SELECT token_hash, motivo_encerramento FROM sessao_usuario WHERE usuario_id = :u ORDER BY id"
        return [tuple(linha) for linha in c.execute(text(sql), {"u": usuario_id})]


def motivo_ao_validar(acesso: Acesso, token: str, automatica: bool = False) -> str | None:
    with pytest.raises(SessaoEncerrada) as erro:
        acesso.sessoes.validar(token, "10.0.0.5", automatica)
    return erro.value.motivo


@pytest.mark.requisito("CT-ACE-07", "DD-05")
def test_token_gravado_so_como_hash(
    criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    uid = criar_usuario("sess_hash")
    aberta = Acesso(engine_web, relogio).auth.entrar("sess_hash", SENHA, "10.0.0.5")
    assert len(aberta.token) >= 43  # 256 bits em base64 sem preenchimento
    [(token_hash, _)] = sessoes_de(engine_web, uid)
    assert token_hash == hashlib.sha256(aberta.token.encode()).hexdigest()
    with engine_web.connect() as c:
        linha = c.execute(text("SELECT * FROM sessao_usuario WHERE usuario_id = :u"), {"u": uid}).one()
    assert aberta.token not in str(tuple(linha))


@pytest.mark.requisito("RF-1002", "DD-81")
def test_sessao_valida_devolve_o_contexto_da_requisicao(
    criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    uid = criar_usuario("sess_ok", perfil="enfermagem")
    acesso = Acesso(engine_web, relogio)
    aberta = acesso.auth.entrar("sess_ok", SENHA, "10.0.0.5")
    contexto = acesso.sessoes.validar(aberta.token, "10.0.0.7")
    assert (contexto.usuario_id, contexto.perfil, contexto.sessao_id) == (
        uid,
        Perfil.ENFERMAGEM,
        aberta.contexto.sessao_id,
    )
    assert contexto.origem == "10.0.0.7" and len(contexto.requisicao_id) == 32
    assert motivo_ao_validar(acesso, "token-que-nao-existe") is None


@pytest.mark.requisito("RNF-601", "CT-ACE-05", "DEC-63")
def test_nova_entrada_encerra_a_sessao_anterior_com_aviso(
    criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    uid = criar_usuario("sess_dupla")
    acesso = Acesso(engine_web, relogio)
    primeira = acesso.auth.entrar("sess_dupla", SENHA, "10.0.0.5")
    segunda = acesso.auth.entrar("sess_dupla", SENHA, "10.0.0.8")
    assert motivo_ao_validar(acesso, primeira.token) == "novo_login"  # a estação antiga mostra o aviso
    assert acesso.sessoes.validar(segunda.token, "10.0.0.8").usuario_id == uid
    assert [motivo for _, motivo in sessoes_de(engine_web, uid)] == ["novo_login", None]


@pytest.mark.requisito("RNF-601", "CT-ACE-05")
def test_entradas_simultaneas_deixam_uma_so_sessao_ativa(
    criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    uid = criar_usuario("sess_simultanea")
    acesso = Acesso(engine_web, relogio)
    with ThreadPoolExecutor(max_workers=4) as pool:
        abertas = list(pool.map(lambda _: acesso.auth.entrar("sess_simultanea", SENHA, "10.0.0.5"), range(4)))
    validas = []
    for aberta in abertas:
        with contextlib.suppress(SessaoEncerrada):  # as outras foram encerradas por novo_login
            validas.append(acesso.sessoes.validar(aberta.token, "10.0.0.5"))
    assert len(validas) == 1
    assert [motivo for _, motivo in sessoes_de(engine_web, uid)].count(None) == 1


@pytest.mark.requisito("RF-1003", "RNF-602", "CT-ACE-06", "QAS-09", "DD-19")
def test_inatividade_encerra_a_sessao(
    criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    criar_usuario("sess_inativa")
    acesso = Acesso(engine_web, relogio)
    token = acesso.auth.entrar("sess_inativa", SENHA, "10.0.0.5").token
    for _ in range(3):  # cada ação dentro do prazo renova a inatividade
        relogio.avancar(timedelta(minutes=9))
        acesso.sessoes.validar(token, "10.0.0.5")
    relogio.avancar(timedelta(minutes=10, seconds=1))
    assert motivo_ao_validar(acesso, token) == "inatividade"
    assert motivo_ao_validar(acesso, token) == "inatividade"  # continua encerrada


@pytest.mark.requisito("CT-ACE-06", "DD-19", "DD-57")
def test_requisicao_automatica_nao_renova_a_inatividade(
    criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    criar_usuario("sess_automatica")
    acesso = Acesso(engine_web, relogio)
    token = acesso.auth.entrar("sess_automatica", SENHA, "10.0.0.5").token
    for _ in range(9):  # a tela atualiza as contagens sozinha, minuto a minuto
        relogio.avancar(timedelta(minutes=1))
        acesso.sessoes.validar(token, "10.0.0.5", automatica=True)
    relogio.avancar(timedelta(minutes=1, seconds=1))
    assert motivo_ao_validar(acesso, token, automatica=True) == "inatividade"


@pytest.mark.requisito("DD-19")
def test_limite_absoluto_mesmo_com_uso_continuo(
    criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    criar_usuario("sess_limite")
    acesso = Acesso(engine_web, relogio)
    token = acesso.auth.entrar("sess_limite", SENHA, "10.0.0.5").token
    for _ in range(12 * 6):  # uma ação a cada 10 min por 12 h
        relogio.avancar(timedelta(minutes=10))
        acesso.sessoes.validar(token, "10.0.0.5")
    relogio.avancar(timedelta(minutes=5))
    assert motivo_ao_validar(acesso, token) == "limite"


@pytest.mark.requisito("RF-1002", "RNF-605")
def test_saida_encerra_e_e_auditada(
    criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    uid = criar_usuario("sess_saida")
    acesso = Acesso(engine_web, relogio)
    token = acesso.auth.entrar("sess_saida", SENHA, "10.0.0.5").token
    acesso.auth.sair(acesso.sessoes.validar(token, "10.0.0.5"))
    assert motivo_ao_validar(acesso, token) == "saida"
    with engine_web.connect() as c:
        sql = "SELECT operacao, motivo FROM auditoria WHERE usuario_id = :u ORDER BY id"
        assert [tuple(linha) for linha in c.execute(text(sql), {"u": uid})] == [
            ("acesso.sessao.entrar", None),
            ("acesso.sessao.sair", "saida"),
        ]


@pytest.mark.requisito("RF-1005", "DDS-3.11")
def test_inativacao_do_usuario_encerra_as_sessoes(
    criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    uid = criar_usuario("sess_evento")
    acesso = Acesso(engine_web, relogio)
    token = acesso.auth.entrar("sess_evento", SENHA, "10.0.0.5").token

    def inativar(uow: UnidadeDeTrabalho) -> None:  # o que o UsuarioService fará na etapa 6
        uow.publicar(UsuarioInativado(usuario_id=uid))

    acesso.executar(inativar)
    assert motivo_ao_validar(acesso, token) == "inativacao"


@pytest.mark.requisito("RF-1005")
def test_usuario_inativado_ou_com_perfil_alterado_vale_na_hora(
    criar_usuario: CriarUsuario, engine_web: Engine, trilha_zerada: Engine, relogio: RelogioControlado
) -> None:
    uid = criar_usuario("sess_mudanca")
    acesso = Acesso(engine_web, relogio)
    token = acesso.auth.entrar("sess_mudanca", SENHA, "10.0.0.5").token
    with trilha_zerada.begin() as c:
        c.execute(text("UPDATE usuario SET perfil = 'visualizador' WHERE id = :u"), {"u": uid})
    assert acesso.sessoes.validar(token, "10.0.0.5").perfil is Perfil.VISUALIZADOR
    with trilha_zerada.begin() as c:
        c.execute(text("UPDATE usuario SET ativo = 0 WHERE id = :u"), {"u": uid})
    assert motivo_ao_validar(acesso, token) == "inativacao"
