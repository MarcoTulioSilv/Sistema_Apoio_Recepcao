# Fase 1 — Especificação de Migração

**Versão:** 1.0
**Data:** 10/09/2026
**Supersede:** a estratégia de reconciliação do §4 de `fase1-perfilamento-p3-p4-reconciliacao.md`

---

## 1. Decisões que definem o escopo da migração

| ID | Decisão | Efeito |
|---|---|---|
| **DEC-13** | **P1 é a fonte da verdade.** P4 e P3 apenas complementam | Elimina a disputa de precedência entre planilhas |
| **DEC-14** | **O histórico começa na implantação.** Pacientes e eventos anteriores ficam fora do sistema, rastreados manualmente pelo acervo físico da clínica | Reduz drasticamente o escopo e o risco da carga |
| **DEC-15** | Modalidade de diálise está fora de escopo. A ocorrência de `PERITONIAL` em P4 é ignorada | Nenhum campo de modalidade |
| **DEC-16** | **Desistência** é mantida como tipo de evento | Domínio com cinco tipos |
| **DEC-17** | Duplicidades são resolvidas pela **tríade** nome + data de nascimento + nome da mãe, com base em P1 | Critério único de identidade |

### 1.1 O que DEC-14 realmente elimina

É a decisão de maior impacto de toda a Fase 1. Com ela:

- **P3 deixa de ser migrada.** Todos os seus 506 eventos são anteriores à implantação. Nenhum dos 146 pacientes de P1 tem evento de saída — se tivesse, não estaria ativo.
- **P4 deixa de ser fonte de períodos de tratamento.** Passa a ser apenas uma fonte de complemento de campos.
- **O problema de reconciliação desaparece.** As 88 entradas faltantes, os 253 eventos órfãos e os 102 pacientes de divergência tornam-se irrelevantes: eram todos histórico.
- **R-15 é encerrado.** Não há mais reconciliação a errar.

O acervo físico continua sendo o registro histórico, o que é coerente com DEC-04: o papel já era o registro de origem dos documentos de prontuário.

**Consequência a documentar:** os relatórios de entrada por período e de eventos por período
**nascem vazios** e só passam a ter conteúdo a partir da data de implantação. Isso precisa estar
visível na própria tela do relatório, com a data de início da série. Sem isso, alguém vai comparar
2027 com 2026 e concluir que a clínica cresceu 400%.

---

## 2. Item aberto — 146 contra 139

P1 tem **146 pacientes cadastrados**. A clínica informou **139 ativos**. Diferença de **sete**.

As hipóteses são poucas e mutuamente exclusivas:

| Hipótese | Como confirmar |
|---|---|
| P1 contém 7 pacientes que já saíram e não foram removidos | Conferir os 7 contra a escala atual: quem não tem turno alocado, saiu |
| O número 139 está defasado e o correto é 146 | Confirmar com a recepção a contagem do dia |
| Parte dos 7 está em processo de admissão, ainda sem primeira sessão | Verificar data de início do tratamento |

**Isso precisa ser resolvido antes da carga, não depois.** Se sete registros obsoletos entrarem como
ativos, eles vão aparecer na distribuição de escala, nos relatórios e na contagem por convênio —
e o erro se propaga silenciosamente, porque nada no sistema vai acusá-lo.

O critério de aceitação fica: **a contagem de pacientes ativos carregados deve ser igual ao número
confirmado pela recepção na data da carga**, e o valor confirmado deve constar do registro de
migração. Não se fixa 139 nem 146 antes dessa conferência.

A conferência contra a escala é o método mais confiável, porque a escala é a informação que a
operação usa de fato: paciente sem turno alocado não está em tratamento.

---

## 3. Escopo da carga

### 3.1 P1 — carga principal

146 registros, no formato de ficha descrito em `fase1-perfilamento-conteudo-p1.md`.

Campos migrados: nome, número de prontuário, nome da mãe, data de nascimento, endereço, município,
UF, CEP, código IBGE, telefones com contato e parentesco, CPF, RG, órgão expedidor, CNS, convênio,
início do tratamento.

Campos descartados: **CID** (DEC-45, dado clínico fora de escopo).

### 3.2 P4 — complemento apenas

Junção pelo **número de prontuário**, confirmado como a mesma numeração de `Nº PT` em P1.

| Campo de P4 | Uso |
|---|---|
| `CNES` | Preenche a instituição referenciadora (ND-39), ausente de P1 |
| `CARTÃO SUS` | Confere o CNS de P1; divergência vira exceção |
| `CPF` | Confere o CPF de P1; divergência vira exceção |
| `CEP`, `CIDADE` | Conferem os de P1; **P1 prevalece** |
| `ENT` | Confere o início do tratamento de P1; **P1 prevalece** |
| `PLANO` | **Não usar.** A coluna mistura pagador, evento e modalidade; P1 tem o convênio limpo |

