"""Regras puras da carga inicial (DDS §14.1, DD-114): sem banco, sem arquivo, sem relógio.

A leitura da P1 parte do extrator de referência da fase 1 (docs/extrator_p1.py), que acertou 10 de 10 na amostra:
o mesmo dicionário de rótulos, a mesma separação das células compostas e a mesma regra do telefone (o rótulo vem
depois do número). O que mudou é o destino: aqui as regras devolvem códigos de aviso e de exceção, nunca o valor,
porque o relatório chega ao terminal do TI só como contagem (DD-65, RNF-624).

Planilhas (docs/fase1-especificacao-migracao.md):
- P1, endereços e telefones: a base (RN-04). Fichas de 9 linhas, rótulo na coluna A e valor na B.
- P4, entradas: só completa o que falta na P1 e confere CPF e CNS, pelo prontuário (RF-1102, DD-114).
- P3, eventos: só conferida, pelo nome (RF-1103); nenhum evento é gravado (RN-05).
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date

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


# ------------------------------------------------------------------ datas (ND-55)
_DATA = re.compile(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})")


def ler_data(valor: Valor) -> date | None:
    """dd/mm/aaaa, a convenção da planilha (perfilamento §4.2); qualquer outra leitura é None, não palpite."""
    if isinstance(valor, date):
        return valor
    if not valor:
        return None
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
_PRONTUARIO = re.compile(r"N\s*[ºo°]?\s*\.?\s*PT\s*[:.]?\s*(\d+)", re.I)
_IBGE = re.compile(r"C[ÓO]?D[.:]?\s*(?:IBGE)?\s*[.:]?\s*(\d{6,7})", re.I)
_CEP = re.compile(r"CEP\s*[.:]?\s*([\d.\- ]{8,12})", re.I)
_UF = re.compile(r"[\s\-]+([A-Z]{2})$")
_CPF = re.compile(r"\b(\d{3}[.\s]?\d{3}[.\s]?\d{3}[-.\s]?\d{2})\b")
_RG = re.compile(r"RG\s*[.:]?\s*([\d.\-]+)", re.I)
_ORGAO = re.compile(r"(?:ORG[ÃÂA]?O?\.?\s*EXPEDIDOR\s*[.:]?)?\s*([A-Z]{2,6}\s*[-\s]?\s*[A-Z]{2})\s*$", re.I)
_CNS = re.compile(r"CNS\s*[.:]?\s*([\d.\s]{15,25})", re.I)
_CID = re.compile(r"CID\s*[.:]?\s*N?[ºo°]?\s*[-:]?\s*([A-Z0-9.\-]*)", re.I)
_FONE = re.compile(r"(?:\(\s*\d{2}\s*\)\s*)?\d[\d\s.\-]{6,}\d")
_TIPOS_LOGRADOURO = r"(AV|AVENIDA|RUA|R|VIELA|TRAVESSA|TV|ALAMEDA|AL|PRACA|PRA[ÇC]A|ROD|RODOVIA)"
_BAIRRO = re.compile(r"\b(SETOR|CONJ\.?|CONJUNTO|RESIDENCIAL|JARDIM|BAIRRO|VILA)\b(.*)$", re.I)


class _Leitura:
    """Acumula os campos e os avisos de uma ficha."""

    def __init__(self, numero_linha: int) -> None:
        self.campos: dict[str, object] = {"numero_linha": numero_linha}
        self.avisos: list[str] = []

    def aviso(self, codigo: str) -> None:
        self.avisos.append(codigo)

    def paciente(self, valor: str) -> None:
        achado = _PRONTUARIO.search(valor)
        if achado:
            self.campos["prontuario"] = achado.group(1)
            valor = valor[: achado.start()]
        self.campos["nome"] = _espacos(valor) or None

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
        if self.campos.get("rg") and self.campos.get("rg") == self.campos.get("cpf"):  # ND-36: é a CIN
            self.campos.pop("rg")
            self.campos.pop("rg_orgao", None)
            self.aviso("rg.igual_cpf")

    def convenio(self, valor: str) -> None:
        cns = _CNS.search(valor)
        if cns:
            self.campos["cns"] = _digitos(cns.group(1))
            valor = valor[: cns.start()] + valor[cns.end() :]
        self.campos["convenio"] = re.sub(r"[\s/:]+", " ", valor).strip(" /:") or None

    def inicio(self, valor: Valor) -> None:
        if isinstance(valor, str):
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
        quadra = re.search(r"\bQD\s*[.:]?\s*(\w+)", resto, re.I)
        lote = re.search(r"\bLT\s*[.:]?\s*(\w+)", resto, re.I)
        complemento = " ".join(f"{r} {m.group(1)}" for r, m in (("QD", quadra), ("LT", lote)) if m)
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
            limpo = re.split(r"\b(?:QD|LT)\b", bairro.group(0), flags=re.I)[0]
            self.campos["bairro"] = _espacos(limpo).strip(" .:-") or None
            achados += 1
        corte = len(resto)
        for padrao in (r"\bN[ºo°.]?\s*[:.]?\s*\d", r"\bS/?N\b", r"\bQD\b", r"\bLT\b",
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

    def telefone(self, valor: str) -> None:
        telefones = list(self.campos.get("telefones", ()))  # type: ignore[call-overload]
        telefones.extend(ler_telefones(valor, self.avisos))
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
    palavras = texto.split()
    if grau_texto is None and palavras and parentesco(palavras[-1]) is not None:
        grau_texto, palavras = palavras[-1], palavras[:-1]
    nome = " ".join(palavras).strip(" .:") or None
    if nome is not None and norm_rotulo(nome) in PROPRIOS:
        return None, None, None, norm_rotulo(nome) == "RECADO"
    grau = parentesco(grau_texto) if grau_texto else None
    aviso = "contato.parentesco_desconhecido" if grau_texto and grau is None and nome else None
    if nome is None and grau_texto:
        return None, None, "contato.sem_nome", True  # quem atende, sem nome: recado no telefone do paciente
    return nome, grau, aviso, False


def ler_telefones(valor: str, avisos: list[str]) -> list[TelefoneLido]:
    """O rótulo de cada número é o texto que vem DEPOIS dele (perfilamento §5.1): a leitura pelo texto anterior
    passou sem erro e trocou os contatos. Número curto demais é ignorado; DDD ausente é presumido, com aviso."""
    numeros: list[tuple[str, int, int]] = []
    for achado in _FONE.finditer(valor):
        digitos = _digitos(achado.group(0))
        if len(digitos) >= 8:
            numeros.append((digitos, achado.start(), achado.end()))
    if not numeros and valor.strip():
        avisos.append("telefone.nenhum")
    lidos: list[TelefoneLido] = []
    for i, (digitos, _, fim) in enumerate(numeros):
        proximo = numeros[i + 1][1] if i + 1 < len(numeros) else len(valor)
        contato, grau, aviso, recado = _rotulo(valor[fim:proximo])
        if aviso:
            avisos.append(aviso)
        if len(digitos) in (8, 9):
            ddd, numero = DDD_PRESUMIDO, digitos
            avisos.append("telefone.ddd_presumido")
        elif len(digitos) in (10, 11):
            ddd, numero = digitos[:2], digitos[2:]
        else:
            avisos.append("telefone.numero")
            continue
        tipo = "recado" if recado or contato else ("celular" if len(numero) == 9 else "fixo")
        lidos.append(TelefoneLido(ddd, numero, tipo, contato, grau))
    return lidos


# ------------------------------------------------------------------ P1: ficha → registro
def interpretar_p1(bloco: BlocoP1) -> RegistroP1:
    """Rótulo desconhecido ou repetido não é adivinhado: a ficha inteira vai às exceções (ND-49)."""
    leitura = _Leitura(bloco.numero_linha)
    vistos: set[str] = set()
    reconhecidos = 0
    for celula in bloco.celulas:
        campo = ROTULOS.get(norm_rotulo(celula.rotulo))
        if campo is None:
            if not norm_rotulo(celula.rotulo) and celula.valor in (None, ""):
                continue
            return RegistroP1(bloco.numero_linha, excecao="p1.rotulo_desconhecido")
        if campo in vistos and campo != "telefone":
            return RegistroP1(bloco.numero_linha, excecao="p1.rotulo_repetido")
        vistos.add(campo)
        reconhecidos += 1
        valor = celula.valor
        texto = _espacos(valor) if isinstance(valor, str) else ("" if valor is None else valor)
        if campo == "nascimento":
            leitura.nascimento(valor if isinstance(valor, date) else texto or None)
        elif campo == "inicio":
            leitura.inicio(valor if isinstance(valor, date) else texto or None)
        elif not isinstance(texto, str):  # data num campo de texto: célula fora do lugar
            return RegistroP1(bloco.numero_linha, excecao="p1.celula_ilegivel")
        elif campo == "mae":
            leitura.campos["nome_mae"] = texto or None
        elif texto:
            getattr(leitura, campo)(texto)
    if not reconhecidos:
        return RegistroP1(bloco.numero_linha, excecao="p1.ilegivel")
    registro = RegistroP1(**leitura.campos)  # type: ignore[arg-type]
    return replace(registro, avisos=tuple(leitura.avisos))


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
        return _digitos(texto) or None

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
        if re.fullmatch(r"(19|20)\d{2}", unico):
            return "ano", int(unico)
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
    """DD-114: a P1 prevalece. A P4 preenche só o que está vazio e confere o que já existe."""
    avisos = list(registro.avisos)
    if not linhas:
        avisos.append("p4.sem_linha")
        return replace(registro, avisos=tuple(avisos))
    if len(linhas) > 1:
        avisos.append("p4.varias_linhas")  # especificação §4: a de entrada mais recente
    linha = max(linhas, key=lambda li: (li.entrada() or date.min, li.numero_linha))
    mudancas: dict[str, object] = {}
    entrada, cpf, cns, cep = linha.entrada(), linha.digitos("CPF"), linha.digitos("CARTAOSUS"), linha.digitos("CEP")
    if entrada is not None and entrada < INICIO_MINIMO:
        entrada = None
    for campo, valor, codigo in (("inicio", entrada, "inicio"), ("cpf", cpf, "cpf"), ("cns", cns, "cns")):
        atual = getattr(registro, campo)
        if atual is None and valor is not None:
            mudancas[campo] = valor
            avisos.append(f"p4.completou_{codigo}")
        elif atual is not None and valor is not None and atual != valor:
            avisos.append(f"p4.{codigo}_divergente")
    if registro.cep is None and cep is not None and len(cep) == 8:
        mudancas["cep"] = cep
        avisos.append("p4.completou_cep")
    return replace(registro, avisos=tuple(avisos), **mudancas)  # type: ignore[arg-type]


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

    itens: list[Planejado] = []
    ligadas: set[int] = set()
    casadas: set[tuple[str, int]] = set()
    for bloco in blocos:
        registro = _inicio_plausivel(interpretar_p1(bloco), hoje)
        if registro.excecao is not None:
            itens.append(Planejado(registro))
            continue
        numero = int(registro.prontuario) if registro.prontuario else None
        doP4 = tuple(por_prontuario.get(numero, ())) if numero is not None else ()
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
    excecoes = Counter(d.excecao for d in lista if not d.importado and d.excecao)
    sem_codigo = sum(1 for d in lista if not d.importado and not d.excecao)
    avisos = Counter(a for d in lista for a in d.avisos)
    p1 = {"linhas": lidas_p1, "importados": importados, "excecoes": sum(excecoes.values()) + sem_codigo}
    fecha = (
        len(lista) == lidas_p1
        and sem_codigo == 0
        and p1["linhas"] == p1["importados"] + p1["excecoes"]
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
