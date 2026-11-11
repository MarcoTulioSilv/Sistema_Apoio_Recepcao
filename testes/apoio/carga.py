"""Apoio dos testes da carga (MOD-10 e web): o serviço montado como no compor_carga e o contexto do TI. As fixtures
`carga` e `sinteticas` ficam no conftest da raiz."""

from __future__ import annotations

from sqlalchemy import Engine, text

from sar.composicao import SemCep, montar_barramento, montar_executor
from sar.modulo_01_acesso.servicos import ServicoAuditoria
from sar.modulo_02_cadastro.servicos import ServicoLeituraCadastro, ServicoPacientes
from sar.modulo_06_configuracao.servicos import ServicoReferencias
from sar.modulo_08_dados.cifra import CifraAesGcm
from sar.modulo_08_dados.relogio import RelogioSistema
from sar.modulo_10_carga.servicos import ServicoCarga
from sar.nucleo.contexto import Contexto, Perfil
from testes.apoio.cadastro import AGORA

CHAVE = bytes(range(32))


def sortear_os_primeiros(ids: list[int], quantos: int) -> list[int]:
    return sorted(ids)[:quantos]


def servico(engine: Engine) -> ServicoCarga:
    executar = montar_executor(engine, montar_barramento(RelogioSistema()))
    auditoria = ServicoAuditoria()
    referencias = ServicoReferencias()
    pacientes = ServicoPacientes(executar, auditoria, referencias, SemCep())
    leitura = ServicoLeituraCadastro()
    return ServicoCarga(
        executar, auditoria, pacientes, referencias, CifraAesGcm(CHAVE), pacientes, leitura, sortear_os_primeiros
    )


def ti(usuarios: dict[str, int]) -> Contexto:
    return Contexto(usuarios["ti"], Perfil.TI, None, "cli.carga", AGORA, "e" * 32)


def contar(engine: Engine, sql: str, **parametros: object) -> int:
    with engine.connect() as c:
        return int(c.execute(text(sql), parametros).scalar_one())
