"""Usuários pela tela do TI e pela linha de comando, no MySQL (DDS §5.1, §4.1, DD-85)."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, text

from sar.cli import main
from sar.composicao import montar_barramento, montar_executor
from sar.modulo_01_acesso.contrato import CredencialInvalida, SessaoEncerrada, TermoPendente, TrocaDeSenhaExigida
from sar.modulo_01_acesso.servicos import GerenciadorSessao, ServicoAuditoria, ServicoAutenticacao, ServicoUsuarios
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado, ConflitoDeVersao, RegraViolada
from testes.apoio.acesso import HASHER, SENHA, CriarUsuario, ParametrosPadrao
from testes.apoio.relogio_controlado import RelogioControlado
from testes.conftest import ZERAR_TRILHA

pytestmark = pytest.mark.integracao


@pytest.fixture
def relogio() -> RelogioControlado:
    return RelogioControlado(datetime(2026, 10, 8, 11, 0, tzinfo=UTC))


@pytest.fixture
def ti(criar_usuario: CriarUsuario, trilha_zerada: Engine, relogio: RelogioControlado) -> Iterator[Contexto]:
    """Um TI logado; no fim, apaga os usuários que os testes criaram (login usr_*)."""
    uid = criar_usuario("usr_ti_da_tela", perfil="ti")
    yield Contexto(uid, Perfil.TI, None, "10.0.0.9", relogio.agora(), "f" * 32)
    with trilha_zerada.begin() as c:
        for comando in ZERAR_TRILHA:
            c.execute(text(comando))
        criados = "SELECT id FROM usuario WHERE login LIKE 'usr%' AND login <> 'usr_ti_da_tela'"
        for (usuario_id,) in c.execute(text(criados)).all():
            c.execute(text("DELETE FROM sessao_usuario WHERE usuario_id = :u"), {"u": usuario_id})
            c.execute(text("DELETE FROM usuario WHERE id = :u"), {"u": usuario_id})


class Servicos:
    def __init__(self, engine: Engine, relogio: RelogioControlado) -> None:
        executar = montar_executor(engine, montar_barramento(relogio))
        auditoria, parametros = ServicoAuditoria(), ParametrosPadrao()
        self.usuarios = ServicoUsuarios(executar, auditoria, HASHER)
        self.auth = ServicoAutenticacao(executar, auditoria, parametros, relogio, HASHER)
        self.sessoes = GerenciadorSessao(executar, auditoria, parametros, relogio)


def versao(engine: Engine, usuario_id: int) -> int:
    with engine.connect() as c:
        return int(c.execute(text("SELECT versao FROM usuario WHERE id = :u"), {"u": usuario_id}).scalar_one())


def auditoria_de(engine: Engine, operacao: str) -> list[str | None]:
    with engine.connect() as c:
        sql = "SELECT alteracoes FROM auditoria WHERE operacao = :o ORDER BY id"
        return [linha[0] for linha in c.execute(text(sql), {"o": operacao})]


@pytest.mark.requisito("RF-1002", "DEC-47", "DD-83", "RNF-605")
def test_novo_usuario_entra_depois_do_termo_e_da_troca_de_senha(
    ti: Contexto, engine_web: Engine, relogio: RelogioControlado
) -> None:
    s = Servicos(engine_web, relogio)
    criado = s.usuarios.criar(ti, "Maria Souza Fictício", "usr_maria", Perfil.RECEPCAO)
    with pytest.raises(TermoPendente):
        s.auth.entrar("usr_maria", criado.senha_provisoria, "10.0.0.5")
    s.usuarios.registrar_termo(ti, criado.id, versao(engine_web, criado.id))
    with pytest.raises(TrocaDeSenhaExigida):
        s.auth.entrar("usr_maria", criado.senha_provisoria, "10.0.0.5")
    aberta = s.auth.entrar("usr_maria", criado.senha_provisoria, "10.0.0.5", nova_senha="jabuticaba madura")
    assert aberta.contexto.perfil is Perfil.RECEPCAO
    [criacao] = auditoria_de(engine_web, "acesso.usuario.criar")
    assert criacao is not None and '"login":[null,"usr_maria"]' in criacao
    assert criado.senha_provisoria not in str(criacao)


@pytest.mark.requisito("RF-1004", "CT-ACE-01")
def test_so_o_ti_administra_usuarios(
    ti: Contexto, criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    s = Servicos(engine_web, relogio)
    admin = Contexto(criar_usuario("usr_admin", perfil="administracao"), Perfil.ADMINISTRACAO, None, "10.0.0.9",
                     relogio.agora(), "f" * 32)  # fmt: skip
    with pytest.raises(AcessoNegado):
        s.usuarios.criar(admin, "Outro Fictício", "usr_outro", Perfil.RECEPCAO)
    with pytest.raises(AcessoNegado):
        s.usuarios.consultar(admin)
    resumo = next(u for u in s.usuarios.consultar(ti) if u.login == "usr_ti_da_tela")
    assert not hasattr(resumo, "senha_hash")


@pytest.mark.requisito("RF-1002")
def test_login_repetido_formato_e_perfil_sao_recusados(
    ti: Contexto, engine_web: Engine, relogio: RelogioControlado
) -> None:
    s = Servicos(engine_web, relogio)
    s.usuarios.criar(ti, "Ana Fictício", "usr_ana", Perfil.ENFERMAGEM)
    for login, perfil, codigo in (
        ("USR_ANA", Perfil.RECEPCAO, "usuario.login_repetido"),  # o login é guardado em minúsculas
        ("usr ana", Perfil.RECEPCAO, "usuario.login_formato"),
        ("usr_sistema", Perfil.SISTEMA, "usuario.perfil"),
    ):
        with pytest.raises(RegraViolada) as erro:
            s.usuarios.criar(ti, "Ana Fictício", login, perfil)
        assert erro.value.codigo == codigo


@pytest.mark.requisito("DD-17", "RNF-605")
def test_alteracao_de_perfil_com_versao_e_auditoria(
    ti: Contexto, engine_web: Engine, relogio: RelogioControlado
) -> None:
    s = Servicos(engine_web, relogio)
    uid = s.usuarios.criar(ti, "Rita Fictício", "usr_rita", Perfil.RECEPCAO).id
    antiga = versao(engine_web, uid)
    s.usuarios.alterar_perfil(ti, uid, antiga, Perfil.VISUALIZADOR)
    with pytest.raises(ConflitoDeVersao):
        s.usuarios.alterar_perfil(ti, uid, antiga, Perfil.ADMINISTRACAO)  # outra tela, com a versão velha
    with pytest.raises(RegraViolada):
        s.usuarios.alterar_perfil(ti, uid, versao(engine_web, uid), Perfil.VISUALIZADOR)
    assert auditoria_de(engine_web, "acesso.usuario.alterar_perfil") == ['{"perfil":["recepcao","visualizador"]}']


@pytest.mark.requisito("RF-1005", "DDS-3.11")
def test_inativar_encerra_a_sessao_e_reativar_devolve_o_acesso(
    ti: Contexto, criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    s = Servicos(engine_web, relogio)
    uid = criar_usuario("usr_jose")
    token = s.auth.entrar("usr_jose", SENHA, "10.0.0.5").token
    s.usuarios.inativar(ti, uid, versao(engine_web, uid))
    with pytest.raises(SessaoEncerrada) as erro:
        s.sessoes.validar(token, "10.0.0.5")
    assert erro.value.motivo == "inativacao"
    with pytest.raises(CredencialInvalida):
        s.auth.entrar("usr_jose", SENHA, "10.0.0.5")
    with pytest.raises(RegraViolada):
        s.usuarios.inativar(ti, uid, versao(engine_web, uid))
    s.usuarios.reativar(ti, uid, versao(engine_web, uid))
    s.auth.entrar("usr_jose", SENHA, "10.0.0.5")
    with engine_web.connect() as c:  # nunca excluído (RF-1005)
        assert c.execute(text("SELECT COUNT(*) FROM usuario WHERE id = :u"), {"u": uid}).scalar_one() == 1


@pytest.mark.requisito("DD-83", "RNF-613")
def test_redefinir_senha_desbloqueia_e_exige_troca_sem_gravar_a_senha_na_trilha(
    ti: Contexto, criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    s = Servicos(engine_web, relogio)
    uid = criar_usuario("usr_bia")
    for _ in range(5):
        with pytest.raises(CredencialInvalida):
            s.auth.entrar("usr_bia", "esqueci a senha", "10.0.0.5")
    provisoria = s.usuarios.redefinir_senha(ti, uid, versao(engine_web, uid))
    with pytest.raises(CredencialInvalida):
        s.auth.entrar("usr_bia", SENHA, "10.0.0.5")  # a antiga deixou de valer
    with pytest.raises(TrocaDeSenhaExigida):
        s.auth.entrar("usr_bia", provisoria, "10.0.0.5")  # e o bloqueio foi zerado
    [registro] = auditoria_de(engine_web, "acesso.usuario.redefinir_senha")
    assert registro == '{"deve_trocar_senha":[false,true]}'


@pytest.mark.requisito("DD-85", "DEC-47")
def test_linha_de_comando_cria_o_primeiro_ti_uma_vez(
    trilha_zerada: Engine, engine_web: Engine, capsys: pytest.CaptureFixture[str], relogio: RelogioControlado
) -> None:
    try:
        assert main(["criar-usuario-ti", "--nome", "Primeiro TI Fictício", "--login", "usr_ti_cli"]) == 1
        assert "--termo-assinado" in capsys.readouterr().err

        argumentos = ["criar-usuario-ti", "--nome", "Primeiro TI Fictício", "--login", "usr_ti_cli", "--termo-assinado"]
        assert main(argumentos) == 0
        provisoria = capsys.readouterr().out.strip().rsplit(" ", 1)[-1]
        with pytest.raises(TrocaDeSenhaExigida):  # termo já registrado: falta só trocar a senha
            Servicos(engine_web, relogio).auth.entrar("usr_ti_cli", provisoria, "10.0.0.5")

        argumentos[4] = "usr_ti_cli2"
        assert main(argumentos) == 1  # já existe TI ativo
        assert "usuario.ja_existe_ti_ativo" in capsys.readouterr().err
    finally:
        with trilha_zerada.begin() as c:
            for comando in ZERAR_TRILHA:
                c.execute(text(comando))
            dos_criados = "SELECT id FROM usuario WHERE login LIKE 'usr_ti_cli%'"
            c.execute(text(f"DELETE FROM sessao_usuario WHERE usuario_id IN ({dos_criados})"))  # noqa: S608
            c.execute(text("DELETE FROM usuario WHERE login LIKE 'usr_ti_cli%'"))


@pytest.mark.requisito("DD-85")
def test_superusuario_so_em_desenvolvimento(
    trilha_zerada: Engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    argumentos = ["criar-superusuario", "--nome", "Super Fictício", "--login", "usr_super"]
    try:
        monkeypatch.delenv("SAR_AMBIENTE", raising=False)  # padrão: produção
        assert main(argumentos) == 1
        assert "desenvolvimento" in capsys.readouterr().err
        monkeypatch.setenv("SAR_AMBIENTE", "desenvolvimento")
        assert main(argumentos) == 0
        assert "SAR_SUPERUSUARIOS" in capsys.readouterr().out
    finally:
        with trilha_zerada.begin() as c:
            for comando in ZERAR_TRILHA:
                c.execute(text(comando))
            c.execute(text("DELETE FROM usuario WHERE login = 'usr_super'"))


def ti_ativos(engine: Engine) -> int:
    with engine.connect() as c:
        return int(c.execute(text("SELECT COUNT(*) FROM usuario WHERE perfil = 'ti' AND ativo = 1")).scalar_one())


@pytest.mark.requisito("DD-87")
def test_ultimo_ti_ativo_nao_e_inativado_nem_muda_de_perfil(
    ti: Contexto, engine_web: Engine, relogio: RelogioControlado
) -> None:
    s = Servicos(engine_web, relogio)
    assert ti.usuario_id is not None and ti_ativos(engine_web) == 1
    for tentativa in (
        lambda: s.usuarios.inativar(ti, ti.usuario_id, versao(engine_web, ti.usuario_id)),
        lambda: s.usuarios.alterar_perfil(ti, ti.usuario_id, versao(engine_web, ti.usuario_id), Perfil.ADMINISTRACAO),
    ):
        with pytest.raises(RegraViolada) as erro:
            tentativa()
        assert erro.value.codigo == "usuario.ultimo_ti"
    s.usuarios.redefinir_senha(ti, ti.usuario_id, versao(engine_web, ti.usuario_id))  # a senha ainda pode
    assert ti_ativos(engine_web) == 1


@pytest.mark.requisito("DD-87")
def test_com_dois_ti_um_sai_e_o_outro_fica_protegido(
    ti: Contexto, criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    s = Servicos(engine_web, relogio)
    assert ti.usuario_id is not None
    inativo = criar_usuario("usr_ti_antigo", perfil="ti", ativo=False)  # TI inativo não conta
    outro = criar_usuario("usr_ti_novo", perfil="ti")
    s.usuarios.alterar_perfil(ti, outro, versao(engine_web, outro), Perfil.ADMINISTRACAO)
    with pytest.raises(RegraViolada):
        s.usuarios.inativar(ti, ti.usuario_id, versao(engine_web, ti.usuario_id))
    s.usuarios.reativar(ti, inativo, versao(engine_web, inativo))
    s.usuarios.inativar(ti, ti.usuario_id, versao(engine_web, ti.usuario_id))  # agora há outro TI ativo
    assert ti_ativos(engine_web) == 1


@pytest.mark.requisito("DD-87")
def test_dois_ti_inativando_um_ao_outro_ao_mesmo_tempo_deixam_um(
    ti: Contexto, criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    assert ti.usuario_id is not None
    outro_id = criar_usuario("usr_ti_par", perfil="ti")
    outro = Contexto(outro_id, Perfil.TI, None, "10.0.0.8", relogio.agora(), "e" * 32)
    pares = [(ti, outro_id, versao(engine_web, outro_id)), (outro, ti.usuario_id, versao(engine_web, ti.usuario_id))]

    def inativar(par: tuple[Contexto, int, int]) -> str:
        quem, alvo, versao_alvo = par
        try:
            Servicos(engine_web, relogio).usuarios.inativar(quem, alvo, versao_alvo)
        except RegraViolada as erro:
            return erro.codigo
        return "inativou"

    for _ in range(3):  # repete, para pegar as duas ordens de chegada
        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = sorted(pool.map(inativar, pares))
        assert resultados == ["inativou", "usuario.ultimo_ti"]
        assert ti_ativos(engine_web) == 1
        with engine_web.begin() as c:  # volta ao começo para a próxima rodada (só no banco de testes)
            c.execute(text("UPDATE usuario SET ativo = 1 WHERE login IN ('usr_ti_da_tela', 'usr_ti_par')"))
        pares = [(q, a, versao(engine_web, a)) for q, a, _ in pares]
