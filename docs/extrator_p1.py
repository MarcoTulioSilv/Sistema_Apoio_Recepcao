"""
Extrator de referência — Planilha P1 (endereços e telefones).
Objetivo: validar as regras de parsing contra a amostra, não é código de produção.
"""
import re, json, unicodedata, datetime
from openpyxl import load_workbook

ORIGEM = '/mnt/user-data/uploads/planilha_despersonalizada_end_pacientes.xlsx'


def sem_acento(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s)
                   if unicodedata.category(c) != 'Mn')


def norm_rotulo(s):
    if s is None:
        return ''
    s = sem_acento(str(s)).upper()
    s = re.sub(r'[^A-Z]', '', s)
    return s


# dicionário de rótulos -> campo canônico
ROTULOS = {
    'PACIENTE': 'paciente',
    'NOMEDAMAE': 'mae', 'NOMEMAE': 'mae',
    'DATADENASC': 'nascimento', 'DATANASC': 'nascimento',
    'DATADEMASC': 'nascimento',          # erro de digitação observado
    'ENDERECO': 'endereco',
    'CIDADECEP': 'cidade', 'CIDADE': 'cidade',
    'TELEFONE': 'telefone',
    'DOCPESSOAIS': 'documentos',
    'CONVENIO': 'convenio',
    'INICIOTRATAM': 'inicio',
}


def limpa(v):
    if v is None:
        return ''
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v
    return re.sub(r'\s+', ' ', str(v)).strip()


def blocos(ws):
    atual, saida = [], []
    for r in range(1, ws.max_row + 1):
        a, b = ws.cell(r, 1).value, ws.cell(r, 2).value
        if a is None and b is None:
            if atual:
                saida.append(atual)
                atual = []
        else:
            atual.append((r, a, b))
    if atual:
        saida.append(atual)
    return saida


def parse_data(v, exc, campo):
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.date() if isinstance(v, datetime.datetime) else v
    m = re.search(r'(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})', str(v))
    if not m:
        exc.append(f'{campo}: data não reconhecida em "{v}"')
        return None
    d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000 if y < 50 else 1900
    try:
        return datetime.date(y, mth, d)          # dd/mm/aaaa confirmado na amostra
    except ValueError:
        exc.append(f'{campo}: data inválida "{v}"')
        return None


def valida_cpf(num):
    if len(num) != 11:
        return False
    if num == num[0] * 11:
        return False
    for i in (9, 10):
        s = sum(int(num[j]) * ((i + 1) - j) for j in range(i))
        dv = (s * 10) % 11 % 10
        if dv != int(num[i]):
            return False
    return True


def valida_cns(num):
    if len(num) != 15:
        return False
    if num[0] in '12':
        s = sum(int(num[i]) * (15 - i) for i in range(15))
        return s % 11 == 0
    if num[0] in '789':
        s = sum(int(num[i]) * (15 - i) for i in range(15))
        return s % 11 == 0
    return False


def extrai_paciente(v, reg, exc):
    m = re.search(r'N\s*[ºo°]?\s*PT\s*:?\s*(\d+)', v, re.I)
    if m:
        reg['num_prontuario'] = m.group(1)
        reg['num_prontuario_numerico'] = int(m.group(1))
        reg['num_prontuario_digitos'] = len(m.group(1))
        v = v[:m.start()]
    else:
        exc.append('paciente: número de prontuário ausente')
    reg['nome'] = re.sub(r'\s+', ' ', v).strip()


def extrai_cidade(v, reg, exc):
    m = re.search(r'C[ÓO]?D[.:]?\s*(?:IBGE)?\s*[.:]?\s*(\d{6,7})', v, re.I)
    if m:
        cod = m.group(1)
        reg['cod_ibge_origem'] = cod
        reg['cod_ibge_digitos'] = len(cod)
        v = v[:m.start()] + v[m.end():]
    else:
        exc.append('cidade: código IBGE ausente')
    m = re.search(r'CEP\s*[.:]?\s*([\d.\- ]{8,12})', v, re.I)
    if m:
        cep = re.sub(r'\D', '', m.group(1))
        reg['cep'] = cep
        reg['cep_formato_origem'] = m.group(1).strip()
        if len(cep) != 8:
            exc.append(f'cep: {len(cep)} dígitos em "{m.group(1).strip()}"')
        elif cep.endswith('000'):
            reg['cep_classe'] = 'possivelmente genérico do município'
        else:
            reg['cep_classe'] = 'específico'
        v = v[:m.start()] + v[m.end():]
    else:
        exc.append('cidade: CEP ausente')
    cid = re.sub(r'\s+', ' ', v).strip(' .:-/')
    m = re.search(r'[\s\-]+([A-Z]{2})$', cid)
    if m and m.group(1) in ('GO', 'MG', 'MT', 'MS', 'SP', 'BA', 'DF'):
        reg['uf'] = m.group(1)
        cid = cid[:m.start()]
    else:
        reg['uf'] = 'GO'
        reg['uf_presumida'] = True
    reg['municipio'] = cid.strip(' -')
    reg['municipio_normalizado'] = sem_acento(reg['municipio']).upper()