Só interessam as linhas de P4 cujo prontuário esteja entre os 146. As demais ficam fora.

### 3.3 P3 — não migrada

Nenhum evento é carregado. A tabela de eventos do sistema nasce vazia e passa a ser alimentada pela
operação, com o domínio de cinco tipos: óbito, alta, transferência, transplante e **desistência**.

### 3.4 P2 — substituída

A tabela de municípios do IBGE vem da base oficial, restrita a Goiás, com os 7 dígitos do código.
P2 serve apenas para conferência dos códigos de 6 dígitos encontrados em P1.

---

## 4. Resolução de duplicidades (DEC-17)

Aplicação da tríade **nome + data de nascimento + nome da mãe**, com P1 como base.

Os 9 nomes repetidos identificados em P4 perdem quase toda a relevância com DEC-14: só importam se
algum dos 146 tiver mais de uma linha em P4 durante o complemento.

| Situação no complemento | Ação |
|---|---|
| Prontuário de P1 casa com 1 linha de P4 | Complemento direto |
| Casa com mais de uma linha | Aplicar a tríade; se P4 não tiver dados suficientes para desempatar, usar a linha de `ENT` mais recente e registrar exceção |
| Não casa com nenhuma | Paciente segue sem instituição referenciadora, marcado como pendência (ND-43) |

Duas ressalvas sobre a tríade:

1. **P4 não tem data de nascimento nem nome da mãe.** A tríade só é aplicável dentro de P1, ou entre P1 e uma fonte que os tenha. Para desempatar linhas de P4, o critério real disponível é o prontuário mais a data de entrada.
2. Dentro de P1, a tríade serve para detectar se algum dos 146 é o mesmo paciente cadastrado duas vezes — verificação que vale rodar antes da carga, já que 146 e 139 diferem em sete.

---

## 5. Sequência de execução

| # | Passo | Critério de saída |
|---|---|---|
| 1 | Confirmar com a recepção a contagem de ativos do dia, conferida contra a escala | Número acordado e registrado |
| 2 | Rodar a tríade dentro de P1 para detectar duplicidade interna | Zero duplicatas, ou lista revisada |
| 3 | Extrair P1 em área de staging, sem transformação | 146 blocos lidos, zero rótulos desconhecidos |
| 4 | Aplicar as regras de parsing e gerar o relatório de exceções | Exceções revisadas com a recepção |
| 5 | Complementar com P4 por prontuário | Divergências de CPF e CNS revisadas |
| 6 | Conferência amostral manual de 30 registros pela recepção (ND-50) | Aprovação da recepção |
| 7 | Carga em homologação | Contagem confere com o passo 1 |
| 8 | Distribuição de escala em massa (ND-37) | 100% dos ativos com turno e dias |
| 9 | Carga em produção | Repetir a conferência de contagem |

O passo 8 depende da escala formalizada em papel antes da carga, conforme recomendado no §8.1 do
perfilamento estrutural.

---

## 6. Riscos atualizados

| ID | Risco | Situação |
|---|---|---|
| R-02 | Qualidade das planilhas inviabilizar a migração | **Reduzido.** Escopo caiu de ~1.200 linhas para 146 fichas |
| R-15 | Reconciliação produzir períodos incorretos | **Encerrado** por DEC-14 |
| **R-16** | *(novo)* Os 7 registros de diferença entre 146 e 139 entrarem como ativos | Alto até a conferência do §2. Mitigado pelo passo 1 |
| **R-17** | *(novo)* Relatórios de série histórica serem lidos como se cobrissem o passado | Médio. Mitigar exibindo a data de início da série na própria tela |
| **R-18** | *(novo)* Perda de acesso prático ao histórico anterior à implantação | Aceito por DEC-14. O acervo físico é a via de consulta |

---

## 7. Nota sobre os dados reais

Os artefatos derivados das planilhas com dados reais foram eliminados do ambiente de trabalho, e
nenhum dado pessoal foi incorporado aos documentos do projeto — todas as análises constam em
agregado. Os arquivos originais permanecem no histórico desta conversa e só podem ser removidos por
quem os enviou.

---

## 8. Pendências

1. Confirmar a contagem de ativos conferida contra a escala (§2). **Bloqueante.**
2. Definir a data de corte da implantação, que passa a ser o marco zero do histórico.
3. Confirmar se o campo `INICIO TRATAM` de P1 deve ser migrado como atributo informativo do paciente, já que o histórico de períodos não será carregado. Recomendação: sim, é dado administrativo útil e sem custo.

---

*Rastreabilidade: DEC-13 a DEC-17 encerram R-15 e abrem R-16 a R-18.*
