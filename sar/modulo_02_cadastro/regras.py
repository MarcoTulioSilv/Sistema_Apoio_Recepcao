"""Regras puras do MOD-02 (DDS §6.2, §6.3): sem banco, sem relógio, sem perfil. Quem chama passa a data de hoje.

Os códigos de RegraViolada levam o campo ou a invariante; a tela os traduz em mensagem. Nenhum carrega o valor
recusado no detalhe, porque o erro pode chegar ao log (RNF-624)."""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import fields, replace
from datetime import date
from enum import Enum

from sar.modulo_02_cadastro.contrato import DadosPaciente, Situacao, TipoCobertura, TipoEvento, TipoTelefone
from sar.nucleo.erros import RegraViolada

# Tamanhos das colunas de texto da 0001.
TAMANHOS = {
    "prontuario": 20, "nome": 150, "nome_mae": 150, "rg": 20, "rg_orgao": 20, "logradouro": 150, "numero": 10,
    "complemento": 60, "bairro": 80,
}  # fmt: skip
TAMANHO_LOCAL_EVENTO = 150
TAMANHO_CARTEIRINHA = 30
TAMANHO_NOME_CONTATO = 150
TAMANHO_PARENTESCO = 40
NASCIMENTO_MINIMO = date(1900, 1, 1)

# Campos que, vazios, viram pendência nomeada (RF-102, UC-01 A1). O complemento é opcional de verdade.
CAMPOS_DE_PENDENCIA = (
    "data_nascimento", "sexo", "nome_mae", "cpf", "cns", "rg", "rg_orgao", "naturalidade_municipio", "logradouro",
    "numero", "bairro", "municipio", "cep",
)  # fmt: skip
CEP_NAO_VERIFICADO = "cep_nao_verificado"

# DDDs em uso no Brasil (Anatel).
DDDS = frozenset(
    {11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 24, 27, 28, 31, 32, 33, 34, 35, 37, 38, 41, 42, 43, 44, 45, 46, 47,
     48, 49, 51, 53, 54, 55, 61, 62, 63, 64, 65, 66, 67, 68, 69, 71, 73, 74, 75, 77, 79, 81, 82, 83, 84, 85, 86, 87,
     88, 89, 91, 92, 93, 94, 95, 96, 97, 98, 99}
)  # fmt: skip

EVENTOS_COM_LOCAL = frozenset({TipoEvento.OBITO, TipoEvento.TRANSFERENCIA, TipoEvento.TRANSPLANTE})  # RF-602

_SEPARADORES = re.compile(r"[\s.\-/()]")
_CODIGO_IBGE = re.compile(r"^[0-9]{7}$")


# ------------------------------------------------------------------ texto e números
def texto(valor: str | None, campo: str, tamanho: int) -> str | None:
    """Sem espaços repetidos nem nas pontas; vazio vira None; acima do tamanho da coluna, RegraViolada."""
    if valor is None:
        return None
    limpo = " ".join(valor.split())
    if not limpo:
        return None
    if len(limpo) > tamanho:
        raise RegraViolada(f"{campo}.tamanho", {"maximo": tamanho})
    return limpo


def digitos(valor: str | None, codigo_erro: str) -> str | None:
    """Só os dígitos, aceitando a pontuação usual (ponto, hífen, barra, parênteses, espaço). Letra ou outro sinal
    no meio é erro (RegraViolada com o código dado), não algo a descartar em silêncio."""
    if valor is None:
        return None
    sem_separadores = _SEPARADORES.sub("", valor)
    if not sem_separadores:
        return None
    if not sem_separadores.isdigit() or not sem_separadores.isascii():
        raise RegraViolada(codigo_erro)
    return sem_separadores


def cpf_valido(cpf: str) -> bool:
    if len(cpf) != 11 or not (cpf.isascii() and cpf.isdigit()) or len(set(cpf)) == 1:
        return False
    numeros = [int(c) for c in cpf]
    for posicao in (9, 10):
        soma = sum(n * peso for n, peso in zip(numeros[:posicao], range(posicao + 1, 1, -1), strict=True))
        if numeros[posicao] != (soma * 10 % 11) % 10:
            return False
    return True


def cns_valido(cns: str) -> bool:
    """Cartão Nacional de Saúde (algoritmo do DATASUS). Definitivo começa por 1 ou 2 e é formado a partir de um
    PIS de 11 dígitos; provisório começa por 7, 8 ou 9 e só precisa da soma ponderada múltipla de 11."""
    if len(cns) != 15 or not (cns.isascii() and cns.isdigit()):
        return False
    if cns[0] in "12":
        pis = cns[:11]
        soma = sum(int(c) * (15 - i) for i, c in enumerate(pis))
        dv = 11 - soma % 11
        if dv == 11:
            dv = 0
        if dv == 10:
            dv = 11 - (soma + 2) % 11
            return cns == f"{pis}001{dv}"
        return cns == f"{pis}000{dv}"
    if cns[0] in "789":
        return sum(int(c) * (15 - i) for i, c in enumerate(cns)) % 11 == 0
    return False