def extrai_documentos(v, reg, exc):
    cpfs = re.findall(r'\b(\d{3}[.\s]?\d{3}[.\s]?\d{3}[-.\s]?\d{2})\b', v)
    if cpfs:
        cpf = re.sub(r'\D', '', cpfs[0])
        reg['cpf'] = cpf
        reg['cpf_valido'] = valida_cpf(cpf)
        v = v.replace(cpfs[0], ' ', 1)
    else:
        exc.append('documentos: CPF não localizado')
    m = re.search(r'RG\s*[.:]?\s*([\d.\-]+)', v, re.I)
    if m:
        reg['rg'] = re.sub(r'\D', '', m.group(1))
        v = v[:m.start()] + v[m.end():]
    m = re.search(r'(?:ORG[ÃÂA]?O?\.?\s*EXPEDIDOR\s*[.:]?)?\s*([A-Z]{2,6}\s*[-\s]?\s*[A-Z]{2})\s*$',
                  v.strip(), re.I)
    if m:
        reg['orgao_expedidor'] = re.sub(r'\s+', '', m.group(1).upper())
    reg['tem_rg'] = 'rg' in reg
    if reg.get('rg') and reg.get('cpf') and reg['rg'] == reg['cpf']:
        reg['rg_e_cin'] = True          # regra ND-36
        reg.pop('rg')


def extrai_convenio(v, reg, exc):
    m = re.search(r'CNS\s*[.:]?\s*([\d.\s]{15,25})', v, re.I)
    if m:
        cns = re.sub(r'\D', '', m.group(1))
        reg['cns'] = cns
        reg['cns_digitos'] = len(cns)
        reg['cns_valido'] = valida_cns(cns)
        v = v[:m.start()] + v[m.end():]
    else:
        exc.append('convenio: CNS ausente')
    reg['convenio'] = re.sub(r'[\s/:]+', ' ', v).strip(' /:')


def extrai_inicio(v, reg, exc):
    if isinstance(v, (datetime.datetime, datetime.date)):
        reg['inicio_tratamento'] = v.date() if isinstance(v, datetime.datetime) else v
        return
    m = re.search(r'CID\s*[.:]?\s*N?[ºo°]?\s*[-:]?\s*([A-Z0-9.\-]*)', v, re.I)
    if m:
        reg['cid_presente'] = True
        reg['cid_descartado'] = m.group(0).strip()
        v = v[:m.start()]
    reg['inicio_tratamento'] = parse_data(v, exc, 'inicio_tratamento')


PADRAO_FONE = re.compile(r'(?:\(\s*\d{2}\s*\)\s*)?\d[\d\s.\-]{6,}\d')


def extrai_telefone(v, reg, exc):
    fones, resto, pos = [], [], 0
    for m in PADRAO_FONE.finditer(v):
        rot = v[pos:m.start()].strip(' /,-()')
        digitos = re.sub(r'\D', '', m.group(0))
        if len(digitos) < 8:
            pos = m.end()
            continue
        fones.append({'bruto': m.group(0).strip(), 'digitos': digitos,
                      'rotulo_anterior': rot})
        pos = m.end()
    cauda = v[pos:].strip(' /,-()')
    for i, f in enumerate(fones):
        f.pop('rotulo_anterior')
        posterior = fones[i + 1]['rotulo_anterior'] if i + 1 < len(fones) else cauda
        f['rotulo'] = (posterior or '').strip(' ()/-')
        if not f['rotulo']:
            f['rotulo_ausente'] = True
        d = f['digitos']
        if len(d) == 8:
            f['tipo'], f['ddd'], f['numero'] = 'fixo', None, d
            f['ddd_ausente'] = True
        elif len(d) == 9:
            f['tipo'], f['ddd'], f['numero'] = 'celular', None, d
            f['ddd_ausente'] = True
        elif len(d) == 10:
            f['tipo'], f['ddd'], f['numero'] = 'fixo', d[:2], d[2:]
        elif len(d) == 11:
            f['tipo'], f['ddd'], f['numero'] = 'celular', d[:2], d[2:]
        else:
            f['tipo'] = 'indefinido'
            exc.append(f'telefone: {len(d)} dígitos em "{f["bruto"]}"')
    reg['telefones'] = fones
    if not fones:
        exc.append('telefone: nenhum número reconhecido')


TIPOS_LOGR = r'(AV|AVENIDA|RUA|R|VIELA|TRAVESSA|TV|ALAMEDA|AL|PRACA|PRA[ÇC]A|ROD|RODOVIA)'


