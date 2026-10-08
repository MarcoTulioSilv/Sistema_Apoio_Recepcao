"""Entrada no sistema no MySQL, pelo usuário de banco da web (DD-58): §5.2, DD-83, CT-ACE-04."""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Engine, text

from sar.composicao import montar_barramento, montar_executor
from sar.modulo_01_acesso.contrato import CredencialInvalida, TermoPendente, TrocaDeSenhaExigida
from sar.modulo_01_acesso.senhas import Hasher
from sar.modulo_01_acesso.servicos import ServicoAuditoria, ServicoAutenticacao
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import RegraViolada
from sar.nucleo.parametros import PARAMETROS
from testes.apoio.relogio_controlado import RelogioControlado
from testes.conftest import ZERAR_TRILHA

pytestmark = pytest.mark.integracao

SENHA = "cafe com leite"
HASHER = Hasher(custo=4)  # rápido nos testes; o custo 12 de produção é conferido no teste de unidade
HASH = HASHER.gerar(SENHA)

CriarUsuario = Callable[..., int]


class ParametrosPadrao:
    def valor(self, nome: str) -> int | bool | date | None:
        return PARAMETROS[nome].padrao  # 5 tentativas, 5 min, teto de 60 min


class HasherContado(Hasher):
    def __init__(self) -> None:
        super().__init__(custo=4)
        self.chamadas = 0

    def conferir(self, senha: str, senha_hash: str | None) -> bool:
        self.chamadas += 1
        return super().conferir(senha, senha_hash)


@pytest.fixture
def criar_usuario(trilha_zerada: Engine) -> Iterator[CriarUsuario]:
    criados: list[int] = []

    def criar(login: str, *, perfil: str = "recepcao", ativo: bool = True, termo: bool = True,
              trocar: bool = False, senha_hash: str = HASH) -> int:  # fmt: skip
        with trilha_zerada.begin() as c:
            c.execute(
                text(
                    "INSERT INTO usuario (nome, login, senha_hash, perfil, ativo, deve_trocar_senha, termo_ciencia_em,"
                    " criado_em) VALUES ('Marco Túlio Fictício', :l, :h, :p, :a, :t, IF(:termo, NOW(6), NULL), NOW(6))"
                ),
                {"l": login, "h": senha_hash, "p": perfil, "a": ativo, "t": trocar, "termo": termo},
            )
            criados.append(c.execute(text("SELECT id FROM usuario WHERE login = :l"), {"l": login}).scalar_one())
        return criados[-1]

    yield criar
    with trilha_zerada.begin() as c:
        for comando in ZERAR_TRILHA:
            c.execute(text(comando))
        for id_ in criados:
            c.execute(text("DELETE FROM usuario WHERE id = :u"), {"u": id_})


@pytest.fixture
def relogio() -> RelogioControlado:
    return RelogioControlado(datetime(2026, 10, 8, 11, 0, tzinfo=UTC))


def servico(engine: Engine, relogio: RelogioControlado, hasher: Hasher = HASHER) -> ServicoAutenticacao:
    executar = montar_executor(engine, montar_barramento(relogio))
    return ServicoAutenticacao(executar, ServicoAuditoria(), ParametrosPadrao(), relogio, hasher)


def trilha(engine: Engine) -> list[tuple[object, ...]]:
    with engine.connect() as c:
        sql = "SELECT operacao, usuario_id, entidade_id, motivo, alteracoes FROM auditoria ORDER BY id"
        return [tuple(linha) for linha in c.execute(text(sql))]


def estado(engine: Engine, usuario_id: int) -> tuple[object, ...]:
    with engine.connect() as c:
        sql = "SELECT tentativas_falhas, bloqueado_ate, deve_trocar_senha FROM usuario WHERE id = :u"
        return tuple(c.execute(text(sql), {"u": usuario_id}).one())


