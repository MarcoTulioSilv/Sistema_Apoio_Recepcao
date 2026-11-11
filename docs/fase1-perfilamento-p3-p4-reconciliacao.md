# Fase 1 — Perfilamento de P3 e P4 e Teste de Reconciliação

**Versão:** 1.0
**Data:** 08/09/2026
**Base:** `PLANILHA_ENTRADA_DE_PACIENTES.xls` (P4) e `ÓBITOS_ALTAS_TRANF_TRANSPLANTES.xlsx` (P3)
**Natureza dos arquivos:** dados reais, não despersonalizados — ver §0

---

## 0. Aviso — os arquivos contêm dados reais

Diferente da amostra de P1, estes dois arquivos vieram com dados reais de pacientes: nomes
completos, CPF, CNS e datas. São dados pessoais sensíveis de saúde, com titulares identificados.

Todo o perfilamento a seguir foi feito em agregado. Nenhum nome, documento ou valor individual é
reproduzido neste relatório.

**Recomendações:**

1. Excluir os arquivos e esta conversa após o uso, para reduzir o período de exposição.
2. Para as próximas rodadas, aplicar a mesma despersonalização usada em P1.
3. Registrar internamente o ocorrido. Não é incidente de segurança, mas é um compartilhamento de
   dado sensível com terceiro fora do ambiente da clínica — exatamente o cenário que o contrato do
   art. 39 (risco **R-10**) existe para disciplinar. Enquanto esse contrato não existir, o
   compartilhamento não tem instrumento que o suporte.
4. Adotar como prática: dado sensível só sai do ambiente da clínica despersonalizado, e a
   despersonalização é verificada por rotina, não a olho.

---

## 1. P4 — Entrada de pacientes

### 1.1 Estrutura

| Característica | Valor |
|---|---|
| Abas | 1 (`Plan1`) |
| Linhas totais | 701 |
| Cabeçalho | Linha 2 — a linha 1 traz um `2009` solto |
| Colunas | 9: `PRONT.`, `ENT`, `PACIENTE`, `CARTÃO SUS`, `CPF`, `CIDADE`, `CEP`, `CNES`, `PLANO` |
| Linhas com paciente | 567 |
| Pacientes distintos por nome | 557 — **9 nomes repetidos** |

Ao contrário de P1, P4 **é tabular**. A extração é direta.

### 1.2 Preenchimento

| Coluna | Preenchida | Distintos |
|---|---|---|
| PRONT. | 566 | 565 |
| ENT | 567 | 513 |
| PACIENTE | 567 | 558 |
| CARTÃO SUS | 660 | 561 |
| CPF | 562 | 549 |
| CIDADE | 566 | 32 |
| CEP | 524 | 238 |
| CNES | 562 | 23 |
| PLANO | 564 | 22 |

Número de prontuário: **1 duplicado** e 1 valor não numérico. Faixa de 3 a 793.

**Nota:** com a confirmação de que `Nº PT` de P1 e `PRONT.` de P4 são a mesma numeração, o
prontuário passa a ser a chave de junção entre as duas — muito mais confiável que o nome. As
análises deste relatório usaram nome porque a amostra de P1 tem apenas 10 registros; a execução
sobre a base completa deve usar o prontuário.

### 1.3 A coluna `PLANO` faz três trabalhos

Este é o principal achado estrutural de P4. A coluna guarda, na mesma posição, coisas de natureza
diferente:

| O que aparece | Valores observados | Ocorrências |
|---|---|---|
| **Pagador** | SUS, IPASGO, UNIMED, BRF, CONV., SSUS | 324 |
| **Evento de saída** | ÓBITO/OBITO, ALTA, TRANSPLANTE, TRANSFERÊNCIA, DESISTÊNCIA | 240 |
| **Modalidade de tratamento** | PERITONIAL | 1 |
| Vazio | — | 135 |

Consequências:

- **P4 não tem campo de convênio confiável.** Quem saiu perdeu o registro do pagador, porque o
  evento sobrescreveu o valor.
- **P4 não tem campo de situação confiável.** Quem continua ativo não tem status; quem saiu tem o
  status no lugar do pagador.
