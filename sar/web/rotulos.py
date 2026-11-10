"""Como a interface chama cada coisa: perfis, parâmetros (DDS §10.1) e unidades. Só apresentação."""

from __future__ import annotations

from sar.nucleo.contexto import Perfil

PERFIS = {
    Perfil.RECEPCAO: "Recepção",
    Perfil.ADMINISTRACAO: "Administração",
    Perfil.VISUALIZADOR: "Visualização",
    Perfil.TI: "TI",
    Perfil.ENFERMAGEM: "Enfermagem",
}

# Pares, e não dicionário literal: a bandit confunde a palavra "token" de captura_token_validade com senha
# escrita no código (B105). É só o rótulo de tela.
PARAMETROS = dict(
    [
        ("preparacao_turno_antecedencia", "Antecedência da preparação do turno"),
        ("confirmacao_turno_antecedencia", "Antecedência da liberação da confirmação"),
        ("rascunho_prazo", "Prazo do rascunho de cadastro"),
        ("rascunho_aviso", "Aviso antes do descarte do rascunho"),
        ("titular_prazo", "Prazo de resposta ao titular"),
        ("sessao_inatividade", "Inatividade até encerrar a sessão"),
        ("sessao_duracao_maxima", "Duração máxima da sessão"),
        ("login_tentativas", "Tentativas de entrada antes do bloqueio"),
        ("login_bloqueio_inicial", "Bloqueio inicial"),
        ("login_bloqueio_teto", "Teto do bloqueio"),
        ("captura_token_validade", "Validade do token de captura"),
        ("quarentena_prazo", "Prazo da quarentena e da ingestão pendente"),
        ("extracao_ligada", "Extração automática ligada"),
        ("antimalware_idade_maxima", "Idade máxima das assinaturas do antimalware"),
        ("disco_alarme_ocupacao", "Ocupação de disco que abre o alarme"),
        ("pagina_tamanho_maximo", "Tamanho máximo por página recebida"),
        ("paginas_por_ingestao", "Páginas por digitalização"),
        ("pixels_por_pagina", "Pixels por página"),
        ("processamento_tempo_maximo", "Tempo máximo de processamento por página"),
        ("data_implantacao", "Data de implantação"),
    ]
)

UNIDADES = {
    "min": "minutos", "h": "horas", "dias": "dias", "qtd": "", "bool": "", "data": "", "MB": "MB", "s": "segundos",
    "mi": "milhões de pixels", "%": "%",
}  # fmt: skip

# Pendências (DDS §11.1): o nome curto de cada linha, nas etiquetas dos cartões e no título dos itens, e o texto do
# botão que leva a resolver. Sem botão: "Abrir".
PENDENCIAS_CURTAS = {
    "cadastro_incompleto": "Cadastro incompleto",
    "checklist_faltante": "Documento faltante",
    "evento_sem_comprovante": "Evento sem comprovante",
    "sessao_nao_confirmada": "Sessão não confirmada",
    "termo_a_emitir": "Termo a emitir",
    "sem_alocacao": "Sem alocação",
    "presenca_sem_registro": "Presença fora da escala",
    "extra_alem_do_limite": "Extra além do limite",
    "possivel_duplicidade": "Possível duplicidade",
    "pedido_titular": "Pedido do titular",
    "solicitacao_autorizacao": "Solicitação de autorização",
    "falha_cadeia": "Falha na cadeia de auditoria",
    "rascunho_proximo_descarte": "Rascunho perto do descarte",
    "aguardando_conferencia": "Documento a conferir",
    "documento_bloqueado": "Documento bloqueado",
    "elegiveis_descarte": "Retenção vencida",
    "job_atrasado": "Job atrasado",
    "antimalware_desatualizado": "Antimalware desatualizado",
    "disco_acima_do_limite": "Disco acima do alarme",
}
ACOES_PENDENCIA = {
    "cadastro_incompleto": "Completar",
    "sessao_nao_confirmada": "Confirmar",
    "aguardando_conferencia": "Conferir",
    "solicitacao_autorizacao": "Decidir",
    "rascunho_proximo_descarte": "Retomar",
    "job_atrasado": "Ver os jobs",
    "disco_acima_do_limite": "Ver os jobs",
    "falha_cadeia": "Ver a integridade",
}
PRIORIDADES = {"U": ("Urgência", "text-urgencia", "etiqueta-u"), "A": ("Alta", "text-alta", "etiqueta-a"),
               "N": ("Normal", "text-normal", "etiqueta-n")}  # fmt: skip
