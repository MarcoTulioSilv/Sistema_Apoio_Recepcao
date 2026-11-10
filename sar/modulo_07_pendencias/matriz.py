"""Matriz de pendências por perfil (ERS §3.2.13, DDS §11.1): a fonte única de quem vê cada linha, com que prioridade.

DD-55: um teste lê a tabela da ERS e a do DDS e compara com esta; divergência é falha. A ordem é a da matriz, e o
número de cada linha é o do DDS §11.1. A linha 20 foi retirada pela DEC-74 e o número não é reaproveitado.
"""

from __future__ import annotations

from dataclasses import dataclass

from sar.nucleo.contexto import Perfil
from sar.nucleo.portas import Prioridade

R, A, V, T, E = Perfil.RECEPCAO, Perfil.ADMINISTRACAO, Perfil.VISUALIZADOR, Perfil.TI, Perfil.ENFERMAGEM
U, AL, N = Prioridade.URGENCIA, Prioridade.ALTA, Prioridade.NORMAL


@dataclass(frozen=True, slots=True)
class LinhaMatriz:
    numero: int  # linha do DDS §11.1
    codigo: str  # o mesmo da FontePendencia
    nome: str
    perfis: frozenset[Perfil]
    prioridade: Prioridade
    variavel: bool = False  # a prioridade depende do item (linha 10: urgência a 3 dias do prazo)
    de_paciente: bool = True  # a fonte responde por paciente (§11.3)


def _linha(numero: int, codigo: str, nome: str, perfis: set[Perfil], prioridade: Prioridade, *,
           variavel: bool = False, de_paciente: bool = True) -> LinhaMatriz:  # fmt: skip
    return LinhaMatriz(numero, codigo, nome, frozenset(perfis), prioridade, variavel, de_paciente)


MATRIZ: tuple[LinhaMatriz, ...] = (
    _linha(1, "cadastro_incompleto", "Cadastro incompleto ou CEP não verificado", {R, A}, N),
    _linha(2, "checklist_faltante", "Documento do checklist faltante", {R, A}, N),
    _linha(3, "evento_sem_comprovante", "Evento sem documento comprobatório", {R, A}, AL),
    _linha(4, "sessao_nao_confirmada", "Sessão de turno não confirmada", {R, A}, U, de_paciente=False),
    _linha(5, "termo_a_emitir", "Termo a emitir e assinar", {R, A, E}, AL),
    _linha(6, "sem_alocacao", "Paciente sem alocação", {R, A, E}, AL),
    _linha(7, "presenca_sem_registro", "Presença fora da escala sem registro prévio", {E}, N),
    _linha(8, "extra_alem_do_limite", "Sessão extra além do limite mensal", {R, A, E}, N),
    _linha(9, "possivel_duplicidade", "Possível duplicidade pela tríade", {R, A}, N),
    _linha(10, "pedido_titular", "Pedido de titular", {R, A, V}, AL, variavel=True),
    _linha(11, "solicitacao_autorizacao", "Solicitação de autorização", {A}, AL),
    _linha(12, "falha_cadeia", "Falha na verificação da cadeia de auditoria", {A, T}, U, de_paciente=False),
    _linha(13, "rascunho_proximo_descarte", "Rascunho próximo do descarte", {R, A}, N, de_paciente=False),
    _linha(14, "aguardando_conferencia", "Documento capturado aguardando conferência", {R, A}, AL),
    _linha(15, "documento_bloqueado", "Documento bloqueado", {A, T}, U),
    _linha(16, "elegiveis_descarte", "Documentos elegíveis para descarte", {A}, N),
    _linha(17, "job_atrasado", "Job agendado que não rodou no horário", {T}, U, de_paciente=False),
    _linha(18, "antimalware_desatualizado", "Assinaturas do antimalware desatualizadas", {T}, U, de_paciente=False),
    _linha(19, "disco_acima_do_limite", "Ocupação de disco acima do limite", {T}, AL, de_paciente=False),
)

POR_CODIGO: dict[str, LinhaMatriz] = {linha.codigo: linha for linha in MATRIZ}


def visiveis(perfil: Perfil) -> tuple[LinhaMatriz, ...]:
    """As linhas que o perfil vê, na ordem da matriz."""
    return tuple(linha for linha in MATRIZ if perfil in linha.perfis)
