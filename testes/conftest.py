"""Fixtures comuns. Os testes usam o banco sar_teste, nunca o da aplicação (sar): cada rodada zera a trilha.
Em desenvolvimento, os segredos ficam em segredos/ e o MySQL do compose na porta 3307; no CI, as variáveis vêm
do workflow."""

from __future__ import annotations

import logging
import os
import sys
import zlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from sar.modulo_08_dados.banco import ConfigBanco, criar_engine
from sar.nucleo.logs import RUIDOSOS
from testes.apoio.acesso import HASH, CriarUsuario
from testes.apoio.fabrica import VALORES_SENSIVEIS, Fabrica, PacienteFicticio
from testes.apoio.relogio_controlado import RelogioControlado
from testes.apoio.vazamento import ColetorLogs, EstadoLogging, vazamentos

RAIZ = Path(__file__).resolve().parent.parent
os.environ.setdefault("SAR_SEGREDOS", str(RAIZ / "segredos"))
os.environ.setdefault("SAR_BANCO_PORTA", "3307")
os.environ.setdefault("SAR_BANCO_NOME", "sar_teste")


@pytest.fixture
def relogio() -> RelogioControlado:
    """Quarta-feira, 30/09/2026, 09:15 em Jataí — a cena do protótipo."""
    return RelogioControlado(datetime(2026, 9, 30, 12, 15, tzinfo=UTC))


@pytest.fixture
def fabrica(request: pytest.FixtureRequest) -> Fabrica:
    """Semente derivada do nome do teste: dados reprodutíveis e independentes entre testes."""
    return Fabrica(zlib.crc32(request.node.nodeid.encode()))


@pytest.fixture(scope="session")
def engine_migracao() -> Iterator[Engine]:
    """Banco de teste já migrado, pelo usuário de migração (pode criar as tabelas de apoio dos testes)."""
    engine = criar_engine(ConfigBanco.do_ambiente("sar_migracao"))
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def engine_web() -> Iterator[Engine]:
    """O usuário de banco do processo web (DD-58), com os privilégios de produção."""
    engine = criar_engine(ConfigBanco.do_ambiente("sar_web"))
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def engine_worker() -> Iterator[Engine]:
    """O usuário de banco do worker (DD-58)."""
    engine = criar_engine(ConfigBanco.do_ambiente("sar_worker"))
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def engine_expurgo() -> Iterator[Engine]:
    """O usuário de banco do expurgo da trilha (DD-58)."""
    engine = criar_engine(ConfigBanco.do_ambiente("sar_expurgo"))
    yield engine
    engine.dispose()


ZERAR_TRILHA = (
    "DELETE FROM aviso_integridade",
    "DELETE FROM auditoria_ancora",
    "DELETE FROM auditoria_corte",
    "DELETE FROM auditoria",
    "UPDATE auditoria_cabeca SET ultimo_registro_id = 0, ultimo_hash = REPEAT('0', 64) WHERE id = 1",
)


# Operação (MOD-03), documentos (MOD-04) e cadastro (MOD-02), na ordem das chaves estrangeiras. A aplicação não
# apaga paciente; só os testes.
ZERAR_CADASTRO = (
    "DELETE FROM mes_alterado",
    "DELETE FROM ciencia_enfermagem",
    "DELETE FROM ligacao_manual",
    "DELETE FROM presenca",
    "DELETE FROM sessao_turno",
    "DELETE FROM termo_extra",
    "DELETE FROM extra_planejada",
    "DELETE FROM troca_pontual",
    "DELETE FROM alocacao",
    "DELETE FROM solicitacao_autorizacao",
    "DELETE FROM telefone",
    "DELETE FROM contato",
    "DELETE FROM cobertura",
    "DELETE FROM periodo_tratamento",
    "DELETE FROM ingestao",
    "UPDATE documento SET substitui_id = NULL",  # versões apontam umas para as outras
    "DELETE FROM documento",
    "DELETE FROM duplicidade_descartada",
    "DELETE FROM rascunho_cadastro",
    "DELETE FROM paciente",
    "DELETE FROM convenio",
)


@pytest.fixture
def trilha_zerada(engine_migracao: Engine) -> Iterator[Engine]:
    """Cadeia vazia no começo e no fim do teste. A aplicação nunca apaga a trilha; só o usuário de migração,
    no banco de teste."""
    with engine_migracao.begin() as c:
        for comando in ZERAR_TRILHA:
            c.execute(text(comando))
    yield engine_migracao
    with engine_migracao.begin() as c:
        for comando in ZERAR_TRILHA:
            c.execute(text(comando))


