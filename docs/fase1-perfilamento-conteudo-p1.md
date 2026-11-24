# Fase 1 — Perfilamento de Conteúdo e Especificação de Extração
## Planilha P1 — Endereços e telefones dos pacientes

**Versão:** 1.0
**Data:** 08/09/2026
**Base:** amostra despersonalizada com 10 registros
**Artefato associado:** `extrator_p1.py` — extrator de referência, validado contra a amostra

---

## 1. Correção ao relatório anterior

O relatório de perfilamento estrutural (v0.2) concluiu, a partir da lista de cabeçalhos, que
**P1 não possuía identificadores fortes** e que a ligação com P4 dependeria de casamento por nome.

**Isso estava errado.** A lista de rótulos não revelava que várias células contêm **múltiplos campos
concatenados**. Com a amostra, verifica-se que P1 contém:

| Identificador | Onde está | Presença na amostra |
|---|---|---|
| **Número de prontuário** | Dentro da célula de `PACIENTE`, como `Nº PT: nnnn` | 10/10 |
| **CPF** | Dentro de `DOC.PESSOAIS` | 10/10 |
| **CNS** | Dentro de `CONVÊNIO` | 10/10 |

**Consequência:** o risco central da migração muda de patamar. A ligação P1 ↔ P4 pode ser feita por
número de prontuário e conferida por CPF e CNS — três chaves independentes, não uma aproximação por
nome. O risco **R-15** cai de alto para baixo no que diz respeito a P1.

**O que não muda:** P3 (eventos) continua tendo apenas o nome do paciente. Ela segue sendo o elo
frágil da migração, e agora é o único.

---

## 2. Estrutura física real

P1 **não é uma tabela**. É um conjunto de fichas.

| Característica | Observação |
|---|---|
| Colunas | Duas. Coluna A = rótulo, coluna B = valor |
| Registro | Bloco de 9 linhas |
| Separador | Uma linha inteiramente vazia |
| Células mescladas | Nenhuma |
| Ordem dos campos | **Variável** — 1 registro em 10 traz o endereço na última linha, não na quarta |

Um importador posicional falharia. A extração precisa ser **dirigida por rótulo**, não por posição.

### 2.1 Variação dos rótulos

Na amostra de 10 registros, 9 campos produziram **14 grafias distintas**:

| Campo canônico | Grafias observadas |
|---|---|
| paciente | `PACIENTE:`, `PACIENTE` |
| mãe | `NOME DA MÃE:`, `NOME MÃE:` |
| nascimento | `DATA DE NASC:`, `DATA NASC:`, **`DATA DE MASC:`** (erro de digitação) |
| cidade | `CIDADE/CEP:`, `CIDADE /CEP:`, `CIDADE:` |
| convênio | `CONVÊNIO:`, `CONVENIO:`, `CONVÊNIO: ` |
| documentos | `DOC.PESSOAIS:`, `DOC.PESSOAIS: ` |
| telefone | `TELEFONE:`, `TELEFONE` |
| início | `INICIO TRATAM:`, `INICIO TRATAM: ` |

Se 10 registros produzem essa variedade, os 139 produzirão mais. O importador precisa normalizar
acento, pontuação e espaço, e **falhar explicitamente** diante de rótulo desconhecido — nunca
ignorar em silêncio.

---

## 3. Campos compostos

Cinco das nove células contêm mais de um dado:

| Célula | Contém | Exemplo de estrutura |
|---|---|---|
| `PACIENTE` | nome + número de prontuário | `NOME COMPLETO   Nº PT: 0314` |
| `CIDADE/CEP` | município + UF (às vezes) + CEP + código IBGE | `JATAI -GO   CEP: 75800971   CÓD.IBGE: 521190` |
| `DOC.PESSOAIS` | CPF + RG + órgão expedidor | `CPF: ...  RG: ...  ORGÃO EXPEDIDOR: SSP-GO` |
| `CONVÊNIO` | convênio + CNS | `SUS   CNS: 000.000.000.000.000` |
| `INICIO TRATAM` | data + **CID** | `22/03/2018   CID N-000` |
| `TELEFONE` | 1..4 números + nome do contato + parentesco | `(64) 9....  NOME DO CONTATO (esposa)  (64) 9....  NOME DO CONTATO (filha)` |

---

## 4. Achados por campo

### 4.1 Número de prontuário — a chave que faltava

Rótulo interno com quatro grafias: `Nº PT:`, `NºPT:`, `NºPT: `, `NºPT `. Valores com 4 dígitos e
zeros à esquerda, exceto um com 3 dígitos (`551`).

**Requisito:** armazenar como **texto**, preservando os zeros à esquerda, e manter uma forma
numérica à parte apenas para conferência com P4. Converter para inteiro na carga destruiria o
formato e criaria divergência falsa com a outra planilha.

### 4.2 Datas — dois tipos no mesmo campo