def _codigo_ibge(valor: str | None, campo: str) -> str | None:
    if valor is None or not valor.strip():
        return None
    if not _CODIGO_IBGE.match(valor.strip()):
        raise RegraViolada(f"{campo}.invalido")
    return valor.strip()


# ------------------------------------------------------------------ paciente
def normalizar(dados: DadosPaciente, hoje: date) -> DadosPaciente:
    """Os dados como serão gravados: textos limpos, CPF, CNS e CEP só com dígitos. CPF ou CNS com dígito
    verificador inválido é recusado (DD-22); vazio passa e vira pendência."""
    cpf = digitos(dados.cpf, "cpf.invalido")
    if cpf is not None and not cpf_valido(cpf):
        raise RegraViolada("cpf.invalido")
    cns = digitos(dados.cns, "cns.invalido")
    if cns is not None and not cns_valido(cns):
        raise RegraViolada("cns.invalido")
    cep = digitos(dados.cep, "cep.invalido")
    if cep is not None and len(cep) != 8:
        raise RegraViolada("cep.invalido")
    nascimento = dados.data_nascimento
    if nascimento is not None and not NASCIMENTO_MINIMO <= nascimento <= hoje:
        raise RegraViolada("data_nascimento.invalida")

    def limpo(campo: str) -> str | None:
        return texto(getattr(dados, campo), campo, TAMANHOS[campo])

    return replace(
        dados,
        prontuario=limpo("prontuario"),
        nome=limpo("nome"),
        nome_mae=limpo("nome_mae"),
        cpf=cpf,
        cns=cns,
        rg=limpo("rg"),
        rg_orgao=limpo("rg_orgao"),
        naturalidade_municipio=_codigo_ibge(dados.naturalidade_municipio, "naturalidade_municipio"),
        logradouro=limpo("logradouro"),
        numero=limpo("numero"),
        complemento=limpo("complemento"),
        bairro=limpo("bairro"),
        municipio=_codigo_ibge(dados.municipio, "municipio"),
        cep=cep,
    )


def verificar_minimo(dados: DadosPaciente, inicio: date | None) -> None:
    """P-03: nome, prontuário e data de início. Sem eles, só rascunho (DEC-57)."""
    faltam = [
        campo
        for campo, valor in (("nome", dados.nome), ("prontuario", dados.prontuario), ("inicio", inicio))
        if valor is None
    ]
    if faltam:
        raise RegraViolada("P-03.minimo", {"faltam": faltam})


def verificar_inicio(inicio: date, nascimento: date | None) -> None:
    if nascimento is not None and inicio < nascimento:
        raise RegraViolada("inicio.antes_do_nascimento")


def pendencias(dados: DadosPaciente, cep_verificado: bool) -> tuple[str, ...]:
    """Campos faltantes, na ordem da ficha, e o CEP não verificado (RF-102, RF-109, QAS-03)."""
    faltantes = tuple(campo for campo in CAMPOS_DE_PENDENCIA if getattr(dados, campo) is None)
    if dados.cep is not None and not cep_verificado:
        return (*faltantes, CEP_NAO_VERIFICADO)
    return faltantes


def sem_acento(valor: str) -> str:
    decomposto = unicodedata.normalize("NFKD", valor)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def chave_triade(nome: str | None, nascimento: date | None, nome_mae: str | None) -> tuple[str, date, str] | None:
    """INV-08: comparação sem acento, sem caixa e sem espaços repetidos. Sem um dos três, a verificação não roda
    (fica adiada até a atualização que os completar)."""
    if nome is None or nascimento is None or nome_mae is None:
        return None
    return (
        " ".join(sem_acento(nome).casefold().split()),
        nascimento,
        " ".join(sem_acento(nome_mae).casefold().split()),
    )


def idade(nascimento: date, hoje: date) -> int:
    """RF-105: calculada na exibição, nunca gravada."""
    return hoje.year - nascimento.year - ((hoje.month, hoje.day) < (nascimento.month, nascimento.day))


def situacao(eventos_dos_periodos: Sequence[TipoEvento | None], alocado: bool) -> Situacao:
    """§6.3. Recebe o evento de cada período em ordem de início (None: período aberto); só o último decide,
    porque a INV-02 deixa no máximo um aberto e ele é sempre o mais recente."""
    if not eventos_dos_periodos:
        return Situacao.EM_CADASTRO
    ultimo = eventos_dos_periodos[-1]
    if ultimo is None:
        return Situacao.ATIVO if alocado else Situacao.SEM_ALOCACAO
    return Situacao.FALECIDO if ultimo is TipoEvento.OBITO else Situacao.INATIVO


def campos_alterados(antes: DadosPaciente, depois: DadosPaciente) -> dict[str, tuple[object, object]]:
    """Só o que mudou, para a auditoria (DD-10)."""
    alterados: dict[str, tuple[object, object]] = {}
    for campo in fields(DadosPaciente):
        velho, novo = getattr(antes, campo.name), getattr(depois, campo.name)
        if velho != novo:
            alterados[campo.name] = (_simples(velho), _simples(novo))
    return alterados


