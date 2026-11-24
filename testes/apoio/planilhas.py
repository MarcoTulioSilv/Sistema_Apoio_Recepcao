"""Planilhas sintéticas da carga inicial (PT §5.3): a estrutura das planilhas da clínica, descrita no perfilamento
da fase 1 (docs/fase1-*.md), com dados fictícios da fábrica e os defeitos reais conhecidos. Nunca uma planilha real.

- P1: fichas de rótulo e valor, com as grafias variadas dos rótulos, as células compostas, o CID no início, o CPF
  sem rótulo, a UF ora presente ora não, CEP com três separadores, IBGE de 6 dígitos e telefones com contato.
- P4: tabela com um "2009" solto na linha 1 e o cabeçalho na 2; o prontuário sem os zeros à esquerda; linhas
  históricas fora da base e uma sem prontuário.
- P3: abas por tipo de evento, em blocos por ano, com linhas-sentinela; o nome na coluna B dos óbitos e na A das
  demais.

Cada ficha especial carrega o defeito que reproduz e o desfecho esperado; as demais são importadas.
"""

from __future__ import annotations

import io
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import xlsxwriter

from sar.modulo_10_carga.extrator import ARQUIVOS
from testes.apoio.fabrica import VALORES_SENSIVEIS, Fabrica, Municipio, digitos_cpf, municipios_go

IMPORTADO = "importado"
# Fora da regra do dígito verificador do IBGE: o cálculo erraria o sétimo dígito (DD-53, CT-MIG-02).
BURITI_DE_GOIAS = Municipio("5203939", "Buriti de Goiás", "GO")

# Defeito → desfecho esperado e avisos que precisam aparecer na ficha.
DEFEITOS: dict[str, tuple[str, tuple[str, ...]]] = {
    "rotulo_antes_do_numero": (IMPORTADO, ()),  # passa sem erro e troca o contato: só a conferência acha (§5.1)
    "cpf_digito_errado": (IMPORTADO, ("cpf.invalido",)),
    "prontuario_repetido": ("prontuario.repetido", ()),
    "sem_linha_na_p4": (IMPORTADO, ("p4.sem_linha",)),
    "evento_de_saida": ("evento_saida", ()),
    "ibge_fora_da_regra": (IMPORTADO, ()),
    "cid_no_inicio": (IMPORTADO, ()),
    "rotulo_desconhecido": (IMPORTADO, ("p1.linha_nao_reconhecida",)),  # a linha estranha não derruba a ficha
    "sem_prontuario": ("P-03.minimo", ()),
    "cep_generico": (IMPORTADO, ("cep.generico",)),
    "telefone_sem_ddd": (IMPORTADO, ("telefone.ddd_presumido",)),
    "inicio_so_na_p4": (IMPORTADO, ("p4.completou_inicio",)),
    "cns_divergente_na_p4": (IMPORTADO, ("p4.cns_divergente",)),
    "cpf_repetido": ("cpf.repetido", ()),
    "ibge_inexistente": (IMPORTADO, ("ibge.sem_correspondencia",)),
}


def _sensivel(valor: str) -> str:
    VALORES_SENSIVEIS.add(valor)
    return valor


@dataclass
class Ficha:
    linha: int  # primeira linha da ficha na P1
    prontuario: str | None
    nome: str
    nome_mae: str
    nascimento: date
    cpf: str
    cns: str
    municipio: Municipio
    cep: str
    convenio: str
    inicio: date | None
    defeito: str | None = None
    telefones: list[tuple[str, str]] = field(default_factory=list)  # (número formatado, rótulo depois dele)

    @property
    def esperado(self) -> str:
        return DEFEITOS[self.defeito][0] if self.defeito else IMPORTADO


@dataclass
class Sinteticas:
    fichas: list[Ficha]
    p1: bytes
    p4: bytes
    p3: bytes
    linhas_p4: int
    fora_da_base_p4: int
    sem_prontuario_p4: int
    linhas_p3: int
    casadas_p3: int

    def gravar(self, pasta: Path) -> Path:
        pasta.mkdir(parents=True, exist_ok=True)
        for chave, conteudo in (("p1", self.p1), ("p4", self.p4), ("p3", self.p3)):
            (pasta / ARQUIVOS[chave]).write_bytes(conteudo)
        return pasta

    def esperados(self) -> dict[str, int]:
        importados = sum(1 for f in self.fichas if f.esperado == IMPORTADO)
        return {
            "linhas": len(self.fichas) + 1,
            "importados": importados,
            "excecoes": len(self.fichas) - importados,
            "sem_ficha": 1,
        }  # o título no topo da P1


