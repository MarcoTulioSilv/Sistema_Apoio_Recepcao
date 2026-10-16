"""Apoio dos testes do MOD-03: as seis escalas da 0002 (DEC-52, P-14), instantes locais e os serviços com o banco."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy import Engine, text

from sar.modulo_01_acesso.servicos import ServicoAuditoria
from sar.modulo_03_operacao.calendario import Antecedencias
from sar.modulo_03_operacao.contrato import Escala
from sar.modulo_03_operacao.escalas import ServicoEscalas
from sar.modulo_06_configuracao.servicos import LeitorParametrosSQL
from sar.modulo_08_dados.relogio import FUSO_CLINICA
from sar.nucleo.contexto import Contexto, Perfil
from testes.apoio.cadastro import AGORA, Cadastro
from testes.apoio.cadastro import montar as montar_cadastro

ESCALAS = [
    Escala.de_texto(1, "1-seg", 1, "seg,qua,sex", time(6), time(10)),
    Escala.de_texto(2, "1-ter", 1, "ter,qui,sab", time(6), time(10)),
    Escala.de_texto(3, "2-seg", 2, "seg,qua,sex", time(11), time(15)),
    Escala.de_texto(4, "2-ter", 2, "ter,qui,sab", time(11), time(15)),
    Escala.de_texto(5, "3-seg", 3, "seg,qua,sex", time(16), time(20)),
    Escala.de_texto(6, "3-ter", 3, "ter,qui,sab", time(16), time(20)),
]
POR_CODIGO = {e.codigo: e for e in ESCALAS}
PADRAO = Antecedencias.em_minutos(60, 60)


def local(dia: date, hora: int, minuto: int = 0, segundo: int = 0) -> datetime:
    """Instante no fuso da clínica."""
    return datetime.combine(dia, time(hora, minuto, segundo), FUSO_CLINICA)


# ------------------------------------------------------------------ com o banco
@dataclass(frozen=True, slots=True)
class Operacao:
    cadastro: Cadastro
    escalas: ServicoEscalas
    parametros: LeitorParametrosSQL


def montar(engine: Engine) -> Operacao:
    """Como o compor() monta o MOD-03, sobre os serviços do cadastro de teste."""
    cadastro = montar_cadastro(engine)
    parametros = LeitorParametrosSQL(cadastro.executar)
    return Operacao(cadastro, ServicoEscalas(cadastro.executar, ServicoAuditoria(), cadastro.leitura, parametros),
                    parametros)  # fmt: skip


def definir_implantacao(engine: Engine, data: date | None, usuario_id: int) -> None:
    """Grava o parâmetro direto: definir pelo serviço exige um TI e é testado no MOD-06."""
    with engine.begin() as c:
        c.execute(text("DELETE FROM parametro WHERE nome = 'data_implantacao'"))
        if data is not None:
            c.execute(
                text("INSERT INTO parametro VALUES ('data_implantacao', :v, NOW(6), :u)"),
                {"v": data.isoformat(), "u": usuario_id},
            )


def confirmar_direto(engine: Engine, data: date, escala_id: int, usuario_id: int) -> None:
    """Sessão confirmada gravada direto, para as regras que dependem dela; a confirmação é testada no serviço."""
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO sessao_turno (data, escala_id, confirmada_em, confirmada_por) VALUES (:d, :e, NOW(6), :u)"
            ),
            {"d": data, "e": escala_id, "u": usuario_id},
        )


def contexto(usuarios: dict[str, int], chave: str, perfil: Perfil, instante: datetime = AGORA) -> Contexto:
    return Contexto(usuarios.get(chave), perfil, None, "10.0.0.7", instante, "c" * 32)
