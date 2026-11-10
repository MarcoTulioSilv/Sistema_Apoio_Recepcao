"""Catálogo de jobs (DDS §13.1). CT-JOB-01: um teste lê a tabela do DDS e compara com este catálogo.

As rotinas são dos módulos donos; a raiz de composição as liga pelo nome (`com_rotinas`), porque o MOD-01, o MOD-02
e o MOD-04 não podem importar o MOD-09 (DDS §3.12).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import timedelta

from sar.modulo_09_agendamento.contrato import Diaria, Domingo, Externa, Intervalo, Job, Rotina

H, D = timedelta(hours=1), timedelta(days=1)

CONSUMIDOR_FILA = "consumidor_fila"
BACKUP = "backup"
COPIA_PENDRIVE = "copia_pendrive"
OCUPACAO_DISCO = "ocupacao_disco"

CATALOGO: tuple[Job, ...] = (
    Job(CONSUMIDOR_FILA, "Consumidor da fila de ingestão", "MOD-04",
        Externa("Contínuo, a cada 2 s (DD-63)"), False, timedelta(minutes=5), False, False),
    Job("expiracao_ingestoes", "Expiração de ingestões e limpeza da quarentena", "MOD-04",
        Intervalo(15), False, H, True, True),
    Job("descarte_rascunhos", "Descarte de rascunhos vencidos", "MOD-02",
        Diaria(20, 30), False, 2 * D, True, True),
    Job("orfaos_repositorio", "Varredura de arquivos órfãos no repositório", "MOD-04",
        Diaria(2, 10), True, 2 * D, False, True),
    Job("verificacao_cadeia", "Verificação da cadeia de auditoria e registro da âncora", "MOD-01",
        Diaria(2, 0), True, 2 * D, True, True, fora_da_janela=True),
    Job("idade_assinaturas", "Idade das assinaturas do antimalware", "MOD-04",
        Intervalo(60), False, 3 * H, True, True),
    Job(OCUPACAO_DISCO, "Ocupação de disco", "MOD-09",
        Intervalo(60), False, 3 * H, True, True),
    Job(BACKUP, "Backup: dump e restic", "Servidor",
        Externa("Diário, 02:20, depois da âncora do dia", D), True, 2 * D, False, False),
    Job(COPIA_PENDRIVE, "Cópia para o pen drive", "Servidor",
        Externa("Semanal", 7 * D), False, 8 * D, False, False),
    Job("rescan_acervo", "Rescan antimalware do acervo", "MOD-04",
        Domingo(2, 30), True, 8 * D, False, True),
    Job("hash_acervo", "Conferência de hash de todo o acervo", "MOD-04",
        Domingo(2, 40, primeiro_do_mes=True), True, 35 * D, False, True),
    Job("expurgo_trilha", "Expurgo da trilha com mais de 5 anos", "MOD-01",
        Domingo(2, 50, primeiro_do_mes=True), True, 35 * D, False, False),
)  # fmt: skip

POR_NOME: dict[str, Job] = {job.nome: job for job in CATALOGO}
EXTERNOS = frozenset(job.nome for job in CATALOGO if isinstance(job.agenda, Externa))
REGISTRAVEIS = frozenset({BACKUP, COPIA_PENDRIVE})  # registrados pelos scripts do servidor (DD-62)


def com_rotinas(rotinas: Mapping[str, Rotina]) -> tuple[Job, ...]:
    """O catálogo com a rotina de cada job do worker. Falta ou sobra é erro de composição."""
    do_worker = {job.nome for job in CATALOGO if job.nome not in EXTERNOS}
    if set(rotinas) != do_worker:
        raise ValueError(
            f"rotinas faltando {sorted(do_worker - set(rotinas))}, sobrando {sorted(set(rotinas) - do_worker)}"
        )
    return tuple(replace(job, rotina=rotinas[job.nome]) if job.nome in rotinas else job for job in CATALOGO)
