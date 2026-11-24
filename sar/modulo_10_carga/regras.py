"""Regras puras da carga inicial (DDS §14.1, DD-114): sem banco, sem arquivo, sem relógio.

A leitura da P1 parte do extrator de referência da fase 1 (docs/extrator_p1.py), que acertou 10 de 10 na amostra:
o mesmo dicionário de rótulos, a mesma separação das células compostas e a mesma regra do telefone (o rótulo vem
depois do número). O que mudou é o destino: aqui as regras devolvem códigos de aviso e de exceção, nunca o valor,
porque o relatório chega ao terminal do TI só como contagem (DD-65, RNF-624).

Planilhas (docs/fase1-especificacao-migracao.md):
- P1, endereços e telefones: a base (RN-04). Fichas de 9 linhas, rótulo na coluna A e valor na B.
- P4, entradas: só completa o que falta na P1 e confere CPF e CNS, pelo prontuário (RF-1102, DD-114); a ficha sem
  prontuário se liga pelo CPF ou pelo nome, se apontarem um prontuário só (DD-117).
- P3, eventos: só conferida, pelo nome (RF-1103); nenhum evento é gravado (RN-05).
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

Valor = str | date | None

INICIO_MINIMO = date(1990, 1, 1)  # ND-55: data de início fora da faixa plausível é erro de digitação
DDD_PRESUMIDO = "64"  # ND-47: Jataí e região; a presunção vira aviso, para a conferência saber
MAXIMO_AVISO = 40  # tamanho de excecao_codigo; os avisos usam os mesmos códigos


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def norm_rotulo(texto: object) -> str:
    """'CIDADE /CEP: ' → 'CIDADECEP': sem acento, sem pontuação, sem espaço, em maiúsculas."""
    if texto is None:
        return ""
    return re.sub(r"[^A-Z]", "", sem_acento(str(texto)).upper())


def norm_nome(texto: str) -> str:
    """Para casar nomes entre planilhas: sem acento, sem caixa, sem espaços repetidos."""
    return " ".join(sem_acento(texto).upper().split())


def _espacos(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def _digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto)


# ------------------------------------------------------------------ P1: rótulos (ND-49)
# Quando o rótulo não está no dicionário, um trecho dele decide, na ordem (visto no perfil da P1 real, 18/11/2026:
# "DATA DE NASCIMENTO", "DOC.PESSOAL", "CIDAE/CEP", "NASCIMENTO"). Rótulo longo é texto fora do lugar, não rótulo.
ROTULOS_POR_TRECHO = (
    ("MAE", "mae"), ("NOMEDA", "mae"), ("NASC", "nascimento"), ("INICIO", "inicio"), ("TRATAM", "inicio"),
    ("DATADE", "nascimento"),
    ("CEP", "cidade"), ("CIDADE", "cidade"), ("MUNIC", "cidade"), ("DOC", "documentos"), ("CPF", "documentos"),
    ("CONV", "convenio"), ("CNS", "convenio"), ("FONE", "telefone"), ("TEL", "telefone"), ("CEL", "telefone"),
    ("ENDER", "endereco"),
)  # fmt: skip
TAMANHO_MAXIMO_ROTULO = 24


def comeca_ficha(rotulo: object) -> bool:
    """A linha de rótulo iniciado por PACIENTE, logo depois da faixa preta, começa uma ficha (DD-114). O prontuário não
    entra na regra: há fichas sem número (visto no uso, 18/11/2026)."""
    return norm_rotulo(rotulo).startswith("PACIENTE")


def campo_do_rotulo(rotulo: object) -> str | None:
    """O campo da ficha a que o rótulo se refere: pelo dicionário e, se não estiver nele, por um trecho conhecido."""
    normalizado = norm_rotulo(rotulo)
    if normalizado in ROTULOS:
        return ROTULOS[normalizado]
    if not normalizado or len(normalizado) > TAMANHO_MAXIMO_ROTULO:
        return None
    if normalizado.startswith("END"):
        return "endereco"
    if normalizado.startswith("PACIENTE"):  # "PACIENTE NOME"; "CONTATO DO PACIENTE" não é (visto no uso)
        return "paciente"
    return next((campo for trecho, campo in ROTULOS_POR_TRECHO if trecho in normalizado), None)


SEM_FICHA = "p1.sem_ficha"  # bloco sem nenhum rótulo de ficha: título ou nota, contado à parte
ROTULOS = {
    "PACIENTE": "paciente",
    "NOMEDAMAE": "mae", "NOMEMAE": "mae",
    "DATADENASC": "nascimento", "DATANASC": "nascimento",
    "DATADEMASC": "nascimento",  # erro de digitação observado na amostra
    "ENDERECO": "endereco",
    "CIDADECEP": "cidade", "CIDADE": "cidade",
    "TELEFONE": "telefone",
    "DOCPESSOAIS": "documentos",
    "CONVENIO": "convenio",
    "INICIOTRATAM": "inicio",
}  # fmt: skip


@dataclass(frozen=True, slots=True)
class CelulaP1:
    linha: int
    rotulo: str  # como está na planilha
    valor: Valor


@dataclass(frozen=True, slots=True)
class BlocoP1:
    """Uma ficha: as linhas entre duas linhas vazias."""

    numero_linha: int  # a primeira linha da ficha
    celulas: tuple[CelulaP1, ...]


@dataclass(frozen=True, slots=True)
class TelefoneLido:
    ddd: str
    numero: str
    tipo: str  # celular, fixo, recado (os valores do TipoTelefone do MOD-02)
    contato: str | None  # None: telefone do próprio paciente
    parentesco: str | None  # já na lista fechada da DD-102, ou None


@dataclass(frozen=True, slots=True)
class RegistroP1:
    numero_linha: int
    prontuario: str | None = None  # texto, com os zeros à esquerda (ND-48)
    nome: str | None = None
    nome_mae: str | None = None
    nascimento: date | None = None
    cpf: str | None = None
    rg: str | None = None
    rg_orgao: str | None = None
    cns: str | None = None
    convenio: str | None = None  # "SUS" ou o nome do convênio
    inicio: date | None = None
    municipio_nome: str | None = None
    ibge: str | None = None  # 6 ou 7 dígitos, como na planilha
    cep: str | None = None
    logradouro: str | None = None
    numero: str | None = None
    complemento: str | None = None
    bairro: str | None = None
    telefones: tuple[TelefoneLido, ...] = ()
    cid_descartado: bool = False  # ND-45: o CID nunca é guardado; só contado
    avisos: tuple[str, ...] = ()
    excecao: str | None = None
    # Trechos de uma célula que a leitura não encaixou em campo nenhum, por campo da ficha. Só vão ao conteúdo cifrado
    # da linha, para a recepção ver na conferência; aos avisos vai só o código (p1.sobra_<campo>).
    sobras: tuple[tuple[str, str], ...] = ()


def _sobra(texto: str) -> str | None:
    """O que restou de uma célula, se ainda tiver letra ou número: pontuação e espaço não contam."""
    limpo = _espacos(re.sub(r"^[\s.,;:/()\-]+|[\s.,;:/()\-]+$", "", texto))
    return limpo if re.search(r"[0-9A-Za-zÀ-ÿ]", limpo) else None


# ------------------------------------------------------------------ datas (ND-55)
EPOCA_EXCEL = date(1899, 12, 30)  # o dia zero do Excel no Windows
SERIAL_MINIMO, SERIAL_MAXIMO = 10000, 73050  # de 18/05/1927 a 31/12/2099; um ano solto ("2015") não é serial
_DATA = re.compile(r"(\d{1,2})[/.\-]+(\d{1,2})[/.\-]+(\d{2,4})")


def ler_data(valor: Valor) -> date | None:
    """dd/mm/aaaa, a convenção da planilha (perfilamento §4.2); qualquer outra leitura é None, não palpite."""
    if isinstance(valor, date):
        return valor
    if not valor:
        return None
    serial = valor.strip().removesuffix(".0")
    if serial.isdigit() and SERIAL_MINIMO <= int(serial) <= SERIAL_MAXIMO:
        # Data gravada como número serial do Excel, numa célula sem formato de data (visto no uso: "43914").
        return EPOCA_EXCEL + timedelta(days=int(serial))
    achado = _DATA.search(valor)
    if achado is None:
        return None
    dia, mes, ano = (int(g) for g in achado.groups())
    if ano < 100:
        ano += 2000 if ano < 50 else 1900
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


# ------------------------------------------------------------------ células compostas
_MARCA_DO_NUMERO = re.compile(r"(?:\bN\s*[º°]|\bN[º°o]?\s*\.?\s*PT\b|\bPT\b|\bN\.)\s*[:.]?", re.I)
_PRONTUARIO = re.compile(r"(?:N\s*[ºo°]?\s*\.?\s*PT|(?<![A-Za-z])PT)\s*[:.]?\s*(\d+)", re.I)
_IBGE = re.compile(r"C[ÓO]?D[.:]?\s*(?:IBGE)?\s*[.:]?\s*(\d{6,7})", re.I)
_CEP = re.compile(r"CEP\s*[.:]?\s*([\d.\- ]{8,12})", re.I)
_UF = re.compile(r"[\s\-]+([A-Z]{2})$")
_CPF = re.compile(r"\b(\d{3}[.\s]?\d{3}[.\s]?\d{3}[-.\s]?\d{2})\b")
_RG = re.compile(r"RG\s*[.:]?\s*([\d.\-]+)", re.I)
_ORGAO = re.compile(r"(?:ORG[ÃÂA]?O?\.?\s*EXPEDIDOR\s*[.:]?)?\s*([A-Z]{2,6}\s*[-\s]?\s*[A-Z]{2})\s*$", re.I)
_CNS = re.compile(r"CNS\s*[.:;]?\s*([\d.\s]{15,25})", re.I)
_CNS_SOLTO = re.compile(r"(?<!\d)\d[\d.\s]{13,24}\d(?!\d)")  # "SUS 999.9999.9999.9999", sem o rótulo
_CID = re.compile(r"CID\s*[.:]?\s*N?[ºo°]?\s*[-:]?\s*([A-Z0-9.\-]*)", re.I)
_FONE = re.compile(r"(?:\(\s*\d{2}\s*\)\s*)?\d[\d\s.\-]{6,}\d")
_TIPOS_LOGRADOURO = r"(AV|AVENIDA|RUA|R|VIELA|TRAVESSA|TV|ALAMEDA|AL|PRACA|PRA[ÇC]A|ROD|RODOVIA)"
# Pedaços do complemento, na ordem da ficha. CASA entrou no uso com a P1 real (18/11/2026).
COMPLEMENTOS = (
    ("QD", r"\bQD\s*[.:]?\s*(\w+)"),
    ("LT", r"\bLT\s*[.:]?\s*(\w+)"),
    ("CASA", r"\bCASA\s*[.:]?\s*(\w+)"),
    ("AP", r"\bAP(?:TO)?\s*[.:]?\s*(\w+)"),
    ("BLOCO", r"\bBL(?:OCO)?\s*[.:]?\s*(\w+)"),
)
_FIM_DO_BAIRRO = r"\b(?:QD|LT|CASA|APTO|AP|BLOCO|BL)\b"
_BAIRRO = re.compile(r"\b(SETOR|CONJ\.?|CONJUNTO|RESIDENCIAL|JARDIM|BAIRRO|VILA)\b(.*)$", re.I)


class _Leitura:
    """Acumula os campos e os avisos de uma ficha."""

    def __init__(self, numero_linha: int) -> None:
        self.campos: dict[str, object] = {"numero_linha": numero_linha}
        self.avisos: list[str] = []
        self.sobras: list[tuple[str, str]] = []

    def aviso(self, codigo: str) -> None:
        self.avisos.append(codigo)

    def sobrou(self, campo: str, texto: str | None) -> None:
        if texto:
            self.sobras.append((campo, texto))
            self.aviso(f"p1.sobra_{campo}")

    def paciente(self, valor: str) -> None:
        """Nome não tem dígito: o número da linha é o prontuário, com ou sem "Nº PT", "N°", "PT" ou "-" antes (visto
        no uso, 18/11/2026: "NOME N° 0621", "NOME 782"). Com mais de um número, o rótulo PT decide; sem ele, nenhum
        vale, o nome fica até o primeiro número e o resto vira sobra."""
        achado = _PRONTUARIO.search(valor)
        if achado:
            self.campos["prontuario"] = achado.group(1)
            valor = valor[: achado.start()]
        else:
            numeros = list(re.finditer(r"\d+", valor))
            if len(numeros) == 1:
                self.campos["prontuario"] = numeros[0].group(0)
                valor = valor[: numeros[0].start()] + valor[numeros[0].end() :]
            elif numeros:
                self.aviso("p1.prontuario_ambiguo")
                self.sobrou("paciente", _sobra(valor[numeros[0].start() :]))
                valor = valor[: numeros[0].start()]
        self.campos["nome"] = _espacos(_MARCA_DO_NUMERO.sub(" ", valor)).strip(" -:/.,") or None

    def cidade(self, valor: str) -> None:
        achado = _IBGE.search(valor)
        if achado:
            self.campos["ibge"] = achado.group(1)
            valor = valor[: achado.start()] + valor[achado.end() :]
        else:
            self.aviso("ibge.ausente")
        achado = _CEP.search(valor)
        if achado:
            cep = _digitos(achado.group(1))
            if len(cep) != 8:
                self.aviso("cep.invalido")  # DD-68: malformado não entra
            else:
                self.campos["cep"] = cep
                if cep.endswith("000"):
                    self.aviso("cep.generico")  # RF-1105: genérico do município
            valor = valor[: achado.start()] + valor[achado.end() :]
        else:
            self.aviso("cep.ausente")
        nome = _espacos(valor).strip(" .:-/")
        uf = _UF.search(nome)
        if uf:
            nome = nome[: uf.start()]
        self.campos["municipio_nome"] = nome.strip(" -") or None

    def documentos(self, valor: str) -> None:
        cpfs = _CPF.findall(valor)
        if cpfs:
            self.campos["cpf"] = _digitos(cpfs[0])
            valor = valor.replace(cpfs[0], " ", 1)
        rg = _RG.search(valor)
        if rg:
            self.campos["rg"] = _digitos(rg.group(1)) or None
            valor = valor[: rg.start()] + valor[rg.end() :]
        orgao = _ORGAO.search(valor.strip())
        if orgao and self.campos.get("rg"):
            self.campos["rg_orgao"] = re.sub(r"\s+", "", orgao.group(1).upper())
            valor = valor.strip()[: orgao.start()]
        resto = re.sub(r"\b(?:CPF|RG|ORG[ÃÂA]?O?\.?\s*EXPEDIDOR)\b\s*[.:]?", " ", valor, flags=re.I)
        self.sobrou("documentos", _sobra(resto))
        if self.campos.get("rg") and self.campos.get("rg") == self.campos.get("cpf"):  # ND-36: é a CIN
            self.campos.pop("rg")
            self.campos.pop("rg_orgao", None)
            self.aviso("rg.igual_cpf")

    def convenio(self, valor: str) -> None:
        cns = _CNS.search(valor)
        if cns:
            self.campos["cns"] = _digitos(cns.group(1))
            valor = valor[: cns.start()] + valor[cns.end() :]
        else:  # sem o rótulo: a sequência de 15 dígitos é o CNS (visto no uso)
            solto = next((m for m in _CNS_SOLTO.finditer(valor) if len(_digitos(m.group(0))) == 15), None)
            if solto:
                self.campos["cns"] = _digitos(solto.group(0))
                valor = valor[: solto.start()] + valor[solto.end() :]
        fone = _FONE.search(valor)
        if fone:  # "SUS CNS: … (64) 9… PACIENTE": um telefone fora do lugar (visto no uso)
            self.telefone(valor[fone.start() :])
            valor = valor[: fone.start()]
            self.aviso("p1.telefone_fora_do_lugar")
        nome = re.match(r"[\s/:;]*([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .]*)", valor)
        self.campos["convenio"] = _espacos(nome.group(1)).strip(" .") if nome else None

    def _cns_em(self, valor: str) -> str:
        """O CNS escrito noutra célula (no início do tratamento, visto no uso): vale se a ficha ainda não tem."""
        achado = _CNS.search(valor) or next(
            (m for m in _CNS_SOLTO.finditer(valor) if len(_digitos(m.group(0))) == 15), None
        )
        if achado is None:
            return valor
        if not self.campos.get("cns"):
            self.campos["cns"] = _digitos(achado.group(1) if achado.re is _CNS else achado.group(0))
            self.aviso("p1.cns_fora_do_lugar")
        return valor[: achado.start()] + valor[achado.end() :]

    def inicio(self, valor: Valor) -> None:
        if isinstance(valor, str):
            valor = self._cns_em(valor)
            cid = _CID.search(valor)
            if cid:
                self.campos["cid_descartado"] = True  # ND-45: descartado na extração
                valor = valor[: cid.start()]
        data = ler_data(valor)
        if valor and data is None:
            self.aviso("inicio.invalido")
        self.campos["inicio"] = data

    def nascimento(self, valor: Valor) -> None:
        data = ler_data(valor)
        if valor and data is None:
            self.aviso("data_nascimento.invalida")
        self.campos["nascimento"] = data

    def endereco(self, valor: str) -> None:
        achados = 0
        tipo = re.match(r"^\s*" + _TIPOS_LOGRADOURO + r"\s*[:.]?\s*", valor, re.I)
        resto = valor[tipo.end() :] if tipo else valor
        partes = [(rotulo, re.search(padrao, resto, re.I)) for rotulo, padrao in COMPLEMENTOS]
        achadas = [(rotulo, m) for rotulo, m in partes if m]
        complemento = " ".join(f"{r} {m.group(1)}" for r, m in achadas)
        if complemento:
            self.campos["complemento"] = complemento
            achados += 1
        if re.search(r"\bS/?N\b", resto, re.I):
            self.campos["numero"] = "S/N"
            achados += 1
        else:
            numero = re.search(r"\bN[ºo°.]?\s*[:.]?\s*(\d+)", resto, re.I)
            if numero:
                self.campos["numero"] = numero.group(1)
                achados += 1
        bairro = _BAIRRO.search(resto)
        if bairro:
            limpo = re.split(_FIM_DO_BAIRRO, bairro.group(0), flags=re.I)[0]
            self.campos["bairro"] = _espacos(limpo).strip(" .:-") or None
            achados += 1
        corte = len(resto)
        for padrao in (r"\bN[ºo°.]?\s*[:.]?\s*\d", r"\bS/?N\b", *(c for _, c in COMPLEMENTOS),
                       r"\b(?:SETOR|CONJ|CONJUNTO|RESIDENCIAL|JARDIM|BAIRRO|VILA)\b"):  # fmt: skip
            marca = re.search(padrao, resto, re.I)
            if marca:
                corte = min(corte, marca.start())
        nome = _espacos(resto[:corte]).strip(" .:,-")
        if nome:
            self.campos["logradouro"] = f"{tipo.group(1).upper()} {nome}" if tipo else nome
            achados += 1
        if achados < 3 or not nome:
            self.aviso("endereco.incompleto")  # perfilamento §5.2: 20% a 30% precisam de revisão
        # O que ficou fora do logradouro, do número, da quadra, do lote e do bairro vai à conferência como sobra.
        numero_achado = re.search(r"\bS/?N\b|\bN[ºo°.]?\s*[:.]?\s*\d+", resto, re.I)
        usados = [(0, corte)] + [m.span() for _, m in achadas] + ([numero_achado.span()] if numero_achado else [])
        if bairro:
            sem_quadra = re.split(_FIM_DO_BAIRRO, bairro.group(0), flags=re.I)[0]
            usados.append((bairro.start(), bairro.start() + len(sem_quadra)))
        if not bairro and len(usados) > 1:
            final = max(b for _, b in usados)
            presumido = _sobra(resto[final:])
            if presumido:
                self.campos["bairro"] = presumido
                self.aviso("endereco.bairro_presumido")
                usados.append((final, len(resto)))
        sobra = "".join(" " if any(a <= i < b for a, b in usados) else c for i, c in enumerate(resto))
        self.sobrou("endereco", _sobra(sobra))

    def telefone(self, valor: str) -> None:
        telefones = list(self.campos.get("telefones", ()))  # type: ignore[call-overload]
        telefones.extend(ler_telefones(valor, self.avisos, self.sobras))
        self.campos["telefones"] = tuple(telefones)


# ------------------------------------------------------------------ telefones e contatos (ND-44, DD-102)
PARENTESCOS = {
    "Cônjuge": ("ESPOSA", "ESPOSO", "MARIDO", "MULHER", "COMPANHEIRA", "COMPANHEIRO", "CONJUGE"),
    "Filho ou filha": ("FILHA", "FILHO"),
    "Pai ou mãe": ("MAE", "PAI"),
    "Irmão ou irmã": ("IRMA", "IRMAO"),
    "Outro parente": ("NETA", "NETO", "SOBRINHA", "SOBRINHO", "TIA", "TIO", "PRIMA", "PRIMO", "PADRASTO",
                      "MADRASTA", "GENRO", "NORA", "CUNHADA", "CUNHADO", "AVO", "SOGRA", "SOGRO", "ENTEADA",
                      "ENTEADO", "NETOS", "FILHOS"),
    "Vizinho ou amigo": ("VIZINHA", "VIZINHO", "AMIGA", "AMIGO"),
}  # fmt: skip
_PARENTESCO_POR_PALAVRA = {palavra: grau for grau, palavras in PARENTESCOS.items() for palavra in palavras}
# Rótulos que dizem de quem ou de onde é o número, não quem atende: o telefone fica com o paciente.
PROPRIOS = frozenset({"PACIENTE", "PESSOA", "RESIDENCIA", "FAZENDA", "CASA", "PROPRIO", "DELE", "DELA", "TRABALHO",
                      "CELULAR", "FIXO", "RECADO", "RES", "CEL"})  # fmt: skip


def parentesco(texto: str) -> str | None:
    return _PARENTESCO_POR_PALAVRA.get(norm_rotulo(texto))


def _rotulo(texto: str) -> tuple[str | None, str | None, str | None, bool]:
    """'MARIA (esposa)' → ('MARIA', 'Cônjuge', None, False); devolve também o aviso e se é recado."""
    texto = texto.strip(" /,;-")
    grau_texto: str | None = None
    entre = re.search(r"\(([^)]*)\)", texto)
    if entre:
        grau_texto = entre.group(1)
        texto = (texto[: entre.start()] + texto[entre.end() :]).strip(" /,;-")
        dentro = grau_texto.split()
        grau_dentro = next((p for p in dentro if parentesco(p) is not None), None)
        if len(dentro) > 1 and grau_dentro is not None:  # "(MARIA ESPOSA)": nome e parentesco dentro
            texto = texto or " ".join(p for p in dentro if p != grau_dentro)
            grau_texto = grau_dentro
        elif grau_dentro is None and not texto:  # "(MARIA-JOSE)" sozinho: é o nome
            texto, grau_texto = grau_texto, None
    palavras = texto.split()
    if grau_texto is None and palavras and parentesco(palavras[0]) is not None:  # "ESPOSA NOME", visto no uso
        grau_texto, palavras = palavras[0], palavras[1:]
    elif grau_texto is None and palavras and parentesco(palavras[-1]) is not None:  # "NOME ESPOSA"
        grau_texto, palavras = palavras[-1], palavras[:-1]
    nome = " ".join(palavras).strip(" .:") or None
    if nome is not None and norm_rotulo(nome) in PROPRIOS:
        return None, None, None, norm_rotulo(nome) == "RECADO"
    grau = parentesco(grau_texto) if grau_texto else None
    aviso = "contato.parentesco_desconhecido" if grau_texto and grau is None and nome else None
    if nome is None and grau_texto:
        # "(64) 9... ESPOSA": o número é da esposa, sem o nome. Vira contato com o parentesco, chamado pelo que está
        # escrito, e o aviso pede o nome à recepção (visto no uso).
        return grau_texto.strip(" .:").upper(), grau, "contato.sem_nome", False
    return nome, grau, aviso, False


def ler_telefones(valor: str, avisos: list[str], sobras: list[tuple[str, str]] | None = None) -> list[TelefoneLido]:
    """Em geral o rótulo de cada número é o texto que vem DEPOIS dele (perfilamento §5.1): a leitura pelo texto anterior
    passou sem erro e trocou os contatos. Quando a célula começa com texto e termina num número, é o contrário. Número
    curto demais é ignorado; DDD ausente é presumido, com aviso."""
    numeros: list[tuple[str, int, int]] = []
    for achado in _FONE.finditer(valor):
        digitos = _digitos(achado.group(0))
        if len(digitos) >= 8:
            numeros.append((digitos, achado.start(), achado.end()))
    if not numeros and valor.strip():
        avisos.append("telefone.nenhum")
    antes = _sobra(valor[: numeros[0][1]]) if numeros else None
    depois = _sobra(valor[numeros[-1][2] :]) if numeros else None
    # A célula que começa com texto e termina num número tem o rótulo ANTES de cada número ("PACIENTE 64 9... FULANO
    # IRMAO 64 9..."), visto no uso; nas outras, o rótulo vem depois (perfilamento §5.1).
    rotulo_antes = bool(antes) and not depois
    if antes and not rotulo_antes and norm_rotulo(antes) not in PROPRIOS and sobras is not None:
        sobras.append(("telefone", antes))
        avisos.append("p1.sobra_telefone")
    lidos: list[TelefoneLido] = []
    for i, (digitos, inicio, fim) in enumerate(numeros):
        if rotulo_antes:
            trecho = valor[numeros[i - 1][2] if i else 0 : inicio]
        else:
            trecho = valor[fim : numeros[i + 1][1] if i + 1 < len(numeros) else len(valor)]
        contato, grau, aviso, recado = _rotulo(trecho)
        if aviso:
            avisos.append(aviso)
        if digitos.startswith("0") and len(digitos) in (11, 12):  # "064 99999999": o zero da operadora antiga
            digitos = digitos[1:]
        if len(digitos) in (8, 9):
            ddd, numero = DDD_PRESUMIDO, digitos
            avisos.append("telefone.ddd_presumido")
        elif len(digitos) in (10, 11):
            ddd, numero = digitos[:2], digitos[2:]
        else:
            avisos.append("telefone.numero")
            continue
        if len(numero) == 8 and numero[0] in "6789":  # celular de antes do nono dígito: presumido, com aviso
            numero = "9" + numero
            avisos.append("telefone.nono_digito")
        tipo = "recado" if recado or contato else ("celular" if len(numero) == 9 else "fixo")
        lidos.append(TelefoneLido(ddd, numero, tipo, contato, grau))
    return lidos


# ------------------------------------------------------------------ P1: ficha → registro
def interpretar_p1(bloco: BlocoP1, tolerante: bool = False) -> RegistroP1:
    """Rótulo desconhecido ou repetido não é adivinhado: a ficha inteira vai às exceções (ND-49). Tolerante (só para o
    cadastro pela tela, DD-118), o rótulo repetido sem campo que falte vira trecho que não entrou, e a leitura segue:
    quem decide é a recepção, olhando a ficha."""
    if not any(campo_do_rotulo(c.rotulo) for c in bloco.celulas):
        # Um título ou uma nota entre as fichas (visto no uso): não é paciente nem exceção; é contado à parte (RNF-103).
        return RegistroP1(bloco.numero_linha, excecao=SEM_FICHA)
    leitura = _Leitura(bloco.numero_linha)
    vistos: set[str] = set()
    reconhecidos = 0
    celulas = _com_continuacoes(bloco.celulas, leitura)
    rotulados = {campo_do_rotulo(c.rotulo) for c in celulas}
    for posicao, celula in enumerate(celulas):
        campo = campo_do_rotulo(celula.rotulo)
        if campo is not None and campo in vistos and campo != "telefone":
            # A planilha é feita à mão copiando a ficha de cima: o rótulo repetido ("PACIENTE:" na linha da cidade,
            # "CONVENIO:" na do início; visto no uso, 18/11/2026) lê o campo que falta na ficha.
            trocado = _campo_pela_posicao(posicao, rotulados, vistos, celula.valor)
            if trocado is None and not tolerante:
                return RegistroP1(bloco.numero_linha, excecao="p1.rotulo_repetido")
            if trocado is None:
                repetida = " · ".join(str(v) for v in (celula.rotulo, celula.valor) if v not in (None, ""))
                leitura.sobrou("linha", _sobra(repetida))
                continue
            campo = trocado
            leitura.aviso("p1.rotulo_trocado")
        if campo is None:
            if not norm_rotulo(celula.rotulo) and celula.valor in (None, ""):
                continue
            # Linha que não é da ficha (um endereço solto na coluna do rótulo, visto no uso): não derruba a ficha.
            # Fica à vista, como trecho que não entrou e com aviso, e marcada na conferência (ND-49: falha explícita).
            estranha = " · ".join(str(v) for v in (celula.rotulo, celula.valor) if v not in (None, ""))
            leitura.sobrou("linha", _sobra(estranha))
            leitura.aviso("p1.linha_nao_reconhecida")
            continue
        vistos.add(campo)
        reconhecidos += 1
        valor = celula.valor
        texto = _espacos(valor) if isinstance(valor, str) else ("" if valor is None else valor)
        if campo == "nascimento":
            leitura.nascimento(valor if isinstance(valor, date) else texto or None)
        elif campo == "inicio":
            leitura.inicio(valor if isinstance(valor, date) else texto or None)
        elif not isinstance(texto, str):  # data num campo de texto: a célula fica de fora (visto no uso)
            leitura.aviso("p1.celula_fora_do_lugar")
        elif campo == "mae":
            leitura.campos["nome_mae"] = texto or None
            if texto and _PRONTUARIO.search(texto):  # o nome do paciente na linha da mãe? (visto no uso)
                leitura.aviso("p1.mae_com_prontuario")
        elif texto:
            getattr(leitura, campo)(texto)
    if not reconhecidos:
        return RegistroP1(bloco.numero_linha, excecao="p1.ilegivel")
    registro = RegistroP1(**leitura.campos)  # type: ignore[arg-type]
    registro = replace(registro, telefones=_do_proprio_paciente(registro.telefones, registro.nome))
    return replace(registro, avisos=tuple(leitura.avisos), sobras=tuple(leitura.sobras))


ORDEM_DA_FICHA = (
    "paciente", "mae", "nascimento", "endereco", "cidade", "telefone", "documentos", "convenio", "inicio",
)  # fmt: skip


def _campo_pela_posicao(posicao: int, rotulados: set[str | None], vistos: set[str], valor: Valor) -> str | None:
    """O campo de um rótulo repetido: o da posição no padrão de 9 linhas, se nenhum rótulo da ficha o tem; senão, o
    único campo que falta. Campo de data só com data. Sem candidato, a ficha vai às exceções (ND-49)."""
    faltam = [c for c in ORDEM_DA_FICHA if c not in rotulados and c not in vistos]
    candidato = None
    if posicao < len(ORDEM_DA_FICHA) and ORDEM_DA_FICHA[posicao] in faltam:
        candidato = ORDEM_DA_FICHA[posicao]
    elif len(faltam) == 1:
        candidato = faltam[0]
    if candidato in ("nascimento", "inicio") and ler_data(valor) is None:
        return None
    return candidato


def _com_continuacoes(celulas: Sequence[CelulaP1], leitura: _Leitura) -> list[CelulaP1]:
    """Linha sem rótulo e com texto continua a de cima (um nome ou endereço que quebrou de linha, visto no uso)."""
    juntas: list[CelulaP1] = []
    for celula in celulas:
        anterior = juntas[-1] if juntas else None
        if (
            anterior is not None
            and not norm_rotulo(celula.rotulo)
            and isinstance(celula.valor, str)
            and celula.valor.strip()
            and isinstance(anterior.valor, str)
        ):
            juntas[-1] = replace(anterior, valor=f"{anterior.valor} {celula.valor}")
            leitura.aviso("p1.linha_continuada")
            continue
        juntas.append(celula)
    return juntas


def _do_proprio_paciente(telefones: tuple[TelefoneLido, ...], nome: str | None) -> tuple[TelefoneLido, ...]:
    """Um "contato" sem parentesco cujo nome é parte do nome do paciente ("(64) 9... FULANO" na ficha de FULANO DE
    TAL) é o telefone do próprio paciente (visto no uso)."""
    if not nome:
        return telefones
    palavras = set(norm_nome(nome).split())
    corrigidos = []
    for t in telefones:
        if t.contato and not t.parentesco and set(norm_nome(t.contato).split()) <= palavras:
            t = replace(t, contato=None, tipo="celular" if len(t.numero) == 9 else "fixo")
        corrigidos.append(t)
    return tuple(corrigidos)


# ------------------------------------------------------------------ P4 e P3
@dataclass(frozen=True, slots=True)
class LinhaP4:
    numero_linha: int
    valores: dict[str, Valor]  # pelo rótulo normalizado da coluna: PRONT, ENT, PACIENTE, CARTAOSUS, CPF, CEP...

    def prontuario(self) -> int | None:
        """Forma numérica, só para casar com a P1 (ND-48): a P1 guarda os zeros à esquerda, a P4 não."""
        valor = self.valores.get("PRONT")
        texto = str(valor).strip() if valor is not None else ""
        if texto.endswith(".0"):
            texto = texto[:-2]
        return int(texto) if texto.isdigit() else None

    def digitos(self, coluna: str) -> str | None:
        valor = self.valores.get(coluna)
        if valor is None or isinstance(valor, date):
            return None
        texto = str(valor)
        if texto.endswith(".0"):
            texto = texto[:-2]
        digitos = _digitos(texto)
        if coluna == "CPF" and isinstance(valor, int | float) and 9 <= len(digitos) < 11:
            digitos = digitos.zfill(11)  # CPF gravado como número no Excel: os zeros à esquerda somem (DD-117)
        return digitos or None

    def texto(self, coluna: str) -> str | None:
        valor = self.valores.get(coluna)
        return (_espacos(valor).strip(" .:-/") or None) if isinstance(valor, str) else None

    def nome(self) -> str | None:
        texto = self.texto("PACIENTE")
        return norm_nome(texto) if texto else None

    def texto_do_nome(self) -> str | None:
        return self.texto("PACIENTE")

    def cidade(self) -> str | None:
        texto = self.texto("CIDADE")
        if texto and (uf := _UF.search(texto)):
            texto = texto[: uf.start()].strip(" -/") or None
        return texto

    def entrada(self) -> date | None:
        return ler_data(self.valores.get("ENT"))


COLUNAS_P4 = ("PRONT", "ENT", "PACIENTE", "CARTAOSUS", "CPF", "CIDADE", "CEP", "CNES", "PLANO")


@dataclass(frozen=True, slots=True)
class LinhaP3:
    aba: str
    numero_linha: int
    ano: int | None  # o ano vem do cabeçalho do bloco, não da linha (ND-56)
    nome: str
    valores: tuple[str, ...]  # a linha como texto, para a conferência lado a lado


_SENTINELA = re.compile(r"^NAO HOUVE\b")


def coluna_do_nome_p3(aba: str) -> int:
    """Perfilamento §2.1: o nome está na coluna B na aba de óbitos e na A nas demais."""
    return 1 if norm_rotulo(aba).startswith("OBITO") else 0


def classificar_linha_p3(valores: Sequence[Valor], coluna_nome: int) -> tuple[str, object]:
    """('vazia' | 'ano' | 'sentinela' | 'cabecalho' | 'registro', dado)."""
    preenchidos = [v for v in valores if v not in (None, "")]
    if not preenchidos:
        return "vazia", None
    if len(preenchidos) == 1:
        unico = str(preenchidos[0]).strip().removesuffix(".0")
        ano = re.fullmatch(r"(?:[A-Za-zÀ-ÿ]+\s*[:.-]?\s*)?((?:19|20)\d{2})", unico)
        if ano:
            return "ano", int(ano.group(1))
    primeiro = norm_nome(str(preenchidos[0]))
    if _SENTINELA.match(primeiro):
        return "sentinela", None
    nome = valores[coluna_nome] if coluna_nome < len(valores) else None
    if (
        isinstance(nome, str)
        and len(nome.split()) >= 2
        and re.search(r"[A-Za-zÀ-ÿ]{2}", nome)
        and norm_rotulo(nome) not in ("NOME", "NOMEDOPACIENTE", "PACIENTE")
    ):
        return "registro", _espacos(nome)
    return "cabecalho", None


# ------------------------------------------------------------------ planejamento (DDS §14.1, DD-114)
@dataclass(frozen=True, slots=True)
class Planejado:
    registro: RegistroP1  # já completado pela P4
    p4: tuple[LinhaP4, ...] = ()
    p3: tuple[LinhaP3, ...] = ()

    @property
    def excecao(self) -> str | None:
        return self.registro.excecao


@dataclass(frozen=True, slots=True)
class Plano:
    itens: tuple[Planejado, ...]
    contagens_p4: dict[str, int]
    contagens_p3: dict[str, int]
    cid_descartados: int


def _completar_com_p4(registro: RegistroP1, linhas: Sequence[LinhaP4]) -> RegistroP1:
    """DD-114: a P1 prevalece. A P4 preenche só o que está vazio e confere o que já existe. Com várias entradas do
    mesmo paciente, cada campo vem da mais recente que o tem (DD-117: o CPF de uma entrada antiga se perdia)."""
    avisos = list(registro.avisos)
    if not linhas:
        avisos.append("p4.sem_linha")
        return replace(registro, avisos=tuple(avisos))
    if len(linhas) > 1:
        avisos.append("p4.varias_linhas")
    recentes = sorted(linhas, key=lambda li: (li.entrada() or date.min, li.numero_linha), reverse=True)

    def mais_recente[T](ler: Callable[[LinhaP4], T | None]) -> T | None:
        return next((v for v in map(ler, recentes) if v is not None), None)

    mudancas: dict[str, object] = {}
    entrada = mais_recente(lambda li: e if (e := li.entrada()) is not None and e >= INICIO_MINIMO else None)
    cpf = mais_recente(lambda li: li.digitos("CPF"))
    cns = mais_recente(lambda li: li.digitos("CARTAOSUS"))
    cep = mais_recente(lambda li: c if (c := li.digitos("CEP")) is not None and len(c) == 8 else None)
    numero_p4 = mais_recente(LinhaP4.prontuario)
    if registro.prontuario is None and numero_p4 is not None:
        mudancas["prontuario"] = str(numero_p4)
        avisos.append("p4.completou_prontuario")
    # Campo vazio na ficha vem da P4, quando a P4 o tem (DD-117): nome e cidade só completam, nunca conferem, porque
    # a grafia varia de uma planilha para a outra.
    for campo_texto, texto, codigo_texto in (
        ("nome", mais_recente(LinhaP4.texto_do_nome), "nome"),
        ("municipio_nome", mais_recente(LinhaP4.cidade), "cidade"),
    ):
        if getattr(registro, campo_texto) is None and texto is not None:
            mudancas[campo_texto] = texto
            avisos.append(f"p4.completou_{codigo_texto}")
    for campo, valor, codigo in (("inicio", entrada, "inicio"), ("cpf", cpf, "cpf"), ("cns", cns, "cns")):
        atual = getattr(registro, campo)
        if atual is None and valor is not None:
            mudancas[campo] = valor
            avisos.append(f"p4.completou_{codigo}")
        elif atual is not None and valor is not None and atual != valor:
            avisos.append(f"p4.{codigo}_divergente")
    if registro.cep is None and cep is not None:
        mudancas["cep"] = cep
        avisos.append("p4.completou_cep")
    return replace(registro, avisos=tuple(avisos), **mudancas)  # type: ignore[arg-type]


def _prontuario_pela_p4(registro: RegistroP1, livres: dict[int, list[LinhaP4]]) -> tuple[int | None, str | None]:
    """DD-117: o prontuário das linhas livres da P4 com o mesmo CPF, o mesmo CNS ou o mesmo nome. Vale se for um só;
    mais de um fica sem ligação, com aviso. CPF ou CNS diferentes do da ficha desfazem o candidato."""
    nome = norm_nome(registro.nome) if registro.nome else None
    candidatos: dict[int, str] = {}
    for numero, linhas in livres.items():
        pelo_cpf = registro.cpf is not None and any(li.digitos("CPF") == registro.cpf for li in linhas)
        pelo_cns = registro.cns is not None and any(li.digitos("CARTAOSUS") == registro.cns for li in linhas)
        pelo_nome = nome is not None and any(li.nome() == nome for li in linhas)
        if not (pelo_cpf or pelo_cns or pelo_nome):
            continue
        cpfs = {c for li in linhas if (c := li.digitos("CPF"))}
        cnss = {c for li in linhas if (c := li.digitos("CARTAOSUS"))}
        if (registro.cpf and cpfs and registro.cpf not in cpfs) or (registro.cns and cnss and registro.cns not in cnss):
            continue
        candidatos[numero] = (
            "p4.ligada_por_cpf" if pelo_cpf else "p4.ligada_por_cns" if pelo_cns else "p4.ligada_pelo_nome"
        )
    if len(candidatos) > 1:
        return None, "p4.ligacao_ambigua"
    if not candidatos:
        return None, None
    [(numero, aviso)] = candidatos.items()
    return numero, aviso


def ler_para_cadastro(
    numero_linha: int, p1: Sequence[tuple[str, Valor]], p4: Sequence[Mapping[str, Valor]], hoje: date
) -> RegistroP1:
    """DD-118: a ficha de uma exceção, lida de novo do original guardado, para o cadastro pela tela. A mesma leitura
    da carga, completada pelas linhas da P4 que se ligaram a ela, mas tolerante ao rótulo repetido; sem exceção, que
    aqui quem decide é a recepção. Ficha sem campo nenhum reconhecido devolve o registro vazio."""
    bloco = BlocoP1(
        numero_linha, tuple(CelulaP1(numero_linha + i, rotulo, valor) for i, (rotulo, valor) in enumerate(p1))
    )
    registro = interpretar_p1(bloco, tolerante=True)
    if registro.excecao is not None:
        return RegistroP1(numero_linha)
    linhas = [LinhaP4(i, dict(valores)) for i, valores in enumerate(p4)]
    return _completar_com_p4(_inicio_plausivel(registro, hoje), linhas)


def triade_divergente(
    ficha: RegistroP1, nome: str | None, nascimento: date | None, nome_mae: str | None
) -> tuple[str, ...] | None:
    """DD-119: os itens da tríade (nome, nascimento, nome da mãe) da ficha que não batem com os do cadastro; vazio,
    tudo confere. Nomes sem acento, caixa nem espaço a mais. Item vazio na ficha não é comparado; presente na ficha e
    vazio no cadastro diverge. None se a ficha não tem nenhum dos três: não há o que conferir."""
    pares: tuple[tuple[str, str | date | None, str | date | None], ...] = (
        ("nome", ficha.nome, nome),
        ("nascimento", ficha.nascimento, nascimento),
        ("nome_mae", ficha.nome_mae, nome_mae),
    )
    presentes = [(item, da_ficha, do_cadastro) for item, da_ficha, do_cadastro in pares if da_ficha]
    if not presentes:
        return None

    def igual(da_ficha: str | date, do_cadastro: str | date | None) -> bool:
        if isinstance(da_ficha, str):
            return isinstance(do_cadastro, str) and norm_nome(da_ficha) == norm_nome(do_cadastro)
        return da_ficha == do_cadastro

    return tuple(item for item, da_ficha, do_cadastro in presentes if not igual(da_ficha, do_cadastro))


def _inicio_plausivel(registro: RegistroP1, hoje: date) -> RegistroP1:
    if registro.inicio is not None and not INICIO_MINIMO <= registro.inicio <= hoje:
        return replace(registro, inicio=None, avisos=(*registro.avisos, "inicio.invalido"))
    return registro


def planejar(
    blocos: Sequence[BlocoP1], linhas_p4: Sequence[LinhaP4], linhas_p3: Sequence[LinhaP3], hoje: date
) -> Plano:
    """Cada ficha da P1 vira um item: importar, com seus avisos, ou exceção. As exceções que dependem do banco
    (CPF, CNS e prontuário já usados) chegam depois, na criação pelo MOD-02 (DD-67)."""
    por_prontuario: dict[int, list[LinhaP4]] = defaultdict(list)
    sem_prontuario = 0
    for linha in linhas_p4:
        numero = linha.prontuario()
        if numero is None:
            sem_prontuario += 1
        else:
            por_prontuario[numero].append(linha)
    por_nome: dict[str, list[LinhaP3]] = defaultdict(list)
    for linha3 in linhas_p3:
        por_nome[norm_nome(linha3.nome)].append(linha3)

    registros = [_inicio_plausivel(interpretar_p1(bloco), hoje) for bloco in blocos]
    # Primeira passada: pelo prontuário (DD-114). Os prontuários da P1 ficam reservados, mesmo sem linha na P4.
    da_p1 = {int(r.prontuario) for r in registros if r.excecao is None and r.prontuario}
    ligacoes: dict[int, tuple[LinhaP4, ...]] = {
        i: tuple(por_prontuario.get(int(r.prontuario), ()))
        for i, r in enumerate(registros)
        if r.excecao is None and r.prontuario
    }
    # Segunda passada (DD-117): a ficha sem prontuário, pelo CPF ou pelo nome, nas linhas que sobraram.
    livres = {n: linhas for n, linhas in por_prontuario.items() if n not in da_p1}
    for i, registro in enumerate(registros):
        if registro.excecao is None and not registro.prontuario:
            numero, aviso = _prontuario_pela_p4(registro, livres)
            if aviso:
                registros[i] = replace(registro, avisos=(*registro.avisos, aviso))
            if numero is not None:
                ligacoes[i] = tuple(livres.pop(numero))

    itens: list[Planejado] = []
    ligadas: set[int] = set()
    casadas: set[tuple[str, int]] = set()
    for i, registro in enumerate(registros):
        if registro.excecao is not None:
            itens.append(Planejado(registro))
            continue
        doP4 = ligacoes.get(i, ())
        ligadas.update(id(li) for li in doP4)
        registro = _completar_com_p4(registro, doP4)
        doP3 = tuple(por_nome.get(norm_nome(registro.nome), ())) if registro.nome else ()
        casadas.update((li.aba, li.numero_linha) for li in doP3)
        if doP3:  # RF-1103: cadastro desatualizado; a recepção decide, a carga não registra evento
            registro = replace(registro, excecao="evento_saida")
        elif registro.nome is None or registro.prontuario is None or registro.inicio is None:
            registro = replace(registro, excecao="P-03.minimo")  # P-28: a recepção cadastra pela tela
        itens.append(Planejado(registro, doP4, doP3))

    ligadas_p4 = sum(1 for li in linhas_p4 if id(li) in ligadas)
    contagens_p4 = {
        "linhas": len(linhas_p4),
        "ligadas": ligadas_p4,
        "fora_da_base": len(linhas_p4) - ligadas_p4 - sem_prontuario,
        "sem_prontuario": sem_prontuario,
    }
    contagens_p3 = {
        "linhas": len(linhas_p3),
        "casadas": len(casadas),
        "sem_correspondencia": len(linhas_p3) - len(casadas),
    }
    cid = sum(1 for item in itens if item.registro.cid_descartado)
    return Plano(tuple(itens), contagens_p4, contagens_p3, cid)


# ------------------------------------------------------------------ contagem (RNF-103, DDS §14.2)
@dataclass(frozen=True, slots=True)
class Desfecho:
    """O que aconteceu com uma ficha: importada (paciente_id na efetivação) ou exceção."""

    numero_linha: int
    importado: bool
    excecao: str | None = None
    avisos: tuple[str, ...] = field(default=())


def contagens(lidas_p1: int, desfechos: Iterable[Desfecho], plano: Plano) -> dict[str, object]:
    """Só números, por planilha e por código (DD-65). 'fecha' é a conta da §14.2 em cada planilha."""
    lista = list(desfechos)
    importados = sum(1 for d in lista if d.importado)
    sem_ficha = sum(1 for d in lista if d.excecao == SEM_FICHA)
    excecoes = Counter(d.excecao for d in lista if not d.importado and d.excecao and d.excecao != SEM_FICHA)
    sem_codigo = sum(1 for d in lista if not d.importado and not d.excecao)
    avisos = Counter(a for d in lista for a in d.avisos)
    p1 = {
        "linhas": lidas_p1,
        "importados": importados,
        "excecoes": sum(excecoes.values()) + sem_codigo,
        "sem_ficha": sem_ficha,  # título ou nota entre as fichas: nem paciente nem exceção, mas à vista
    }
    fecha = (
        len(lista) == lidas_p1
        and sem_codigo == 0
        and p1["linhas"] == p1["importados"] + p1["excecoes"] + p1["sem_ficha"]
        and plano.contagens_p4["linhas"]
        == plano.contagens_p4["ligadas"] + plano.contagens_p4["fora_da_base"] + plano.contagens_p4["sem_prontuario"]
        and plano.contagens_p3["linhas"] == plano.contagens_p3["casadas"] + plano.contagens_p3["sem_correspondencia"]
    )
    return {
        "p1": p1,
        "p4": dict(plano.contagens_p4),
        "p3": dict(plano.contagens_p3),
        "excecoes": dict(sorted(excecoes.items())),
        "avisos": dict(sorted(avisos.items())),
        "cid_descartados": plano.cid_descartados,
        "fecha": fecha,
    }
