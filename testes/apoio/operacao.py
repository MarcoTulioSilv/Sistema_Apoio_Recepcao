"""Apoio dos testes do MOD-03: as seis escalas da 0002 (DEC-52, P-14), instantes locais e os serviços com o banco."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy import Engine, text

from sar.modulo_01_acesso.servicos import ServicoAuditoria, ServicoAutorizacoes
from sar.modulo_03_operacao.calendario import Antecedencias
from sar.modulo_03_operacao.contrato import Escala
from sar.modulo_03_operacao.escalas import ServicoEscalas
from sar.modulo_03_operacao.executores import executores as executores_operacao
from sar.modulo_03_operacao.frequencia import ServicoFrequencia
from sar.modulo_03_operacao.integracao import ParticipanteAnulacaoOperacao, VerificadorImpedimentoOperacao
from sar.modulo_03_operacao.sessoes import ServicoSessoes
from sar.modulo_06_configuracao.servicos import LeitorParametrosSQL
from sar.modulo_08_dados.relogio import FUSO_CLINICA, RelogioSistema
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
POR_ID = {e.id: e for e in ESCALAS}
PADRAO = Antecedencias.em_minutos(60, 60)


def local(dia: date, hora: int, minuto: int = 0, segundo: int = 0) -> datetime:
    """Instante no fuso da clínica."""
    return datetime.combine(dia, time(hora, minuto, segundo), FUSO_CLINICA)


# ------------------------------------------------------------------ com o banco
@dataclass(frozen=True, slots=True)
class Operacao:
    cadastro: Cadastro
    escalas: ServicoEscalas
    turnos: ServicoSessoes
    frequencia: ServicoFrequencia
    autorizacoes: ServicoAutorizacoes
    parametros: LeitorParametrosSQL


def montar(engine: Engine) -> Operacao:
    """Como o compor() monta o MOD-03, sobre os serviços do cadastro de teste: o verificador de impedimento e o
    participante da anulação entram nas listas que o cadastro usa."""
    cadastro = montar_cadastro(engine)
    parametros = LeitorParametrosSQL(cadastro.executar)
    auditoria = ServicoAuditoria()
    cadastro.verificadores.append(VerificadorImpedimentoOperacao(auditoria))
    cadastro.participantes.append(
        ParticipanteAnulacaoOperacao(auditoria, cadastro.leitura, parametros, RelogioSistema())
    )
    executores = {e.tipo: e for e in executores_operacao(auditoria, cadastro.leitura, parametros)}
    autorizacoes = ServicoAutorizacoes(cadastro.executar, auditoria, executores)
    executar, leitura = cadastro.executar, cadastro.leitura
    return Operacao(
        cadastro,
        ServicoEscalas(executar, auditoria, leitura, parametros, autorizacoes),
        ServicoSessoes(executar, auditoria, leitura, parametros, autorizacoes),
        ServicoFrequencia(executar, auditoria, leitura, parametros, autorizacoes),
        autorizacoes,
        parametros,
    )


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


def confirmar(op: Operacao, usuarios: dict[str, int], data: date, escala_id: int) -> None:
    """Pela confirmação de verdade, meia hora antes do fim do turno: ela grava a presença de todos (DD-24)."""
    fim = POR_ID[escala_id].fim
    quando = contexto(usuarios, "recepcao", Perfil.RECEPCAO, local(data, fim.hour - 1, 30))
    op.turnos.confirmar(quando, data, escala_id, op.turnos.tela_do_turno(quando, data, escala_id).versao)