`DATA DE NASC` veio como data real em 10/10. Já `INICIO TRATAM` veio como data real em 4 registros e
como **texto** em 6 — justamente os que têm CID concatenado, o que converteu a célula em texto.

Formatos de texto observados: `22/03/2018`, `3/6/2016`, `13/03/2024`, `06/11/2018`, `09/06/2020`.
Sem preenchimento de zero, e com ambiguidade aparente entre dia e mês.

**A ambiguidade se resolve:** o registro `13/03/2024` só admite leitura dia/mês. A convenção da
planilha é **dd/mm/aaaa**. Deve ser aplicada uniformemente, e qualquer data que falhe nessa leitura
vira exceção, não tentativa de interpretação alternativa.

### 4.3 CID — dado clínico dentro de uma planilha administrativa

6 dos 10 registros trazem CID concatenado à data de início: `CID N-000`, `CID.Nº000`, `CID:000`,
`CID:Nº000`.

Isso é **diagnóstico**, portanto dado clínico. O escopo declarado exclui prontuário e conteúdo
clínico, e o campo não tem uso administrativo na recepção.

**Recomendação: não migrar o CID.** Descartar na extração, com contagem registrada. É aplicação
direta da minimização (art. 6º, III da LGPD): um dado que não serve à finalidade declarada não deve
ser tratado. Migrá-lo ampliaria a sensibilidade da base sem nenhum ganho operacional.

### 4.4 Telefone — a estrutura de contato já existe no legado

25 números em 10 registros, de 1 a 4 por paciente. E o campo carrega **muito mais que números**:

| Conteúdo observado | Exemplos |
|---|---|
| Parentesco | esposa, esposo, mãe, pai, filha, irmã, neta, padrasto |
| Nome do contato | primeiros nomes próprios (seis na amostra; omitidos aqui) |
| Titularidade | PACIENTE, PESSOA |
| Tipo de local | RESIDENCIA, FAZENDA |

**Isso resolve ND-07.** O contato de responsável não precisa ser coletado do zero — ele está aí,
em texto livre. O modelo de telefone precisa ser `número + tipo + nome do contato + parentesco`,
não uma lista de números.

Formatos de número: `(00) 00000.0000`, `(00)00000-0000`, `(00) 0 - 0000-0000`, `00000.0000`,
`000000000`, `3663.0000`. Comprimentos de 8 a 11 dígitos.

**4 números vieram sem DDD.** Como todos os pacientes residem em Goiás e a clínica atende a região
de Jataí, o DDD pode ser presumido — mas a presunção precisa ficar **marcada no registro**, para
que ninguém a confunda com dado conferido.

**Ambiguidade residual:** em um registro, o rótulo aparece *antes* do número em vez de depois.
A regra geral — rótulo é o texto que segue o número — acertou 21 de 25. Os casos restantes precisam
de revisão humana, e o extrator os sinaliza em vez de adivinhar.

### 4.5 Cidade, CEP e código IBGE

**Município:** acentuação inconsistente entre registros (`CAIAPONIA` e `CAIAPÔNIA` na mesma base).
Exige normalização sem acento para casamento com a tabela oficial.

**UF:** presente em 5 de 10, em quatro grafias (`-GO`, ` -GO`, `-GO`, ` GO`). Nos outros 5, ausente.
Como todos residem em Goiás, presumir GO é seguro — marcando a presunção.

**CEP:** 8 dígitos em 10/10, mas com três separadores diferentes (`75850-000`, `75805640`,
`75804.568`). Confirmada a heterogeneidade semântica: 3 registros terminam em `000`, padrão de CEP
genérico de município; 7 são específicos de logradouro.

**Código IBGE:** aqui há um achado técnico relevante. Todos os 10 registros trazem **6 dígitos**
(`521190`, `520440`, `522050`). O código municipal oficial do IBGE tem **7 dígitos**, sendo o último
um dígito verificador. A planilha guarda a forma reduzida.

**Requisito:** armazenar os 7 dígitos. A conversão não é aritmética simples e deve ser feita por
consulta à tabela oficial de municípios, não por cálculo — o que também valida o código de quebra.

### 4.6 Documentos pessoais

CPF presente em 10/10, sendo que **um registro não traz o rótulo `CPF:`** — apenas o número solto.
A extração não pode depender do rótulo; precisa reconhecer o padrão.

RG presente em 9/10, com órgão expedidor em 8, escrito de seis formas diferentes
(`ORG. EXPEDIDOR:`, `ORGÃO EXPEDIDOR:`, `ORGÂO EXPEDIDOR:`, e sem rótulo nenhum).

Órgãos de várias unidades da federação: `SSP-GO`, `SSPI-GO`, `PCI-GO`, `DGPC-GO`, `SSP-SP`,
`SSPI-BA`, `SSPDI-RS`. Coerente com pacientes que residem em Goiás mas nasceram em outros estados —
não contradiz a definição de UF única de residência.

A regra ND-36 (descartar o RG quando for igual ao CPF, por se tratar de CIN) está implementada e não
teve ocorrência nesta amostra, o que é esperado: são cadastros antigos, anteriores à emissão do novo
documento.