@pytest.fixture(autouse=True)
def sem_dado_de_paciente_nos_logs() -> Iterator[None]:
    """CT-LOG-01 (RNF-624, DD-81): todo teste roda com os logs capturados no formato de produção; o teste
    falha se algum valor sensível gerado pela fábrica aparecer neles. No fim, o logging volta ao que era, mesmo
    que o teste tenha rodado a linha de comando e trocado os handlers da raiz."""
    raiz = logging.getLogger()
    coletor = ColetorLogs()
    estado = EstadoLogging()
    raiz.addHandler(coletor)
    raiz.setLevel(logging.INFO)
    ruidosos = {nome: logging.getLogger(nome).level for nome in RUIDOSOS}
    for nome in RUIDOSOS:
        logging.getLogger(nome).setLevel(logging.WARNING)
    try:
        yield
    finally:
        estado.restaurar()
        for nome, nivel in ruidosos.items():
            logging.getLogger(nome).setLevel(nivel)
    achados = vazamentos(coletor.linhas, VALORES_SENSIVEIS)
    assert not achados, f"CT-LOG-01: dado fictício de paciente apareceu no log: {achados}"


@pytest.fixture
def usuarios(trilha_zerada: Engine) -> Iterator[dict[str, int]]:
    """Recepcionista (com uma sessão), administrador e TI, para os campos com chave estrangeira."""
    perfis = {"recepcao": "recepcao", "admin": "administracao", "ti": "ti"}
    ids: dict[str, int] = {}
    with trilha_zerada.begin() as c:
        for chave, perfil in perfis.items():
            c.execute(
                text(
                    "INSERT INTO usuario (nome, login, senha_hash, perfil, criado_em) "
                    "VALUES ('Usuário de teste', :l, REPEAT('x', 60), :p, NOW(6))"
                ),
                {"l": f"teste_{chave}", "p": perfil},
            )
            ids[chave] = c.execute(
                text("SELECT id FROM usuario WHERE login = :l"), {"l": f"teste_{chave}"}
            ).scalar_one()
        c.execute(
            text(
                "INSERT INTO sessao_usuario (token_hash, usuario_id, origem, criada_em, ultimo_acesso) "
                "VALUES (REPEAT('d', 64), :u, '10.0.0.5', NOW(6), NOW(6))"
            ),
            {"u": ids["recepcao"]},
        )
        ids["sessao"] = c.execute(
            text("SELECT id FROM sessao_usuario WHERE usuario_id = :u"), {"u": ids["recepcao"]}
        ).scalar_one()
    yield ids
    with trilha_zerada.begin() as c:
        for comando in ZERAR_TRILHA:  # a trilha aponta para os usuários: sai antes deles
            c.execute(text(comando))
        c.execute(text("DELETE FROM sessao_usuario WHERE id = :s"), {"s": ids["sessao"]})
        for chave in perfis:
            c.execute(text("DELETE FROM usuario WHERE id = :u"), {"u": ids[chave]})


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
            c.execute(text("DELETE FROM sessao_usuario WHERE usuario_id = :u"), {"u": id_})
            c.execute(text("DELETE FROM usuario WHERE id = :u"), {"u": id_})


@pytest.fixture
def cadastro_zerado(usuarios: dict[str, int], trilha_zerada: Engine) -> Iterator[dict[str, int]]:
    """Cadastro vazio no começo e no fim, com os usuários de teste; o cadastro sai antes deles."""
    with trilha_zerada.begin() as c:
        for comando in ZERAR_CADASTRO:
            c.execute(text(comando))
    yield usuarios
    with trilha_zerada.begin() as c:
        for comando in ZERAR_CADASTRO:
            c.execute(text(comando))


@pytest.fixture
def operacao_zerada(
    cadastro_zerado: dict[str, int], criar_usuario: CriarUsuario, trilha_zerada: Engine
) -> Iterator[dict[str, int]]:
    ids = dict(cadastro_zerado)
    ids["enfermagem"] = criar_usuario("teste_enfermagem", perfil="enfermagem")
    yield ids
    with trilha_zerada.begin() as c:  # antes dos usuários, que as sessões, ciências e parâmetros referenciam
        for comando in (*ZERAR_CADASTRO, "DELETE FROM parametro"):
            c.execute(text(comando))


# ------------------------------------------------------------------ extração (MOD-04)
@pytest.fixture
def tesseract_falso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PacienteFicticio:
    """Um "Tesseract" que devolve sempre o mesmo texto, com o CPF e o CNS do paciente fictício e uma frase que nunca
    pode ser guardada. Vale também para o subprocesso, que herda SAR_TESSERACT."""
    paciente = Fabrica(7).paciente()
    texto = f"Paciente {paciente.nome}\nCPF {paciente.cpf}\nCNS {paciente.cns}\nDIAGNOSTICO SIGILOSO\n"
    script = tmp_path / "tesseract_falso.py"
    script.write_text(f"import sys\nsys.stdin.buffer.read()\nsys.stdout.write({texto!r})\n", encoding="utf-8")
    if sys.platform == "win32":
        programa = tmp_path / "tesseract.cmd"
        programa.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        programa = tmp_path / "tesseract"
        programa.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        programa.chmod(0o755)
    monkeypatch.setenv("SAR_TESSERACT", str(programa))
    return paciente


@pytest.fixture
def sem_tesseract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SAR_TESSERACT", str(tmp_path / "nao-existe"))
