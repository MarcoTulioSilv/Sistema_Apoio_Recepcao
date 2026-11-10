"""Ciclo dos modelos .docx no MySQL e no conversor (DD-42, DD-103, §9.2): envio com validação e prévia, ativação,
reversão à versão 0 e auditoria com o hash."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, text

from sar.composicao import montar_barramento, montar_executor
from sar.modulo_01_acesso.servicos import ServicoAuditoria
from sar.modulo_05_emissao.contrato import Modelo
from sar.modulo_05_emissao.modelos import ServicoModelos, embutido
from sar.modulo_06_configuracao.servicos import ServicoReferencias
from sar.modulo_08_dados.relogio import RelogioSistema
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado, NaoEncontrado, RegraViolada
from testes.apoio.modelos import conversor_no_ar, no_texto, texto_do_pdf

pytestmark = pytest.mark.integracao

AGORA = datetime(2026, 11, 4, 13, 0, tzinfo=UTC)


@pytest.fixture
def modelos_limpos(usuarios: dict[str, int], engine_migracao: Engine) -> Iterator[dict[str, int]]:
    with engine_migracao.begin() as c:
        c.execute(text("DELETE FROM modelo_documento"))
    yield usuarios
    with engine_migracao.begin() as c:
        c.execute(text("DELETE FROM modelo_documento"))


@pytest.fixture
def servico(engine_web: Engine) -> ServicoModelos:
    executar = montar_executor(engine_web, montar_barramento(RelogioSistema()))
    return ServicoModelos(executar, ServicoAuditoria(), ServicoReferencias(), conversor_no_ar())


def pessoa(usuarios: dict[str, int], chave: str = "admin", perfil: Perfil = Perfil.ADMINISTRACAO) -> Contexto:
    return Contexto(usuarios[chave], perfil, None, "10.0.0.9", AGORA, "f" * 32)


def auditorias(engine: Engine) -> list[tuple[str, str, dict[str, list[object]]]]:
    sql = "SELECT operacao, entidade_id, alteracoes FROM auditoria WHERE operacao LIKE 'emissao.modelo.%' ORDER BY id"
    with engine.connect() as c:
        return [(o, e, json.loads(a)) for o, e, a in c.execute(text(sql))]


@pytest.mark.requisito("DD-103", "RNF-703")
def test_sem_envio_vale_a_versao_0_de_cada_modelo(modelos_limpos: dict[str, int], servico: ServicoModelos) -> None:
    resumos = servico.listar(pessoa(modelos_limpos))
    assert [r.modelo for r in resumos] == list(Modelo)
    for resumo in resumos:
        assert resumo.ativa == 0 and [v.versao for v in resumo.versoes] == [0]
        assert {"nome", "data_extenso", "codigo_integridade"} <= {v.nome for v in resumo.variaveis}
    assert servico.baixar(pessoa(modelos_limpos), Modelo.CRACHA) == embutido(Modelo.CRACHA)


@pytest.mark.requisito("DD-42", "DD-103", "RNF-703")
def test_envio_com_previa_ativacao_e_reversao_auditados(
    modelos_limpos: dict[str, int], servico: ServicoModelos, engine_web: Engine
) -> None:
    admin = pessoa(modelos_limpos)
    novo = no_texto("{{ nome }} (texto revisado)")
    envio = servico.enviar(admin, Modelo.CATETER, novo)
    assert envio.versao == 1 and envio.avisos == ()
    previa = texto_do_pdf(envio.previa)
    assert "MARIA APARECIDA EXEMPLO (TEXTO REVISADO)" in previa  # paciente fictício, em maiúsculas pelo modelo
    assert servico.baixar(admin, Modelo.CATETER) == embutido(Modelo.CATETER)  # enviada, ainda não ativa

    servico.ativar(admin, Modelo.CATETER, 1)
    servico.ativar(admin, Modelo.CATETER, 1)  # já ativa: nada muda
    assert servico.baixar(admin, Modelo.CATETER) == novo
    servico.ativar(admin, Modelo.CATETER, 0)  # reverter ao modelo inicial
    assert servico.baixar(admin, Modelo.CATETER) == embutido(Modelo.CATETER)
    assert [v.versao for v in servico.listar(admin)[0].versoes] == [1, 0]

    hash_novo, hash_inicial = hashlib.sha256(novo).hexdigest(), hashlib.sha256(embutido(Modelo.CATETER)).hexdigest()
    assert auditorias(engine_web) == [
        ("emissao.modelo.enviar", "DOC-02:1", {"hash_sha256": [None, hash_novo]}),
        ("emissao.modelo.ativar", "DOC-02", {"versao": [0, 1], "hash_sha256": [hash_inicial, hash_novo]}),
        ("emissao.modelo.reverter", "DOC-02", {"versao": [1, 0], "hash_sha256": [hash_novo, hash_inicial]}),
    ]


@pytest.mark.requisito("DD-42", "CT-EMI-01")
def test_envio_invalido_lista_os_problemas_e_nada_e_gravado(
    modelos_limpos: dict[str, int], servico: ServicoModelos
) -> None:
    admin = pessoa(modelos_limpos)
    with pytest.raises(RegraViolada) as erro:
        servico.enviar(admin, Modelo.CATETER, no_texto("{{ cpf }} {% for x in y %}{% endfor %}"))
    assert erro.value.codigo == "modelo.invalido"
    assert set(erro.value.detalhe["problemas"]) >= {("variavel.desconhecida", "cpf"), ("estrutura.proibida", "for")}
    assert [v.versao for v in servico.listar(admin)[0].versoes] == [0]


@pytest.mark.requisito("DD-42")
def test_versao_inexistente_nao_e_encontrada(modelos_limpos: dict[str, int], servico: ServicoModelos) -> None:
    admin = pessoa(modelos_limpos)
    with pytest.raises(NaoEncontrado):
        servico.ativar(admin, Modelo.TROCA, 9)
    with pytest.raises(NaoEncontrado):
        servico.baixar(admin, Modelo.TROCA, 9)


@pytest.mark.requisito("DD-42", "P-22")
@pytest.mark.parametrize(("chave", "perfil"), [("recepcao", Perfil.RECEPCAO), ("ti", Perfil.TI)])
def test_so_a_administracao_cuida_dos_modelos(
    modelos_limpos: dict[str, int], servico: ServicoModelos, chave: str, perfil: Perfil
) -> None:
    outro = pessoa(modelos_limpos, chave, perfil)
    with pytest.raises(AcessoNegado):
        servico.listar(outro)
    with pytest.raises(AcessoNegado):
        servico.enviar(outro, Modelo.CATETER, embutido(Modelo.CATETER))
    with pytest.raises(AcessoNegado):
        servico.ativar(outro, Modelo.CATETER, 0)