- A grafia é livre. "Transferência" aparece em **nove formas distintas**: `TRANSFERENCIA`,
  `TRANSFER`, `TRANSF.`, `TRANSF`, `TRANSFEREN`, `TRANSFER.`, `TRANS`, `TRANF`, `TRANSP`. Óbito em
  duas. A normalização exige dicionário, não comparação direta.
- **`DESISTÊNCIA` é um quinto tipo de evento**, ausente da lista declarada na reunião inicial
  (óbito, alta, transferência, transplante). Precisa entrar no domínio.
- **`PERITONIAL` sugere diálise peritoneal**, modalidade distinta da hemodiálise. Se a clínica
  atende as duas, isso é informação de escopo que não apareceu até agora (§5).

### 1.4 Datas de entrada

563 das 567 datas foram reconhecidas. Distribuição por ano de 2009 a 2026, com crescimento
consistente. Três valores são claramente errôneos: anos **214**, **1935** e **1964** — erros de
digitação que a validação de faixa plausível pega automaticamente.

---

## 2. P3 — Eventos

### 2.1 Estrutura

Quatro abas úteis (`OBITO`, `ALTA`, `TRANFERENCIA`, `TRANSPLANTE`) e três vazias
(`Plan1`, `Plan2`, `Plan3`).

**P3 também não é tabular.** Cada aba é segmentada por ano: um cabeçalho com o ano, seguido dos
registros daquele ano, repetido para cada exercício de 2010 a 2026.

| Aba | Registros | Blocos de ano | Colunas |
|---|---|---|---|
| ÓBITO | 375 | 35 | 10 |
| ALTA | 37 | 25 | 3 |
| TRANSFERÊNCIA | 50 | 32 | 6 |
| TRANSPLANTE | 44 | 27 | 7 |
| **Total** | **506** | — | — |

Particularidades:

- **O ano está no cabeçalho do bloco, não na linha do registro.** Um importador que leia linha a
  linha perde o exercício. É preciso manter estado ao percorrer.
- Existem **linhas-sentinela** de texto (`NÃO HOUVE ALTA`, `NÃO HOUVE TRANFERÊNCIA`) que precisam
  ser ignoradas sem virar registro.
- O número de colunas varia por aba: de 3 a 10.
- A posição do nome varia: coluna 2 na aba de óbitos, coluna 1 nas demais.

### 2.2 Qualidade das datas

| Aba | Data real | Data como texto | Ausente ou `????` |
|---|---|---|---|
| ÓBITO | 339 | 10 | 30 |
| ALTA | 13 | 21 | 6 |
| TRANSFERÊNCIA | 25 | 15 | 10 |
| TRANSPLANTE | 19 | 15 | 10 |

**56 eventos sem data utilizável**, alguns registrados literalmente como `????`. Isso é relevante
porque a data do evento é o que fecha o período de tratamento. Sem ela, o período fica aberto.

---

## 3. Teste de reconciliação — resultado

O critério de aceitação definido anteriormente: o número de pacientes ativos derivado da
reconciliação deve ser exatamente **139**.

### 3.1 Execução

Três métodos foram testados sobre a base completa:

| Método | Ativos derivados | Esperado |
|---|---|---|
| Pela coluna `PLANO` de P4 (quem tem pagador, não evento) | 324 | 139 |
| Por ausência de evento em P3, casando nome exato | 378 | 139 |
| **União dos dois, com casamento aproximado de nome** | **241** | **139** |

O melhor resultado erra por **102 pacientes**, ou 73% a mais que o real.

### 3.2 Por que falha

O casamento de nomes entre P3 e P4 explica parte:

| Situação | Quantidade |
|---|---|
| Nomes de eventos em P3 com par exato em P4 | 179 (36%) |
| Com par apenas aproximado (provável diferença de grafia) | 67 |
| **Sem qualquer par em P4** | **253** |

Mas o problema de fundo não é grafia. É de completude, e o balanço aritmético mostra isso:

```
eventos de saída registrados em P3        506
pacientes ativos informados pela clínica  139
                                          ---
entradas necessárias para fechar          645
entradas efetivamente registradas em P4   557
                                          ---
entradas faltantes em P4              pelo menos  88
```

**P4 não é um registro completo de pacientes.** Faltam pelo menos 88 entradas, e provavelmente
mais, já que P3 começa em 2010 e a clínica é anterior a isso.

### 3.3 Conclusão