def _simples(valor: object) -> object:
    return valor.value if isinstance(valor, Enum) else valor


# ------------------------------------------------------------------ contatos e telefones (RF-201, RF-202)
def validar_contato(nome: str | None, parentesco: str | None) -> tuple[str, str | None]:
    limpo = texto(nome, "contato.nome", TAMANHO_NOME_CONTATO)
    if limpo is None:
        raise RegraViolada("contato.nome")
    return limpo, texto(parentesco, "contato.parentesco", TAMANHO_PARENTESCO)


def validar_telefone(ddd: str, numero: str, tipo: TipoTelefone) -> tuple[str, str]:
    """DDD em uso; celular com 9 dígitos começando por 9; fixo com 8 começando de 2 a 5; recado, qualquer um
    dos dois formatos."""
    ddd_limpo = digitos(ddd, "telefone.ddd")
    if ddd_limpo is None or len(ddd_limpo) != 2 or int(ddd_limpo) not in DDDS:
        raise RegraViolada("telefone.ddd")
    numero_limpo = digitos(numero, "telefone.numero")
    celular = numero_limpo is not None and len(numero_limpo) == 9 and numero_limpo[0] == "9"
    fixo = numero_limpo is not None and len(numero_limpo) == 8 and numero_limpo[0] in "2345"
    aceito = {TipoTelefone.CELULAR: celular, TipoTelefone.FIXO: fixo, TipoTelefone.RECADO: celular or fixo}[tipo]
    if not aceito or numero_limpo is None:
        raise RegraViolada("telefone.numero")
    return ddd_limpo, numero_limpo


# ------------------------------------------------------------------ períodos e coberturas
def verificar_abertura(inicio: date, ha_periodo_aberto: bool, fim_anterior: date | None, obito: date | None) -> None:
    """Novo período (RF-605): um aberto por vez (INV-02), nada depois do óbito (INV-01) e sem começar antes do
    evento que encerrou o anterior."""
    if obito is not None:
        raise RegraViolada("INV-01")
    if ha_periodo_aberto:
        raise RegraViolada("INV-02")
    if fim_anterior is not None and inicio < fim_anterior:
        raise RegraViolada("periodo.antes_do_fim_anterior")


def validar_cobertura(tipo: TipoCobertura, convenio_id: int | None, carteirinha: str | None) -> str | None:
    """SUS ou convênio nomeado (RF-301); carteirinha só no convênio. Devolve a carteirinha limpa."""
    if tipo is TipoCobertura.CONVENIO and convenio_id is None:
        raise RegraViolada("cobertura.convenio")
    if tipo is TipoCobertura.SUS and (convenio_id is not None or (carteirinha or "").strip()):
        raise RegraViolada("cobertura.sus_sem_convenio")
    return texto(carteirinha, "cobertura.carteirinha", TAMANHO_CARTEIRINHA)


def verificar_inicio_cobertura(
    inicio: date, periodo_inicio: date, periodo_fim: date | None, inicios_existentes: Sequence[date]
) -> None:
    """A cobertura vale de seu início até o início da seguinte (DD-70); dentro do período e sem início repetido,
    a INV-09 vale por construção."""
    if inicio < periodo_inicio:
        raise RegraViolada("cobertura.antes_do_periodo")
    if periodo_fim is not None and inicio > periodo_fim:
        raise RegraViolada("cobertura.depois_do_fim")
    if inicio in inicios_existentes:
        raise RegraViolada("INV-09")


def vigente_em(inicios: Sequence[date], data: date) -> int | None:
    """Índice, na lista ordenada de inícios, da cobertura que vale na data; None se a data é anterior a todas."""
    posicao = bisect_right(list(inicios), data)
    return posicao - 1 if posicao else None


# ------------------------------------------------------------------ evento (RF-601 a RF-604)
def validar_evento(
    tipo: TipoEvento,
    data: date,
    local: str | None,
    periodo_inicio: date,
    periodo_aberto: bool,
    obito: date | None,
    hoje: date,
) -> str | None:
    """Período aberto, data não anterior ao início, não futura, paciente não falecido (§6.2). O local só cabe no
    óbito, na transferência e no transplante (RF-602). Devolve o local limpo."""
    if obito is not None:
        raise RegraViolada("INV-01")
    if not periodo_aberto:
        raise RegraViolada("evento.periodo_encerrado")
    if data < periodo_inicio:
        raise RegraViolada("evento.antes_do_inicio")
    if data > hoje:
        raise RegraViolada("evento.data_futura")
    limpo = texto(local, "evento.local", TAMANHO_LOCAL_EVENTO)
    if limpo is not None and tipo not in EVENTOS_COM_LOCAL:
        raise RegraViolada("evento.local_nao_se_aplica")
    return limpo
