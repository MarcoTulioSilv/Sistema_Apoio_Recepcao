"""Como a ficha do paciente chama as coisas e traduz os códigos do MOD-02 e do MOD-01 (só apresentação)."""

from __future__ import annotations

from sar.modulo_02_cadastro.contrato import Situacao, TipoCobertura, TipoEvento, TipoTelefone

SITUACOES = {
    Situacao.EM_CADASTRO: "Em cadastro", Situacao.SEM_ALOCACAO: "Em tratamento, sem turno",
    Situacao.ATIVO: "Em tratamento", Situacao.INATIVO: "Inativo", Situacao.FALECIDO: "Falecido",
}  # fmt: skip
EVENTOS = {
    TipoEvento.OBITO: "Óbito", TipoEvento.ALTA: "Alta", TipoEvento.TRANSFERENCIA: "Transferência",
    TipoEvento.TRANSPLANTE: "Transplante", TipoEvento.DESISTENCIA: "Desistência",
}  # fmt: skip
EVENTOS_COM_LOCAL = {TipoEvento.OBITO: "Local do falecimento", TipoEvento.TRANSFERENCIA: "Unidade de destino",
                     TipoEvento.TRANSPLANTE: "Centro transplantador"}  # fmt: skip
COBERTURAS = {TipoCobertura.SUS: "SUS", TipoCobertura.CONVENIO: "Convênio"}
TELEFONES = {TipoTelefone.CELULAR: "Celular", TipoTelefone.FIXO: "Fixo", TipoTelefone.RECADO: "Recado"}
PENDENCIAS = {
    "data_nascimento": "data de nascimento", "sexo": "sexo", "nome_mae": "nome da mãe", "cpf": "CPF", "cns": "CNS",
    "rg": "RG", "rg_orgao": "órgão do RG", "naturalidade_municipio": "naturalidade", "logradouro": "logradouro",
    "numero": "número", "bairro": "bairro", "municipio": "município", "cep": "CEP",
}  # fmt: skip

# Códigos das ações da ficha (período, cobertura, evento, contato, autorização) → mensagem do aviso de erro.
ERROS_FICHA = {
    "INV-01": "O paciente faleceu: nada mais é registrado depois do óbito.",
    "INV-02": "O paciente já tem um período de tratamento aberto.",
    "INV-09": "Já existe cobertura começando nesta data. Escolha outra data.",
    "periodo.antes_do_fim_anterior": "O retorno não pode começar antes do encerramento do período anterior.",
    "periodo.inicio_repetido": "Já existe período começando nesta data.",
    "inicio.antes_do_nascimento": "A data é anterior ao nascimento do paciente.",
    "cobertura.antes_do_periodo": "A cobertura não pode começar antes do início do período.",
    "cobertura.depois_do_fim": "A cobertura não pode começar depois do encerramento do período.",
    "cobertura.convenio": "Escolha o convênio.",
    "cobertura.convenio_inativo": "Este convênio foi inativado. Escolha outro.",
    "cobertura.sus_sem_convenio": "Cobertura SUS não tem convênio nem carteirinha.",
    "evento.periodo_encerrado": "Não há período aberto para encerrar.",
    "evento.antes_do_inicio": "A data do evento é anterior ao início do período.",
    "evento.data_futura": "A data do evento não pode ser futura.",
    "evento.local_nao_se_aplica": "Local só no óbito, na transferência e no transplante.",
    "evento.local.tamanho": "Local com no máximo 150 caracteres.",
    "evento.impedimentos": "Há registros depois desta data. Corrija-os antes de registrar o evento.",
    "evento.inexistente": "Este período não tem evento.",
    "evento.nao_e_o_ultimo": "Só o evento do último período pode ser removido.",
    "evento.depois_do_periodo_seguinte": "A data passaria do início do período seguinte.",
    "duplicidade.sem_coincidencia": "Os dois cadastros não têm a mesma tríade.",
    "cep.ausente": "O cadastro não tem CEP.",
    "telefone.ddd": "DDD inválido.",
    "telefone.numero": "Celular tem 9 dígitos começando por 9; fixo tem 8, começando de 2 a 5.",
    "telefone.repetido": "Este número já está cadastrado para o mesmo dono.",
    "contato.nome": "Informe o nome do contato.",
    "contato.nome.tamanho": "Nome do contato com no máximo 150 caracteres.",
    "autorizacao.motivo_obrigatorio": "Explique o motivo do pedido, com até 500 caracteres.",
    "data.formato": "Informe uma data válida.",
}