@pytest.mark.requisito("RF-1002", "RNF-605")
def test_entrada_com_senha_certa_e_auditada(
    criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    uid = criar_usuario("auth_ok", perfil="administracao")
    autenticado = servico(engine_web, relogio).entrar("auth_ok", SENHA, "10.0.0.5")
    assert (autenticado.usuario_id, autenticado.perfil) == (uid, Perfil.ADMINISTRACAO)
    assert trilha(engine_web) == [("acesso.sessao.entrar", uid, str(uid), None, None)]


@pytest.mark.requisito("RF-1002", "CT-ACE-04", "RNF-624")
def test_falhas_tem_a_mesma_mensagem_e_o_motivo_real_so_na_trilha(
    criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    criar_usuario("auth_inativo", ativo=False)
    criar_usuario("auth_errada")
    auth = servico(engine_web, relogio)
    erros = []
    for login, senha in (("login_digitado_xyz", SENHA), ("auth_inativo", SENHA), ("auth_errada", "outra senha")):
        with pytest.raises(CredencialInvalida) as erro:
            auth.entrar(login, senha, "10.0.0.5")
        erros.append((type(erro.value), str(erro.value)))
    assert len(set(erros)) == 1  # a tela não distingue os casos
    motivos = [linha[3] for linha in trilha(engine_web)]
    assert motivos == ["falha.login_inexistente", "falha.inativo", "falha.senha_incorreta"]
    assert trilha(engine_web)[0][1] is None  # login inexistente: sem usuário
    assert "login_digitado_xyz" not in str(trilha(engine_web))  # o que foi digitado não vai para a trilha


@pytest.mark.requisito("RNF-613", "CT-ACE-04", "QAS-09")
def test_bloqueio_progressivo_dobra_ate_o_teto_e_some_com_a_entrada_certa(
    criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    uid = criar_usuario("auth_bloqueio")
    auth = servico(engine_web, relogio)

    def errar() -> None:
        with pytest.raises(CredencialInvalida):
            auth.entrar("auth_bloqueio", "senha errada", "10.0.0.5")

    for _ in range(4):
        errar()
    assert estado(engine_web, uid)[:2] == (4, None)
    errar()  # 5ª falha: 5 minutos
    assert estado(engine_web, uid)[:2] == (5, (relogio.agora() + timedelta(minutes=5)).replace(tzinfo=None))
    with pytest.raises(CredencialInvalida):
        auth.entrar("auth_bloqueio", SENHA, "10.0.0.5")  # bloqueado: nem a senha certa entra
    assert estado(engine_web, uid)[0] == 5  # tentativa durante o bloqueio não conta
    for esperado in (10, 20, 40, 60, 60):  # dobra a cada nova falha, até o teto
        relogio.avancar(timedelta(minutes=60))
        errar()
        assert estado(engine_web, uid)[1] == (relogio.agora() + timedelta(minutes=esperado)).replace(tzinfo=None)
    relogio.avancar(timedelta(minutes=60))
    auth.entrar("auth_bloqueio", SENHA, "10.0.0.5")
    assert estado(engine_web, uid)[:2] == (0, None)


@pytest.mark.requisito("RNF-613")
def test_falhas_em_paralelo_nao_se_perdem(
    criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    uid = criar_usuario("auth_paralelo")
    auth = servico(engine_web, relogio)

    def errar(_: int) -> None:
        with pytest.raises(CredencialInvalida):
            auth.entrar("auth_paralelo", "senha errada", "10.0.0.5")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(errar, range(4)))
    assert estado(engine_web, uid)[0] == 4


@pytest.mark.requisito("DEC-47")
def test_sem_termo_de_ciencia_nao_entra(
    criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    criar_usuario("auth_termo", termo=False)
    with pytest.raises(TermoPendente):
        servico(engine_web, relogio).entrar("auth_termo", SENHA, "10.0.0.5")
    assert trilha(engine_web)[-1][3] == "falha.termo_pendente"


@pytest.mark.requisito("DD-83", "RNF-605")
def test_senha_provisoria_exige_troca_na_entrada(
    criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    uid = criar_usuario("auth_troca", trocar=True)
    auth = servico(engine_web, relogio)
    with pytest.raises(TrocaDeSenhaExigida):
        auth.entrar("auth_troca", SENHA, "10.0.0.5")
    with pytest.raises(RegraViolada) as erro:
        auth.entrar("auth_troca", SENHA, "10.0.0.5", nova_senha="marco1234")
    assert erro.value.codigo == "senha.contem_nome"
    with pytest.raises(RegraViolada) as erro:
        auth.entrar("auth_troca", SENHA, "10.0.0.5", nova_senha=SENHA)
    assert erro.value.codigo == "senha.igual_a_atual"

    auth.entrar("auth_troca", SENHA, "10.0.0.5", nova_senha="jabuticaba madura")
    assert estado(engine_web, uid)[2] == 0  # não precisa mais trocar
    with pytest.raises(CredencialInvalida):
        auth.entrar("auth_troca", SENHA, "10.0.0.5")  # a provisória deixou de valer
    auth.entrar("auth_troca", "jabuticaba madura", "10.0.0.5")
    troca = [linha for linha in trilha(engine_web) if linha[0] == "acesso.senha.trocar_propria"]
    assert troca == [("acesso.senha.trocar_propria", uid, str(uid), None, None)]  # sem valores


@pytest.mark.requisito("DD-83")
def test_troca_da_propria_senha_confere_a_atual(
    criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    uid = criar_usuario("auth_propria")
    auth = servico(engine_web, relogio)
    contexto = Contexto(uid, Perfil.RECEPCAO, None, "10.0.0.5", relogio.agora(), "e" * 32)
    with pytest.raises(CredencialInvalida):
        auth.trocar_propria_senha(contexto, "não é a atual", "jabuticaba madura")
    with pytest.raises(RegraViolada):
        auth.trocar_propria_senha(contexto, SENHA, "12345678")
    auth.trocar_propria_senha(contexto, SENHA, "jabuticaba madura")
    auth.entrar("auth_propria", "jabuticaba madura", "10.0.0.5")


@pytest.mark.requisito("CT-ACE-04")
def test_todo_caminho_faz_exatamente_uma_verificacao_de_senha(
    criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    criar_usuario("auth_um_inativo", ativo=False)
    criar_usuario("auth_um")
    contado = HasherContado()
    auth = servico(engine_web, relogio, contado)
    casos = [("nao_existe", SENHA), ("auth_um_inativo", SENHA), ("auth_um", "errada")] + [("auth_um", "x")] * 4
    for login, senha in casos:  # inexistente, inativo, errada e, por fim, bloqueado
        contado.chamadas = 0
        with pytest.raises(CredencialInvalida):
            auth.entrar(login, senha, "10.0.0.5")
        assert contado.chamadas == 1, login
    with pytest.raises(CredencialInvalida):
        auth.entrar("auth_um", SENHA, "10.0.0.5")  # bloqueado: a senha certa também é conferida


@pytest.mark.requisito("CT-ACE-04")
def test_tempo_de_resposta_igual_para_login_existente_e_inexistente(
    criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    """Com o custo 12 de produção, o bcrypt domina o tempo; a diferença das consultas fica no ruído."""
    real = Hasher()
    criar_usuario("auth_tempo", senha_hash=real.gerar(SENHA))
    auth = servico(engine_web, relogio, real)

    def medir(login: str) -> float:
        tempos = []
        for _ in range(3):
            inicio = time.perf_counter()
            with pytest.raises(CredencialInvalida):
                auth.entrar(login, "senha errada", "10.0.0.5")
            tempos.append(time.perf_counter() - inicio)
            relogio.avancar(timedelta(hours=2))  # evita entrar no bloqueio
        return statistics.median(tempos)

    existente, inexistente = medir("auth_tempo"), medir("nao_existe_tempo")
    assert 0.75 < existente / inexistente < 1.33