def _cpf_formatado(cpf: str, aleatorio: random.Random) -> str:
    return aleatorio.choice((f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}", cpf, f"{cpf[:9]}-{cpf[9:]}"))


def _cns_formatado(cns: str) -> str:
    return f"{cns[:3]}.{cns[3:7]}.{cns[7:11]}.{cns[11:]}"


def _cep_formatado(cep: str, aleatorio: random.Random) -> str:
    return aleatorio.choice((f"{cep[:5]}-{cep[5:]}", cep, f"{cep[:5]}.{cep[5:]}"))


class _Gerador:
    def __init__(self, fabrica: Fabrica, semente: int) -> None:
        self.fabrica = fabrica
        self.aleatorio = random.Random(semente)  # noqa: S311 — dados de teste

    def celular(self) -> str:
        n = "9" + "".join(str(self.aleatorio.randrange(10)) for _ in range(8))
        return _sensivel(n)

    def fixo(self) -> str:
        n = self.aleatorio.choice("23") + "".join(str(self.aleatorio.randrange(10)) for _ in range(7))
        return _sensivel(n)

    def primeiro_nome(self) -> str:
        return _sensivel(self.fabrica.nome().split()[0].upper())

    def telefones(self, ficha: Ficha) -> None:
        a = self.aleatorio
        celular = self.celular()
        formatos = (f"(64) {celular[:5]}.{celular[5:]}", f"(64){celular[:5]}-{celular[5:]}", f"64{celular}")
        # O do paciente vem às vezes com o primeiro nome dele, como na P1 real (visto no uso, 18/11/2026).
        proprio = ("PACIENTE", "", "RESIDENCIA", ficha.nome.split()[0])
        ficha.telefones.append((a.choice(formatos), a.choice(proprio)))
        for _ in range(a.randrange(0, 3)):
            numero = self.celular() if a.random() < 0.7 else self.fixo()
            grau = a.choice(("esposa", "filha", "filho", "mãe", "irmã", "neta", "padrasto", "esposo"))
            formatado = f"(64) {numero[:-4]}.{numero[-4:]}"
            nome = self.primeiro_nome()
            # Os dois jeitos da planilha: "NOME (parentesco)" e "PARENTESCO NOME" (visto no uso, 18/11/2026).
            ficha.telefones.append((formatado, a.choice((f"{nome} ({grau})", f"{grau.upper()} {nome}"))))

    def ficha(self, i: int, prontuario: str, municipio: Municipio) -> Ficha:
        paciente = self.fabrica.paciente()
        nascimento = paciente.data_nascimento
        inicio = date(2015, 1, 1) + timedelta(days=self.aleatorio.randrange(3650))
        cep = f"758{self.aleatorio.randrange(10)}{self.aleatorio.randrange(1, 10)}{self.aleatorio.randrange(100):03d}"
        ficha = Ficha(
            0, prontuario, _sensivel(paciente.nome.upper()), _sensivel(paciente.nome_mae.upper()), nascimento,
            paciente.cpf, paciente.cns, municipio, cep, "IPASGO" if i % 9 == 4 else "SUS", inicio,
        )  # fmt: skip
        self.telefones(ficha)
        return ficha


def _defeitos(fichas: list[Ficha], gerador: _Gerador) -> None:
    """Aplica cada defeito numa ficha própria, a partir da terceira (as duas primeiras ficam sempre limpas)."""
    posicoes = dict(zip(DEFEITOS, range(2, 2 + len(DEFEITOS)), strict=True))
    for defeito, i in posicoes.items():
        fichas[i].defeito = defeito
    base = {d: fichas[i] for d, i in posicoes.items()}
    base["prontuario_repetido"].prontuario = fichas[0].prontuario  # a primeira entra; esta vai às exceções
    base["cpf_repetido"].cpf = fichas[1].cpf
    errado = base["cpf_digito_errado"]
    errado.cpf = _sensivel(errado.cpf[:9] + str((int(errado.cpf[9]) + 1) % 10) + errado.cpf[10])
    base["ibge_fora_da_regra"].municipio = BURITI_DE_GOIAS
    base["ibge_inexistente"].municipio = Municipio("5299990", "Município Fictício", "GO")
    base["cep_generico"].cep = "75800000"
    base["sem_prontuario"].prontuario = None
    base["inicio_so_na_p4"].inicio = None
    celular = gerador.celular()
    base["telefone_sem_ddd"].telefones = [(f"{celular[:5]}.{celular[5:]}", "PACIENTE")]
    rotulado = base["rotulo_antes_do_numero"]
    contato = gerador.primeiro_nome()
    celular = gerador.celular()
    # O rótulo do contato vem ANTES do número; a regra geral o atribui ao número anterior (perfilamento §4.4).
    rotulado.telefones = [(f"(64) {gerador.celular()}", f"{contato} (filha)"), (f"(64) {celular}", "")]


def _p1(fichas: list[Ficha], gerador: _Gerador) -> bytes:
    a = gerador.aleatorio
    saida = io.BytesIO()
    livro = xlsxwriter.Workbook(saida, {"in_memory": True})
    folha = livro.add_worksheet("Plan1")
    formato_data = livro.add_format({"num_format": "dd/mm/yyyy"})
    preto = livro.add_format({"bg_color": "#000000", "pattern": 1})
    folha.write_string(0, 0, "ENDEREÇOS E TELEFONES DOS PACIENTES")  # o título, que não é ficha (visto no uso)
    linha = 2
    for ficha in fichas:
        ficha.linha = linha + 1
        pt = f"   {a.choice(('Nº PT:', 'NºPT:', 'NºPT ', 'Nº PT: '))} {ficha.prontuario}" if ficha.prontuario else ""
        uf = a.choice((" -GO", "-GO", " GO", ""))
        codigo = ficha.municipio.codigo_ibge[:6]
        cidade = (f"{ficha.municipio.nome.upper()}{uf}   CEP: {_cep_formatado(ficha.cep, a)}   "
                  f"{a.choice(('CÓD.IBGE:', 'COD.IBGE:', 'CÓD. IBGE:'))} {codigo}")  # fmt: skip
        rotulo_cpf = "" if ficha.defeito == "rotulo_desconhecido" or a.random() < 0.1 else "CPF: "
        documentos = (
            f"{rotulo_cpf}{_cpf_formatado(ficha.cpf, a)}  RG: {a.randrange(10**6, 10**7)}  ORGÃO EXPEDIDOR: SSP-GO"
        )
        convenio = f"{ficha.convenio}{a.choice(('   ', ': ', ' / '))}CNS: {_cns_formatado(ficha.cns)}"
        endereco = (f"RUA {gerador.primeiro_nome()} QD {a.randrange(1, 90)} LT {a.randrange(1, 30)} "
                    f"Nº {a.randrange(1, 999)} SETOR {gerador.primeiro_nome()}")  # fmt: skip
        telefones = "  ".join(f"{numero}  {rotulo}".strip() for numero, rotulo in ficha.telefones)
        nascimento_rotulo = (
            "DATA DE MASC:" if ficha.defeito == "cid_no_inicio" else a.choice(("DATA DE NASC:", "DATA NASC:"))
        )
        celulas: list[tuple[str, object]] = [
            (a.choice(("PACIENTE:", "PACIENTE")), f"{ficha.nome}{pt}"),
            (a.choice(("NOME DA MÃE:", "NOME MÃE:")), ficha.nome_mae),
            (nascimento_rotulo, ficha.nascimento),
            ("ENDEREÇO:", endereco),
            (a.choice(("CIDADE/CEP:", "CIDADE /CEP:", "CIDADE:", "PACIENTE:")), cidade),
            (a.choice(("TELEFONE:", "TELEFONE")), telefones),
            (a.choice(("DOC.PESSOAIS:", "DOC.PESSOAIS: ")), documentos),
            (a.choice(("CONVÊNIO:", "CONVENIO:", "CONVÊNIO: ")), convenio),
        ]
        if ficha.inicio is not None:
            if ficha.defeito == "cid_no_inicio":
                inicio: object = f"{ficha.inicio.day}/{ficha.inicio.month}/{ficha.inicio.year}   CID N-000"
            else:
                # data, texto ou o número serial do Excel numa célula sem formato de data (visto no uso)
                inicio = a.choice(
                    (ficha.inicio, ficha.inicio.strftime("%d/%m/%Y"), str((ficha.inicio - date(1899, 12, 30)).days))
                )
            celulas.append((a.choice(("INICIO TRATAM:", "INICIO TRATAM: ")), inicio))
        if ficha.defeito == "rotulo_desconhecido":
            celulas.append(("OBSERVAÇÃO:", "texto livre"))
        if a.random() < 0.1:  # 1 em 10 traz o endereço na última linha (perfilamento §2)
            celulas.append(celulas.pop(3))
        if ficha is fichas[3]:
            celulas.insert(4, ("", ""))  # uma linha vazia no meio da ficha, que não a separa (visto no uso)
        for rotulo, valor in celulas:
            if not rotulo:
                linha += 1
                continue
            folha.write_string(linha, 0, rotulo)
            if isinstance(valor, date):
                folha.write_datetime(linha, 1, valor, formato_data)  # type: ignore[arg-type]
            else:
                folha.write_string(linha, 1, str(valor))
            linha += 1
        # A faixa preta que separa as fichas na P1 real (visto no uso, 18/11/2026); a terceira esconde um texto.
        folha.write_string(linha, 0, "", preto)
        folha.write_string(linha, 1, "RUA ESCONDIDA QD 1 LT 1" if ficha is fichas[2] else "", preto)
        linha += 1
    _abas_extras_p1(livro, fichas, gerador)
    livro.close()
    return saida.getvalue()


def _abas_extras_p1(livro: xlsxwriter.Workbook, fichas: list[Ficha], gerador: _Gerador) -> None:
    """Como na P1 real (17/11/2026): uma tentativa de tabela, visível, com um dado por coluna, e uma aba oculta com
    fichas antigas. A carga lê só a aba visível com fichas (extrator.aba_de_fichas)."""
    tabela = livro.add_worksheet("Estruturada")
    for coluna, titulo in enumerate(("PACIENTE", "NOME DA MÃE", "DATA DE NASC", "CPF", "CNS", "CIDADE")):
        tabela.write_string(0, coluna, titulo)
    for i, ficha in enumerate(fichas[:5], start=1):
        for coluna, valor in enumerate((ficha.nome, ficha.nome_mae, ficha.nascimento.strftime("%d/%m/%Y"), ficha.cpf,
                                        ficha.cns, ficha.municipio.nome.upper())):  # fmt: skip
            tabela.write_string(i, coluna, valor)
    antiga = livro.add_worksheet("Antigos")
    for i in range(3):
        nome = _sensivel(gerador.fabrica.nome().upper())
        antiga.write_string(i * 4, 0, "PACIENTE:")
        antiga.write_string(i * 4, 1, f"{nome}   Nº PT: {9000 + i}")
        antiga.write_string(i * 4 + 1, 0, "NOME DA MÃE:")
        antiga.write_string(i * 4 + 1, 1, _sensivel(gerador.fabrica.nome().upper()))
        antiga.write_string(i * 4 + 2, 0, "INICIO TRATAM:")
        antiga.write_string(i * 4 + 2, 1, "01/02/2012")
    antiga.hide()


def _p4(fichas: list[Ficha], gerador: _Gerador, historicos: int) -> tuple[bytes, int, int]:
    a = gerador.aleatorio
    saida = io.BytesIO()
    livro = xlsxwriter.Workbook(saida, {"in_memory": True})
    folha = livro.add_worksheet("Plan1")
    formato_data = livro.add_format({"num_format": "dd/mm/yyyy"})
    folha.write_number(0, 0, 2009)
    for coluna, titulo in enumerate(
        ("PRONT.", "ENT", "PACIENTE", "CARTÃO SUS", "CPF", "CIDADE", "CEP", "CNES", "PLANO")
    ):
        folha.write_string(1, coluna, titulo)
    linha = 2

    def escrever(prontuario: object, entrada: date, nome: str, cns: str, cpf: str, cidade: str, plano: str) -> None:
        nonlocal linha
        if isinstance(prontuario, int):
            folha.write_number(linha, 0, prontuario)
        else:
            folha.write_string(linha, 0, str(prontuario))
        folha.write_datetime(linha, 1, entrada, formato_data)  # type: ignore[arg-type]
        for coluna, valor in ((2, nome), (3, cns), (4, cpf), (5, cidade), (8, plano)):
            folha.write_string(linha, coluna, valor)
        folha.write_string(linha, 7, "0000000")  # CNES: fora do sistema (DEC-73)
        linha += 1

    for ficha in fichas:
        if ficha.prontuario is None or ficha.defeito == "sem_linha_na_p4":
            continue
        if ficha.defeito == "prontuario_repetido":
            continue  # a P4 tem a linha do primeiro dono do número
        entrada = ficha.inicio or date(2019, 5, 6)
        cns = ficha.cns
        if ficha.defeito == "cns_divergente_na_p4":
            cns = _sensivel(gerador.fabrica.cns())
        escrever(int(ficha.prontuario), entrada, ficha.nome, cns, ficha.cpf, ficha.municipio.nome.upper(), "SUS")
    fora = 0
    for _ in range(historicos):
        antigo = gerador.fabrica.paciente()
        cpf = antigo.cpf[:9] + digitos_cpf(antigo.cpf[:9])
        escrever(a.randrange(9000, 9900), date(2010, 1, 1) + timedelta(days=a.randrange(3000)), antigo.nome.upper(),
                 antigo.cns, cpf, "JATAI", a.choice(("ÓBITO", "ALTA", "TRANSF.", "TRANSFER", "IPASGO")))  # fmt: skip
        fora += 1
    antigo = gerador.fabrica.paciente()
    escrever("S/N", date(2012, 3, 4), antigo.nome.upper(), antigo.cns, antigo.cpf, "JATAI", "OBITO")
    livro.close()
    return saida.getvalue(), linha - 2, fora


def _p3(fichas: list[Ficha], gerador: _Gerador) -> tuple[bytes, int, int]:
    a = gerador.aleatorio
    saida = io.BytesIO()
    livro = xlsxwriter.Workbook(saida, {"in_memory": True})
    formato_data = livro.add_format({"num_format": "dd/mm/yyyy"})
    saida_listada = next(f for f in fichas if f.defeito == "evento_de_saida")
    abas = {"OBITO": 10, "ALTA": 3, "TRANFERENCIA": 6, "TRANSPLANTE": 7}
    registros = casadas = 0
    nomes_da_p1 = {f.nome for f in fichas}
    for aba, colunas in abas.items():
        folha = livro.add_worksheet(aba)
        coluna_nome = 1 if aba == "OBITO" else 0
        linha = 0
        for ano in (2018, 2019, 2024):
            folha.write_number(linha, 0, ano)
            linha += 1
            if aba == "ALTA" and ano == 2019:
                folha.write_string(linha, 0, "NÃO HOUVE ALTA")
                linha += 2
                continue
            for _ in range(a.randrange(1, 4)):
                nome = gerador.fabrica.nome().upper()
                while nome in nomes_da_p1:  # o Faker repete nomes; só o defeito "evento de saída" pode casar
                    nome = gerador.fabrica.nome().upper()
                _sensivel(nome)
                if coluna_nome == 1:
                    folha.write_number(linha, 0, registros + 1)
                folha.write_string(linha, coluna_nome, nome)
                folha.write_datetime(linha, coluna_nome + 1, date(ano, a.randrange(1, 13), 10), formato_data)  # type: ignore[arg-type]
                if colunas > 3:
                    folha.write_string(linha, colunas - 1, "????")
                registros += 1
                linha += 1
            linha += 1
        if aba == "TRANFERENCIA":
            folha.write_string(linha, 0, saida_listada.nome)
            folha.write_string(linha, 1, "12/03/2026")
            registros += 1
            casadas += 1
    livro.close()
    return saida.getvalue(), registros, casadas


def gerar(fabrica: Fabrica, pacientes: int = 30, historicos_p4: int = 20, semente: int = 7) -> Sinteticas:
    """Ao menos 2 + len(DEFEITOS) fichas, para caber cada defeito numa ficha própria."""
    if pacientes < 2 + len(DEFEITOS):
        raise ValueError(f"são precisas ao menos {2 + len(DEFEITOS)} fichas")
    gerador = _Gerador(fabrica, semente)
    municipios = [m for m in municipios_go() if m.codigo_ibge != BURITI_DE_GOIAS.codigo_ibge]
    fichas = [
        gerador.ficha(i, f"{(100 + i * 7) % 10000:04d}", gerador.aleatorio.choice(municipios)) for i in range(pacientes)
    ]
    _defeitos(fichas, gerador)
    p1 = _p1(fichas, gerador)
    p4, linhas_p4, fora = _p4(fichas, gerador, historicos_p4)
    p3, linhas_p3, casadas = _p3(fichas, gerador)
    return Sinteticas(fichas, p1, p4, p3, linhas_p4, fora, 1, linhas_p3, casadas)
