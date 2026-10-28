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
        ("pagina_tamanho_maximo", "Tamanho máximo por página recebida"),
        ("paginas_por_ingestao", "Páginas por digitalização"),
        ("pixels_por_pagina", "Pixels por página"),
        ("processamento_tempo_maximo", "Tempo máximo de processamento por página"),
        ("data_implantacao", "Data de implantação"),
    ]
)

UNIDADES = {
    "min": "minutos", "h": "horas", "dias": "dias", "qtd": "", "bool": "", "data": "", "MB": "MB", "s": "segundos",
    "mi": "milhões de pixels",
}  # fmt: skip