### 4.7 Convênio

Dois valores na amostra: `SUS` (9) e `IPASGO` (1). Um registro traz `SUS:` com dois-pontos, outro
usa `/` como separador antes do CNS. Domínio pequeno e normalizável sem dificuldade.

---

## 5. Resultado do extrator de referência

O extrator implementa as regras acima e foi executado contra a amostra.

| Campo | Extraídos |
|---|---|
| nome, número de prontuário, nome da mãe, data de nascimento | 10/10 |
| CPF, CNS, município, CEP, código IBGE, convênio, início do tratamento | 10/10 |
| RG | 9/10 (um registro não possui) |
| número do endereço | 10/10 |
| bairro | 9/10 |
| telefones | 25 números |

**Exceções: zero.**

### 5.1 Por que "zero exceções" não significa "extração correta"

Vale registrar o que aconteceu durante a construção do extrator, porque é a lição prática mais útil
deste perfilamento.

A primeira versão também reportou zero exceções — e estava **errada**. Ela atribuía a cada telefone
o rótulo que o *precedia*, quando na planilha o rótulo *segue* o número. Resultado: em um registro,
o telefone da esposa foi rotulado como residência, e o da filha recebeu o nome da esposa. Nenhum
erro foi lançado, porque a estrutura estava perfeita. Só a semântica estava trocada.

O mesmo ocorreu com o endereço: o nome do logradouro simplesmente não era extraído, e o bairro
absorvia o restante da string, incluindo quadra e lote.

**Consequência para o plano de migração:** a validação da carga não pode se apoiar em contagem de
erros. Precisa incluir **conferência amostral campo a campo, feita por quem conhece os pacientes.**
Trinta registros conferidos manualmente pela recepção valem mais do que qualquer contador de
exceções.

### 5.2 Limites conhecidos do endereço

O endereço é o campo com menor taxa de estruturação confiável. Casos observados:

| Registro | Problema |
|---|---|
| 1 | Trecho `COMERCIO CENTRO` fica sem destino — pode ser complemento ou o bairro real |
| 5 | Bairro `CYLINEO FRANÇA` não é reconhecido, por não conter palavra-chave (`SETOR`, `JARDIM`, `CONJ`) |
| 8 | Origem grafada `RUA: Av. Cel Lindolfo Alves Dias` — dois tipos de logradouro no mesmo valor |

Estimativa realista: **70% a 80% dos endereços saem completamente estruturados**; o restante exige
revisão. Isso confirma a estimativa preliminar do relatório anterior e reforça a estratégia de
pendências progressivas (ND-43): o endereço incompleto entra na lista de pendências da recepção e é
corrigido quando o paciente comparece.

---

## 6. Requisitos derivados deste perfilamento

| ID | Necessidade |
|---|---|
| **ND-44** | Telefone modelado como `número + DDD + tipo + nome do contato + parentesco`. A informação já existe no legado e não pode ser descartada na carga |
| **ND-45** | CID descartado na extração, com contagem registrada. Minimização (art. 6º, III) |
| **ND-46** | Código IBGE armazenado com 7 dígitos, obtido por consulta à tabela oficial de municípios, nunca por cálculo |
| **ND-47** | Marcação de dado presumido — DDD e UF inferidos precisam ser distinguíveis de dado conferido |
| **ND-48** | Número de prontuário armazenado como texto, preservando zeros à esquerda |
| **ND-49** | Importador dirigido por dicionário de rótulos, com falha explícita diante de rótulo não mapeado |
| **ND-50** | Conferência amostral manual da carga, por pessoa da recepção, como critério de aceitação — não apenas contagem de exceções |

---

## 7. Alerta sobre a amostra

Um dos registros da amostra despersonalizada contém um **número de telefone real**, no formato
`(64) 0000.0000` (número omitido aqui), enquanto os demais foram substituídos por zeros. Aparentemente passou pela
despersonalização.

Não é grave neste caso, mas vale o registro por dois motivos: o arquivo foi compartilhado fora do
ambiente da clínica, e o episódio ilustra por que a despersonalização de dados sensíveis precisa ser
verificada por processo automatizado, e não apenas visualmente. Se for usar a mesma rotina para
gerar amostras maiores, vale conferir.

---

## 8. Próximos passos

1. Confirmar que `Nº PT` de P1 e `PRONT.` de P4 são a mesma numeração — é a premissa que sustenta a conclusão do §1.
2. Receber amostras de P3 (eventos) e P4 (entradas) para completar o perfilamento.
3. Executar o extrator sobre a base completa e produzir o relatório de exceções real.
4. Rodar o teste de reconciliação: pacientes ativos derivados devem somar exatamente 139.

---

*Artefato associado: `extrator_p1.py`. É referência de validação das regras, não código de produção —
não contém tratamento de erro, log de auditoria nem os controles de segurança da §5 do documento de Fase 0.*
