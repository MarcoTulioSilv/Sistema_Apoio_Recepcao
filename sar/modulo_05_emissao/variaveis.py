"""Lista fechada de variáveis de cada modelo .docx (DD-42, DDS §9.2), exibida na tela de envio, e os dados fictícios
da prévia. Uma variável fora da lista do documento é recusada no envio; a que falta no modelo só não aparece.

DOC-01 (DD-106), DOC-05 e DOC-06 (DEC-76) não têm modelo .docx.
"""

from __future__ import annotations

from sar.modulo_05_emissao.contrato import Modelo, Variavel

# RF-802, RF-803 e DD-86: em todo modelo.
COMUNS = (
    Variavel("clinica_nome", "Nome da clínica"),
    Variavel("clinica_endereco", "Endereço da clínica"),
    Variavel("clinica_cep", "CEP da clínica, como 75800-000"),
    Variavel("clinica_municipio", "Município da clínica"),
    Variavel("clinica_uf", "UF da clínica"),
    Variavel("clinica_telefone", "Telefone da clínica, como (64) 3600-0000"),
    Variavel("clinica_cnpj", "CNPJ da clínica"),
    Variavel("logotipo", "Logotipo da clínica, com 1,5 cm de altura", imagem=True),
    Variavel("data_extenso", "Município e data da emissão por extenso, como Jataí, 4 de novembro de 2026"),
    Variavel("codigo_integridade", "Código de integridade do rodapé"),
)

_NOME = Variavel("nome", "Nome do paciente")
_NASCIMENTO = Variavel("data_nascimento", "Data de nascimento, como 12/03/1961")
_MAE = Variavel("nome_mae", "Nome da mãe")

PROPRIAS: dict[Modelo, tuple[Variavel, ...]] = {
    Modelo.CATETER: (_NOME,),
    Modelo.TROCA: (
        _NOME,
        Variavel("data_origem", "Data da sessão que o paciente deixa, como 03/11/2026"),
        Variavel("turno_origem", "Turno que o paciente deixa: primeiro, segundo ou terceiro"),
        Variavel("data_destino", "Data da sessão em que o paciente vai dialisar"),
        Variavel("turno_destino", "Turno em que o paciente vai dialisar: primeiro, segundo ou terceiro"),
    ),
    Modelo.ALIMENTOS: (_NOME,),
    Modelo.EXTRA: (
        _NOME,
        _NASCIMENTO,
        _MAE,
        Variavel("turno", "Turno vigente do paciente: primeiro, segundo ou terceiro"),
    ),
    Modelo.CRACHA: (_NOME, _NASCIMENTO, _MAE, Variavel("foto", "Foto do paciente, 3 × 4 cm", imagem=True)),
}


def variaveis(modelo: Modelo) -> tuple[Variavel, ...]:
    return COMUNS + PROPRIAS[modelo]


def nomes(modelo: Modelo) -> frozenset[str]:
    return frozenset(v.nome for v in variaveis(modelo))


# Paciente fictício da prévia (DD-42): nunca dado real.
FICTICIOS: dict[str, str] = {
    "nome": "Maria Aparecida Exemplo",
    "data_nascimento": "12/03/1961",
    "nome_mae": "Joana Exemplo da Silva",
    "turno": "segundo",
    "data_origem": "03/11/2026",
    "turno_origem": "primeiro",
    "data_destino": "04/11/2026",
    "turno_destino": "terceiro",
}