**O critério de aceitação de 139 não pode ser atingido reconciliando P3 e P4.** Não é um defeito do
algoritmo; é uma limitação dos dados. Insistir na reconciliação como fonte da lista de ativos
produziria uma base com mais de duzentos pacientes, a maioria dos quais já não frequenta a clínica.

Isso não invalida o critério — invalida a **fonte**. O critério continua sendo o teste correto; ele
precisa ser aplicado a outra base.

---

## 4. Estratégia de migração revisada

A conclusão acima leva a uma inversão do papel das planilhas.

| Planilha | Papel anterior | **Papel revisado** |
|---|---|---|
| P1 — endereços e telefones | Fonte de dados cadastrais | **Fonte da verdade sobre quem está ativo** |
| P4 — entradas | Fonte dos períodos de tratamento | Histórico de entradas, **reconhecidamente parcial** |
| P3 — eventos | Fonte dos períodos de tratamento | Histórico de saídas, **mais completo que P4** |

O raciocínio: P1 é a ficha operacional que a recepção usa no dia a dia. É a única das três que tem
motivo para conter exatamente os pacientes correntes — ninguém mantém endereço e telefone
atualizados de quem já saiu.

**Premissa a confirmar:** se P1 tiver aproximadamente 139 registros, a hipótese se confirma e a
migração fica muito mais simples do que parecia. É a primeira coisa a verificar (§5).

### 4.1 Sequência proposta

1. **Carregar P1** como base de pacientes ativos. O critério de 139 passa a ser aplicado aqui — e é
   verificável antes de escrever qualquer código de reconciliação.
2. **Anexar o histórico de entrada** a partir de P4, casando por **número de prontuário**, não por
   nome. Onde não houver correspondência, o período fica com início desconhecido e marcado.
3. **Carregar os eventos de P3** como histórico, com casamento por nome e revisão das exceções.
   Eventos sem par em P4 correspondem a pacientes que a base não alcança e devem ser preservados
   como registro histórico, não descartados.
4. **Não tentar fechar a aritmética.** A base histórica é incompleta por natureza e deve ser
   apresentada como tal. Um relatório de entradas por período anterior a 2010 será
   sistematicamente subestimado, e isso precisa estar documentado para que ninguém tire conclusão
   errada dele.

### 4.2 O que isso muda no risco

**R-15** (reconciliação produzir períodos incorretos) deixa de ser risco de execução e passa a ser
**limitação conhecida e documentada**. É um resultado melhor: um risco aceito e declarado é
gerenciável; um erro silencioso de 102 pacientes na base ativa, não.

---

## 5. Requisitos derivados

| ID | Necessidade |
|---|---|
| **ND-51** | Situação do paciente é campo próprio, independente do pagador. A sobreposição dos dois em P4 é a causa da perda de informação de convênio dos pacientes que saíram |
| **ND-52** | Domínio de eventos inclui **desistência**, além de óbito, alta, transferência e transplante |
| **ND-53** | Dicionário de normalização para os valores livres de P4 — nove grafias de "transferência" precisam convergir para um único código |
| **ND-54** | Marcação de completude no histórico: período com início desconhecido, evento sem data, paciente sem entrada correspondente |
| **ND-55** | Validação de faixa plausível para datas na importação — anos 214 e 1935 devem virar exceção, não registro |
| **ND-56** | Importador de P3 sensível a bloco: o ano vem do cabeçalho da seção, não da linha, e linhas-sentinela de texto não são registros |

---

## 6. Questões abertas

1. **Quantos registros tem P1?** Se for próximo de 139, a estratégia do §4 se confirma e a migração fica direta.
2. **A clínica atende diálise peritoneal**, além de hemodiálise? O valor `PERITONIAL` em P4 sugere que sim. Se atende, a modalidade é atributo do período de tratamento e muda a alocação em escala — paciente de peritoneal não ocupa turno de máquina.
3. **`DESISTÊNCIA` deve ser mantida** como tipo de evento no sistema novo?
4. Qual das planilhas a recepção considera hoje a fonte da verdade, quando duas discordam?
5. Os 9 nomes repetidos em P4 são homônimos ou reentradas do mesmo paciente? O prontuário resolve — vale conferir na base completa.

---

*Próximo passo: confirmar a contagem de P1 e executar a carga de teste em ambiente isolado, com dados despersonalizados.*