def extrai_endereco(v, reg, exc):
    reg['endereco_bruto'] = v
    achou = 0
    m = re.match(r'^\s*' + TIPOS_LOGR + r'\s*[:.]?\s*', v, re.I)
    if m:
        reg['tipo_logradouro'] = m.group(1).upper()
        v2 = v[m.end():]
        achou += 1
    else:
        v2 = v
    m = re.search(r'\bQD\s*[.:]?\s*(\w+)', v2, re.I)
    if m:
        reg['quadra'] = m.group(1)
        achou += 1
    m = re.search(r'\bLT\s*[.:]?\s*(\w+)', v2, re.I)
    if m:
        reg['lote'] = m.group(1)
        achou += 1
    m = re.search(r'\bS/?N\b', v2, re.I)
    if m:
        reg['numero'] = 'S/N'
        achou += 1
    else:
        m = re.search(r'\bN[ºo°.]?\s*[:.]?\s*(\d+)', v2, re.I)
        if m:
            reg['numero'] = m.group(1)
            achou += 1
    m = re.search(r'\b(SETOR|CONJ\.?|CONJUNTO|RESIDENCIAL|JARDIM|BAIRRO|VILA)\b(.*)$',
                  v2, re.I)
    if m:
        b = re.split(r'\b(?:QD|LT)\b', m.group(0), flags=re.I)[0]
        reg['bairro'] = re.sub(r'\s+', ' ', b).strip(' .:-')
        achou += 1
    corte = len(v2)
    for pat in (r'\bN[ºo°.]?\s*[:.]?\s*\d', r'\bS/?N\b', r'\bQD\b', r'\bLT\b',
                r'\b(?:SETOR|CONJ|CONJUNTO|RESIDENCIAL|JARDIM|BAIRRO|VILA)\b'):
        mm = re.search(pat, v2, re.I)
        if mm:
            corte = min(corte, mm.start())
    nome_logr = re.sub(r'\s+', ' ', v2[:corte]).strip(' .:,-')
    if nome_logr:
        reg['logradouro'] = nome_logr
        achou += 1
    else:
        exc.append('endereco: nome do logradouro não isolado')
    reg['endereco_campos_extraidos'] = achou
    if achou < 3:
        exc.append(f'endereco: só {achou} componentes reconhecidos')


EXTRATORES = {
    'paciente': extrai_paciente, 'cidade': extrai_cidade,
    'documentos': extrai_documentos, 'convenio': extrai_convenio,
    'inicio': extrai_inicio, 'telefone': extrai_telefone,
    'endereco': extrai_endereco,
}


def main():
    ws = load_workbook(ORIGEM).active
    registros, todas_exc = [], []
    for i, bloco in enumerate(blocos(ws), 1):
        reg, exc = {'_seq': i, '_linha_inicial': bloco[0][0]}, []
        vistos = set()
        for linha, rot, val in bloco:
            campo = ROTULOS.get(norm_rotulo(rot))
            if campo is None:
                exc.append(f'rótulo desconhecido na linha {linha}: "{rot}"')
                continue
            vistos.add(campo)
            v = limpa(val)
            if campo == 'mae':
                reg['nome_mae'] = v
            elif campo == 'nascimento':
                reg['data_nascimento'] = parse_data(v, exc, 'data_nascimento')
            else:
                EXTRATORES[campo](v, reg, exc)
        faltando = set(ROTULOS.values()) - vistos
        for f in sorted(faltando):
            exc.append(f'campo ausente no registro: {f}')
        reg['_excecoes'] = exc
        registros.append(reg)
        todas_exc.extend((i, e) for e in exc)

    def js(o):
        return o.isoformat() if isinstance(o, (datetime.date, datetime.datetime)) else o

    with open('/home/claude/p1_extraido.json', 'w', encoding='utf-8') as fh:
        json.dump(registros, fh, ensure_ascii=False, indent=2, default=js)

    print(f'Registros processados: {len(registros)}')
    print(f'Registros sem exceção: {sum(1 for r in registros if not r["_excecoes"])}')
    print(f'Total de exceções: {len(todas_exc)}')
    print()
    print('--- Exceções ---')
    for seq, e in todas_exc:
        print(f'  reg {seq:>2}: {e}')
    print()
    print('--- Cobertura de extração ---')
    campos = ['nome', 'num_prontuario', 'nome_mae', 'data_nascimento', 'cpf',
              'rg', 'cns', 'municipio', 'cep', 'cod_ibge_origem', 'convenio',
              'inicio_tratamento', 'numero', 'bairro']
    for c in campos:
        n = sum(1 for r in registros if r.get(c) not in (None, '', []))
        print(f'  {c:<20} {n:>2}/{len(registros)}')
    n = sum(len(r.get('telefones', [])) for r in registros)
    print(f'  {"telefones (total)":<20} {n:>2}')
    print()
    print('--- Sinalizações ---')
    print('  CID presente (descartar):',
          sum(1 for r in registros if r.get('cid_presente')))
    print('  CEP possivelmente genérico:',
          sum(1 for r in registros if r.get('cep_classe', '').startswith('poss')))
    print('  IBGE com 6 dígitos (falta DV):',
          sum(1 for r in registros if r.get('cod_ibge_digitos') == 6))
    print('  UF presumida GO:',
          sum(1 for r in registros if r.get('uf_presumida')))
    print('  Telefones sem DDD:',
          sum(1 for r in registros for f in r.get('telefones', [])
              if f.get('ddd_ausente')))
    print('  CNS com 15 dígitos:',
          sum(1 for r in registros if r.get('cns_digitos') == 15))


if __name__ == '__main__':
    main()
