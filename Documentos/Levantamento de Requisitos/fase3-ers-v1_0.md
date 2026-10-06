# Especificação de Requisitos de Software (ERS)
## Sistema de Apoio à Recepção — Centro de Uro-Nefrologia, Jataí-GO

| | |
|---|---|
| **Versão** | 1.0 — para validação |
| **Data** | 29/09/2026 |
| **Norma** | ISO/IEC/IEEE 29148:2018, estrutura de especificação de requisitos de software |
| **Referencial** | SWEBOK v4.0 — Software Requirements |
| **Baseline de entrada** | Requisitos funcionais v1.1 aprovados + Emenda 01, aprovada pela gestão |
| **Situação** | Aguarda validação e assinatura (Fase 4) |

> **Precedência.** Esta ERS consolida os documentos das Fases 0 a 2 num único texto de referência
> para arquitetura, construção, testes e homologação. Em caso de divergência entre esta ERS e um
> documento anterior, prevalece a ERS. Os documentos de origem continuam válidos como registro do
> raciocínio que levou a cada requisito.

---

## Convenções

**Identificadores.** Todos os identificadores das fases anteriores foram preservados, para que a
rastreabilidade continue funcionando. Números ausentes numa sequência correspondem a itens removidos
em versões anteriores, e não são reaproveitados.

**Obrigatoriedade.** Todo requisito desta ERS é obrigatório. A entrega é integral e não há
priorização de escopo (casos de uso, §5). Por isso não há coluna de prioridade.

**Coluna "Origem".**

| Marca | Significado |
|---|---|
| B1.1 | Texto da baseline aprovada em 14/09/2026, sem alteração |
| B1.1 [R] | Requisito da baseline **refinado** na Fase 2 — ver Apêndice A.2 |
| **V4** | Alterado ou acrescentado durante a validação (Fase 4) — ver Apêndice A.3 |
| **E01** | Acrescentado ou alterado pela Emenda 01 — ver Apêndice A.1 |

**Coluna "Verif." — método de verificação.**

| Letra | Método | Quando se usa |
|---|---|---|
| I | Inspeção | Examinar configuração, código, documento ou tela, sem executar o comportamento |
| A | Análise | Cálculo, projeção ou revisão de modelo |
| D | Demonstração | Executar a função e observar o resultado, sem medição |
| T | Teste | Executar com dados preparados e comparar com resultado esperado ou alvo mensurável |

---

## 1. Introdução

### 1.1 Propósito

Especificar, de forma completa e verificável, o que o sistema deve fazer e sob quais restrições de
qualidade, segurança e legalidade, servindo de base única para a arquitetura (Macroentrega II), a
construção, os testes e a homologação.

Leitores: coordenação e direção da clínica, que validam e assinam; o desenvolvedor, que constrói; e
quem vier a manter o sistema, que precisa entender por que cada exigência existe.

### 1.2 Escopo

O sistema substitui o cadastro de pacientes hoje mantido em planilhas e apoia a rotina da recepção:
cadastro, alocação em escala, frequência por turno, eventos, guarda segura de documentos
digitalizados, emissão de documentos parametrizados, relatórios e trilha de auditoria.

**O sistema não é prontuário eletrônico.** Não fará:

- prontuário clínico, prescrição médica ou de enfermagem, evolução clínica ou exames;
- registro de parâmetros de sessão de diálise ou de máquinas;
- registro do motivo clínico da sessão extra;
- distinção entre modalidades de diálise;
- cadastro de profissionais de saúde;
- faturamento, cobrança ou envio de dados a convênios e ao SUS;
- controle de estoque, água tratada ou manutenção;
- compartilhamento ou transmissão de dados a terceiros — a saída é por consulta, relatório em tela e
  arquivo baixado pelo próprio usuário;
- substituição das fichas de frequência em papel, que continuam sendo o comprovante de faturamento;
- guarda do histórico anterior à implantação, que permanece no acervo físico.

### 1.3 Perspectiva do produto

| Aspecto | Situação |
|---|---|
| Substitui | Quatro planilhas Excel de cadastro, entradas, eventos e endereços |
| Convive com | Fichas de frequência e de cadastro em papel; acervo físico de prontuários |
| Compartilha servidor com | O sistema de estoque, cujos terminais acessam o banco dele diretamente pela rede |
| Módulo segregado | Documentos digitalizados, com permissões próprias (DEC-04). O papel permanece como registro de origem |
| Rede | Somente local. Sem acesso de entrada pela internet; saída restrita a lista de destinos (RNF-611) |
| Volume | 146 pacientes; cerca de 1 cadastro por semana; 18 lançamentos de turno por semana; 6 usuários administrativos, mais os da enfermagem |

### 1.4 Funções principais

Cadastro e localização de pacientes; contatos e telefones; cobertura por SUS ou convênio;
alocação em seis escalas com vigência; frequência por turno com confirmação e compensação de
ausências; eventos que encerram o tratamento; digitalização segura e guarda de documentos por vinte
anos; emissão de sete documentos parametrizados e do crachá; relatórios com exportação auditada;
pendências por perfil; carga inicial dos dados das planilhas.

### 1.5 Usuários

| Perfil | Atribuições | Acesso a dado de paciente |
|---|---|---|
| Recepcionista | Usuário principal: cadastro, frequência, digitalização, emissão | Sim |
| Administração | Tudo da recepção, mais relatórios completos, exportação e autorizações | Sim |
| Visualizador | Somente consulta | Sim, leitura |
| TI | Usuários, configuração, backup, verificação da cadeia de auditoria | **Não** (RF-1004) |
| Enfermagem | Gestão das escalas: alocação, trocas de turno pontuais e permanentes, sessões extras | Sim — identificação, escala, frequência e relatórios de sessões (RF-901, 906, 908, 916). Sem módulo de documentos e sem relatórios de cadastro (DEC-55) |
| *Tempo* | Ator não humano: a passagem do horário abre a sessão de turno | — |

A enfermagem registra diretamente a gestão das escalas (DEC-48). Quando o que ela registra exige termo
assinado — troca pontual ou sessão extra —, a recepção recebe a pendência de emitir o documento,
imprimir e colher as assinaturas (RF-809). A recepção continua lançando a frequência.

### 1.6 Limitações

- Todo o cadastro é dado pessoal sensível de saúde: o vínculo com uma clínica de hemodiálise revela
  doença renal crônica (LGPD, art. 5º, II, e art. 11).
- Documentos de prontuário têm guarda mínima de vinte anos (Lei nº 13.787/2018).
- A clínica opera todos os dias da escala, inclusive feriados, das 06:00 às 20:00.
- Uma única pessoa desenvolve, opera e mantém o sistema (R-25).

### 1.7 Premissas e dependências

| # | Premissa ou dependência | Bloqueia |
|---|---|---|
| 1 | Servidor dedicado conforme a viabilidade §2, em local fechado e sem uso diário | Homologação e produção |
| 2 | Arquitetura de aplicação servidora acessada por navegador nas estações. Se a Macroentrega II escolher outro estilo, as §3.1, 3.6 e os requisitos RNF-614, RNF-616 e RNF-618 precisam ser revistos | — |
| 3 | Webcam adquirida | Homologação do crachá |
| 4 | Logotipo e dados institucionais fornecidos, sem o fax | Homologação da emissão |
| 5 | Ficha de cadastro em papel revisada, com a frase informativa de DEC-46 | Go-live |
| 6 | Títulos próprios para os documentos hoje intitulados "Termo de Responsabilidade" | Homologação da emissão |
| 7 | Pendências jurídicas PJ-05 e PJ-06 resolvidas (§3.8.4) | Go-live |

---

## 2. Referências

### 2.1 Normas e referenciais

| Referência | Uso nesta ERS |
|---|---|
| ISO/IEC/IEEE 29148:2018 | Estrutura e critérios de qualidade dos requisitos |
| ISO/IEC 25010:2023 | Modelo de qualidade dos requisitos não funcionais |
| SWEBOK v4.0 | Referencial de engenharia de software do projeto |
| STRIDE e LINDDUN | Modelagem de ameaças e de privacidade |
| WCAG 2.1 | Acessibilidade (RNF-406) |

### 2.2 Legislação

| Norma | Incidência |
|---|---|
| Lei nº 13.709/2018 — LGPD | Bases legais, direitos do titular, segurança, retenção |
| Lei nº 13.787/2018 | Digitalização e guarda de prontuário por vinte anos |
| Guia orientativo da ANPD sobre agentes de tratamento | Empregado não é operador (PJ-08) |
| Guia da ANPD sobre tratamento pelo poder público | Consentimento nulo quando o tratamento é compulsório (DEC-46) |

### 2.3 Documentos do projeto

| Documento | Conteúdo |
|---|---|
| `fase0-v1.0-visao-escopo-baseline.md` | Visão, escopo, triagem legal, controles SEG-01 a SEG-25 |
| `fase1-*` | Perfilamento das planilhas, elicitação, análise dos formulários, especificação da migração |
| `requisitos-funcionais-v1.1-aprovado.md` | Baseline aprovada |
| `fase2-modelo-dominio.md` | Entidades, invariantes, decisões de modelagem |
| `fase2-casos-de-uso.md` | Casos de uso, critérios de aceitação, escopo de entrega |
| `fase2-requisitos-nao-funcionais.md` | Catálogo ISO 25010 e cenários QAS-01 a QAS-10 |
| `fase2-bases-legais-por-operacao.md` | OP-01 a OP-15, retenção, pendências jurídicas |
| `fase2-modelagem-ameacas-stride-linddun.md` | Ameaças T-01 a T-26, requisitos derivados |
| `fase2-viabilidade-fechamento.md` | Especificação do servidor, viabilidade, fechamento da Fase 2 |

---

## 3. Requisitos específicos

### 3.1 Interfaces externas

#### 3.1.1 Interface com o usuário

| ID | Requisito |
|---|---|
| IU-01 | Acesso pelas estações Windows da clínica, por navegador, em conexão cifrada (RNF-618) |
| IU-02 | Tela de cadastro com os campos na ordem da ficha de papel revisada (RF-106, RNF-401) |
| IU-03 | Tela de frequência do turno inteiro, presença como padrão, uma ação por ausência (RF-502, RNF-402) |
| IU-04 | Tela de pendências por perfil, com contagem (RF-1010) |
| IU-05 | Documentos exibidos dentro da aplicação, sem download implícito (SEG-19) |
| IU-06 | Conformidade com WCAG 2.1 nível AA (RNF-406) |

#### 3.1.2 Interfaces de hardware

| Dispositivo | Requisito de interface |
|---|---|
| Scanner Brother, com alimentador automático | Captura recebida diretamente pela aplicação, sem arquivo intermediário em pasta do usuário (SEG-28). Como aplicação web não aciona scanner, a forma de captura é decisão da Macroentrega II (viabilidade §3.3) |
| Webcam | Captura pelo navegador, que só libera a câmera em conexão segura — por isso RNF-618 é também pré-requisito funcional (viabilidade §3.2) |
| Impressora | Emissão dos documentos e do crachá. A impressora atual é monocromática; impressão colorida do crachá é decisão da clínica (R-24) |
| Nobreak | Comunicação USB com o servidor para desligamento ordenado (RNF-508) |

#### 3.1.3 Interfaces de software

| Sistema | Interface |
|---|---|
| MySQL 8.0 | Instância própria, não alcançável pela rede (RNF-301, RNF-614) |
| Sistema de estoque | **Nenhuma.** Compartilha apenas o hardware; instância de banco separada |
| Consulta de CEP (ViaCEP, com fonte alternativa) | Envia **somente o CEP**. Consulta individual, no cadastro e na resolução de pendência — nunca validação em massa. Indisponibilidade não bloqueia nenhuma função (RNF-507, RNF-612, RNF-704) |
| Antimalware | Local, com atualização automática de assinaturas (SEG-09, SEG-21) |
| Sistema operacional do servidor | Com suporte de segurança por pelo menos cinco anos e criptografia de disco nativa. Escolha na Macroentrega II (viabilidade §2.3) |

#### 3.1.4 Interfaces de comunicação

Somente rede local, sem exposição de entrada (RF-1007). Saída restrita a consulta de CEP,
assinaturas antimalware e atualizações de segurança (RNF-611). Tráfego entre estações e servidor
cifrado (RNF-618). A rede é de uso exclusivo dos funcionários da clínica — administrativos e, com DEC-48, a enfermagem (RNF-619; ver §5, item 9).

### 3.2 Requisitos funcionais

#### 3.2.1 Cadastro de pacientes

| ID | Requisito | Verif. | Origem |
|---|---|---|---|
| RF-101 | Cadastrar paciente com nome, nome da mãe, data de nascimento, número de prontuário, CPF, RG com órgão expedidor, CNS, endereço completo, município, UF, CEP, código IBGE e data de início do tratamento | T | B1.1 |
| RF-102 | Permitir salvar cadastro incompleto, sinalizando o que falta. O mínimo para salvar o paciente é nome, data de início do tratamento e número de prontuário; sem ele, o preenchimento só pode ser salvo como rascunho (RF-919). Com o mínimo, o usuário escolhe salvar o paciente ou o rascunho | T | B1.1, **V4** — DEC-57 |
| RF-103 | Validar CPF e CNS automaticamente pelo dígito verificador, **recusando a gravação de valor inválido**, e o CEP contra uma base de referência. CPF ou CNS ausente é permitido e gera pendência | T | B1.1, **V4** — DEC-58 |
| RF-104 | Aceitar o número de prontuário gerado fora do sistema, garantindo que não se repita | T | B1.1 |
| RF-105 | Calcular a idade a partir da data de nascimento sempre que for exibida, sem armazená-la | T | B1.1 |
| RF-106 | Apresentar os campos na mesma ordem da ficha de papel usada na entrevista | I | B1.1 |
| RF-107 | Localizar paciente pelo nome, com desempate por data de nascimento e nome da mãe | T | B1.1 |
| RF-108 | Alertar quando um novo cadastro coincidir em nome, data de nascimento e nome da mãe com um já existente | T | B1.1 |
| RF-109 | Manter uma lista de pendências de cadastro, mostrando quais pacientes têm dado faltante, CEP não verificado ou documento ausente | T | B1.1, **V4** — DEC-58 |
| RF-110 | Registrar o sexo do paciente | T | B1.1 |
| RF-111 | Registrar a naturalidade, com município e unidade da federação | T | B1.1 |
| RF-919 | Guardar automaticamente o preenchimento em andamento como rascunho, vinculado ao usuário, e retomá-lo quando ele voltar ao cadastro | T | **E01** — casos de uso |
| RF-920 | Descartar rascunhos automaticamente após prazo configurável, avisando antes, e permitir descarte manual | T | **E01** — casos de uso |

**Notas.** Os pacientes migrados entram sem sexo e sem naturalidade, e ambos vão para a lista de
pendências (RF-1108). A tabela de municípios é nacional, porque a naturalidade pode ser de qualquer
UF; a residência é filtrada por Goiás (RF-1205). O alerta da tríade (RF-108) é aviso, não bloqueio:
homônimos com mesma data de nascimento e mesma mãe são possíveis.

**Rascunho não é cadastro incompleto.** No rascunho (RF-919) o paciente ainda não existe: não aparece
em busca, escala, relatório nem pendência. O rascunho fica no servidor, vinculado ao usuário, sob o
mesmo controle de acesso e auditoria do cadastro. O prazo de descarte (RF-920) é configurado pelo TI.

#### 3.2.2 Contatos e telefones

| ID | Requisito | Verif. | Origem |
|---|---|---|---|
| RF-201 | Registrar vários contatos por paciente, cada um com nome e grau de parentesco | T | B1.1 |
| RF-202 | Registrar vários telefones, identificando se pertencem ao paciente ou a um contato | T | B1.1 |

#### 3.2.3 Cobertura do tratamento

| ID | Requisito | Verif. | Origem |
|---|---|---|---|
| RF-301 | Registrar a cobertura em dois estados: SUS ou convênio nomeado | T | B1.1 |
| RF-302 | Manter o histórico de cobertura com datas de vigência, preservando a anterior quando houver mudança | T | B1.1 |

A cobertura pertence ao **período de tratamento**, não ao paciente (modelo §7.1). O registro da
instituição que encaminhou o paciente foi retirado do sistema (DEC-73). Estados possíveis: SUS ou convênio nomeado.

#### 3.2.4 Escala e alocação

| ID | Requisito | Verif. | Origem |
|---|---|---|---|
| RF-401 | Trabalhar com as seis escalas da clínica, com a nomenclatura já usada: 1-seg, 2-seg, 3-seg, 1-ter, 2-ter, 3-ter | T | B1.1 |
| RF-402 | Alocar o paciente em uma escala, com data de vigência, preservando as alocações anteriores | T | B1.1 |
| RF-403 | Exibir de forma explícita o paciente que está sem alocação — nunca tratá-lo como alocado por omissão | T | B1.1 |
| RF-404 | Mostrar quantos pacientes há em cada escala, sem impor limite | T | B1.1 |
| RF-405 | Permitir a distribuição de vários pacientes de uma vez, em tela única, para a configuração inicial | T | B1.1 |
| RF-406 | Alocação em escala, trocas de turno pontuais e permanentes e sessões extras são registradas pelo perfil de enfermagem; a auditoria identifica o autor | T | **V4** — DEC-48 |

A escala válida para uma sessão é a que vigia na data da sessão (modelo §7.2).

#### 3.2.5 Frequência

| ID | Requisito | Verif. | Origem |
|---|---|---|---|
| RF-501 | A sessão de turno é aberta automaticamente pelo calendário, identificada por data e escala, sem ação da recepção | T | B1.1 [R] — DEC-54 |
| RF-502 | Lançar a frequência do turno inteiro numa tela só, com presença como padrão e marcação apenas das ausências | T | B1.1 |
| RF-503 | Registrar troca pontual de sessão, ligando a sessão perdida à sessão realizada | T | B1.1 |
| RF-504 | Registrar sessão extra, que acrescenta uma sessão sem substituir nenhuma. A classificação como extra é provisória dentro do mês e pode ser convertida em reposição por compensação posterior (RF-918) | T | B1.1 [R] — modelo §7.14 |
| RF-505 | Distinguir automaticamente sessão regular, troca pontual e sessão extra, sem exigir classificação manual | T | B1.1 |
| RF-506 | Mostrar quantas sessões extras o paciente já teve no mês e avisar ao atingir quatro | T | B1.1 |
| RF-507 | Calcular quantas sessões eram previstas no mês, a partir do calendário e da escala vigente do paciente. A clínica opera normalmente em feriados. Sessão que não aconteceu, por fechamento excepcional, é registrada pela administração como não realizada, com motivo, e sai das previstas sem gerar ausências | T | B1.1, **V4** — DEC-66 |
| RF-917 | Exibir, ao acrescentar um paciente à sessão, as ausências dele no mês em curso, para relacionamento | T | **E01** — modelo de domínio |
| RF-918 | Parear automaticamente ausências e presenças não compensadas por ordem cronológica, exibindo o pareamento e permitindo refazê-lo | T | **E01** — modelo de domínio |
| RF-921 | Presença fora da escala acrescentada pela recepção sem registro prévio da enfermagem gera pendência de ciência para a enfermagem. A presença vale; a classificação continua derivada | T | **V4** — DEC-48 |
| RF-922 | Apresentar os pacientes do próximo turno com antecedência configurável — uma hora por padrão, o intervalo de limpeza da sala —, para que a recepção separe fichas e crachás. Cada paciente aparece com as pendências que ele tem, conforme o perfil de quem consulta (§3.2.13) | T | **V4** — DEC-64 |

**Comportamentos que decorrem destes requisitos** (modelo §7.3, 7.5, 7.11 e 7.14):

- A sessão de turno só vale depois de **confirmada** pela recepcionista. A confirmação é liberada na
  última hora do turno (antecedência configurável), quando o sistema passa a pedi-la (DEC-67). Sessão não confirmada é pendência de urgência, em destaque, sem prazo.
- A classificação da presença — regular, reposição ou extra — é **derivada**, nunca digitada.
- "Extra" é saldo do mês, não fato: uma extra pendente é consumida por falta posterior do mesmo
  paciente no mesmo mês. O pareamento é automático, cronológico, visível e reversível (RF-918). A
  fronteira do mês é real.
- Em caso de divergência, a ficha de frequência assinada prevalece (RN-03).

#### 3.2.6 Eventos do paciente

| ID | Requisito | Verif. | Origem |
|---|---|---|---|
| RF-601 | Registrar cinco tipos de evento: óbito, alta, transferência, transplante e desistência | T | B1.1 |
| RF-602 | Registrar a data e, quando aplicável, o local — local do falecimento, unidade de destino ou centro transplantador | T | B1.1 |
| RF-603 | Encerrar o período de tratamento do paciente ao registrar um evento | T | B1.1 |
| RF-604 | Impedir qualquer registro posterior a um óbito. Trocas e extras planejadas depois da data de um evento de encerramento são canceladas automaticamente; presença já confirmada depois da data, possível só com evento de data retroativa, deve ser corrigida por autorização (RF-1008) antes do registro do evento | T | B1.1, **V4** — DEC-65 |
| RF-605 | Permitir que um paciente retorne, abrindo um novo período de tratamento | T | B1.1 |
| RF-606 | Permitir correção de evento registrado por engano, mantendo o registro de quem corrigiu e quando | T | B1.1 |
| RF-607 | Exigir a certidão de óbito no registro do evento de óbito. Não havendo o documento, o evento é registrado e fica marcado como pendente até que seja anexado | T | B1.1, documento por **V4** — DEC-50 |

**Documento comprobatório por tipo de evento** (DEC-53). O evento é registrado de imediato e fica
pendente até o documento ser anexado.

| Evento | Documento comprobatório |
|---|---|
| Óbito | **Certidão de óbito**, emitida pelo cartório (DEC-50) |
| Alta | Documento de alta |
| Transferência | Documento de encaminhamento à unidade de destino |
| Transplante | Documento do centro transplantador |
| Desistência | Termo de consentimento informado de interrupção do tratamento (DOC-06) |

Corrigir ou remover um evento é operação auditada sob RF-1008; a situação do paciente se ajusta por
derivação, sem rotina de reversão (modelo §7.10).

#### 3.2.7 Documentos digitalizados

| ID | Requisito | Verif. | Origem |
|---|---|---|---|
| RF-701 | Guardar os documentos digitalizados em módulo separado do cadastro, com permissões próprias | T | B1.1 |
| RF-702 | Verificar cada arquivo digitalizado contra programas maliciosos antes de armazená-lo, e recusá-lo se reprovar | T | B1.1 |
| RF-703 | Ler automaticamente os dados do documento digitalizado e apresentá-los para conferência antes de salvar | T | B1.1 |
| RF-704 | Destacar visualmente os campos lidos com baixa confiança | T | B1.1 |
| RF-705 | Classificar cada documento por tipo | T | B1.1 |
| RF-706 | Controlar o checklist de documentos de cadastro: comprovante de endereço, cartão do SUS e, quando houver convênio, cartão do convênio | T | B1.1 |
| RF-707 | Gerar pendência apenas para documentos exigidos: os do checklist de cadastro e os exigidos por um tipo de evento. Os demais documentos de evento não geram pendência | T | B1.1 |
| RF-708 | Não permitir apagar nem sobrescrever documento armazenado. Correção se faz por nova versão, com motivo registrado | T | B1.1 |
| RF-709 | Guardar os documentos por vinte anos, impedindo eliminação antes do prazo | T | B1.1 |
| RF-710 | Registrar quem consultou cada documento, além de quem o inseriu | T | B1.1 |
| RF-711 | Capturar a foto do paciente por webcam, em cores | D | B1.1 [R] |
| RF-712 | Exibir em destaque, na conferência de documento digitalizado, a identificação do paciente de destino — nome, data de nascimento e nome da mãe — antes do armazenamento | D | **E01** — ND-92 |
| RF-713 | Revincular documento anexado ao paciente errado por operação auditada, com motivo, sem excluir nem alterar o documento | T | **E01** — ND-92 |

**Notas.** A foto do paciente é documento de tipo próprio: vem da webcam e pula a digitalização,
mas usa o mesmo armazenamento controlado e a mesma auditoria. Os documentos digitalizados são
guardados em PDF/A, 300 dpi, tons de cinza; a foto, em cores. O pipeline de ingestão está na §3.6.
A extração automática de dados (RF-703, RF-704) é isolada e desativável (RNF-702).

#### 3.2.8 Emissão de documentos

| ID | Requisito | Verif. | Origem |
|---|---|---|---|
| RF-801 | Gerar os sete documentos da clínica já preenchidos com os dados do cadastro | T | B1.1 |
| RF-802 | Obter o cabeçalho institucional de uma configuração única — nome, endereço, CEP, município, UF e telefone | D | B1.1 |
| RF-803 | Escrever a data de emissão por extenso, com o município | D | B1.1 |
| RF-804 | Gerar a declaração de troca de turno a partir do registro da troca, com as duas datas e os dois turnos preenchidos | T | B1.1 |
| RF-805 | Gerar o termo de diálise extra apenas com o cabeçalho, sob demanda, uma folha por paciente por mês, avisando se já houve emissão no mesmo mês | T | B1.1 |
| RF-806 | Permitir digitar o nome e o registro do profissional no momento da emissão do termo de consentimento, sem cadastro prévio | T | B1.1 |
| RF-807 | Permitir texto livre na carta de recusa pontual, descrevendo o que foi recusado | T | B1.1 |
| RF-808 | Emitir o crachá com foto do paciente, logotipo da clínica, nome do paciente e nome da mãe | D | B1.1 |
| RF-809 | Quando a enfermagem registrar troca pontual ou sessão extra, gerar para a recepção pendência de termo: emitir o documento já preenchido (DOC-03 ou DOC-07), imprimir, colher as assinaturas, digitalizar e anexar. A pendência se encerra com o documento assinado anexado | T | **V4** — DEC-48 |

**Os sete documentos parametrizados** (análise dos formulários, §2 e §3.2):

| ID | Documento | Campos preenchidos pelo sistema |
|---|---|---|
| DOC-01 | Ficha de cadastro do paciente | Todos os campos do cadastro, na ordem da ficha revisada |
| DOC-02 | Termo de responsabilidade — implante de cateter duplo lúmen | Nome do paciente, município e data de emissão |
| DOC-03 | Declaração de troca de turno | Nome; data e turno de origem e de destino; município e data (RF-804) |
| DOC-04 | Termo de responsabilidade — alimentos | Nome; endereço da clínica no corpo; município e data |
| DOC-05 | Carta de recusa em data específica | Nome, CPF, CNS, endereço; data da recusa; texto livre; contato que assina (RF-807) |
| DOC-06 | Termo de consentimento informado — interrupção do tratamento | Nome e CPF; nome e registro profissional digitados na emissão (RF-806); linhas para três testemunhas |
| DOC-07 | Termo de necessidade de diálise extra | Apenas cabeçalho: nome, data de nascimento, nome da mãe, turno vigente (RF-805) |

Os títulos definitivos de DOC-02 a DOC-05 dependem da clínica (§1.7, item 6). Os modelos são criados
do zero, nunca a partir de documento real de paciente editado por cima (RNF-903).

#### 3.2.9 Relatórios

| ID | Requisito | Verif. | Origem |
|---|---|---|---|
| RF-901 | Permitir seleção de período em todos os relatórios | T | B1.1 |
| RF-902 | Entrada de pacientes por período | T | B1.1 |
| RF-903 | Pacientes por cidade | T | B1.1 |
| RF-904 | Eventos ocorridos por período, filtrados por categoria | T | B1.1 |
| RF-905 | Pacientes por convênio, em dois modos: situação no momento, ou cobertura vigente num período escolhido | T | B1.1 |
| RF-906 | Frequência mensal por paciente, comparando sessões previstas, realizadas, ausências e extras | T | B1.1 |
| RF-907 | Exibir, em todo relatório de série histórica, a data em que a série começa | T | B1.1 |
| RF-908 | Ocupação por escala | T | B1.1 |
| RF-909 | Exibir na tela inicial um lembrete dos aniversariantes do dia | D | B1.1 |
| RF-910 | Pacientes por faixa etária, em faixas de dez anos: 0–9, 10–19, 20–29, 30–39, 40–49, 50–59, 60–69, 70–79, 80–89, 90–99 e 100 ou mais | T | B1.1, valores por **V4** — DEC-49 |
| RF-911 | Pacientes por sexo | T | B1.1 |
| RF-912 | Baixar qualquer relatório em PDF e em XLSX, contendo apenas as colunas do relatório escolhido | T | B1.1 [R] — ND-94 |
| RF-913 | Bloquear a emissão do relatório mensal de frequência enquanto houver sessão não confirmada no mês, informando quantas faltam e quais | T | **E01** — modelo de domínio |
| RF-914 | Sinalizar, nos demais relatórios que usam frequência com recorte livre de período, a existência de sessões não confirmadas no intervalo | T | **E01** — modelo de domínio |
| RF-915 | Marcar o mês como alterado após o fechamento, com data, responsável e motivo, exibindo essa marca em todo relatório de frequência que inclua aquele período | T | **E01** — modelo de domínio; **V4** — DEC-69 |
| RF-916 | Balanço mensal por paciente: sessões previstas, realizadas, ausências não compensadas, reposições e extras definitivas | T | **E01** — modelo de domínio |

**Notas.** A faixa etária é calculada na data de referência do relatório (RF-910); as faixas são
configuração (RF-1206). Todo relatório de série histórica informa que a série começa na implantação
(RF-907, RN-05). O relatório mensal de frequência só existe quando o mês está completo (RF-913).
Relatórios agregados são tratados como dado pessoal, sem supressão de células (DEC-44).

#### 3.2.10 Acesso e usuários

| ID | Requisito | Verif. | Origem |
|---|---|---|---|
| RF-1001 | Cinco perfis: visualizador, recepcionista, administração, TI e enfermagem | I | **V4** — DEC-48 |
| RF-1002 | Login individual para cada usuário | T | B1.1 |
| RF-1003 | Bloquear a sessão automaticamente após período de inatividade | T | B1.1 |
| RF-1004 | Não conceder ao perfil de TI acesso a dados de paciente | T | B1.1 |
| RF-1005 | Inativar usuário em vez de excluí-lo | T | B1.1 |
| RF-1006 | Registrar quem criou, alterou, consultou, exportou e inativou cada informação sensível | T | B1.1 |
| RF-1007 | Funcionar apenas na rede local, sem acesso externo | I | B1.1 |
| RF-1008 | Exigir autorização da administração, concedida **a partir da sessão do próprio autorizador**, para excluir cadastro criado por engano e para alterar registro já confirmado — reabrir sessão, alterar presença, alterar alocação que alcance sessões confirmadas, corrigir ou remover evento. A solicitação aguarda na tela de pendências da administração até ser aprovada ou recusada, e a auditoria registra autor e autorizador separadamente. Quando a solicitação parte da própria administração, a aprovação é automática e a auditoria registra o mesmo usuário nos dois papéis. Aprovada a exclusão de cadastro criado por engano, tudo o que está vinculado a ele — documentos, presenças, alocações e trocas — é descartado automaticamente, e a tela de decisão mostra antes o que será descartado | T | **E01** — DEC-42; **V4** — DEC-60, DEC-61 |
| RF-1009 | Registrar e acompanhar pedidos de pacientes sobre seus próprios dados, com relatório de atendimento. O atendimento de pedido de acesso produz cópia dos documentos daquele paciente, com registro da entrega | T | B1.1 [R] — ND-95 |
| RF-1010 | Exibir a cada perfil, em tela única e com contagem, as pendências que lhe cabem, conforme a matriz da §3.2.13 | T | **E01** — ND-97 |
| RF-1011 | Notificar a administração quando a verificação da cadeia de auditoria falhar, com aviso sem detalhe técnico e sem dado de paciente; o TI recebe o diagnóstico completo. O aviso só é encerrado pela administração, com registro da explicação recebida | T | **E01** — DEC-43 |

#### 3.2.11 Migração dos dados atuais

| ID | Requisito | Verif. | Origem |
|---|---|---|---|
| RF-1101 | Importar a planilha de endereços e telefones como base dos pacientes em tratamento | T | B1.1 |
| RF-1102 | Complementar com a planilha de entradas, ligando os registros pelo número de prontuário | T | B1.1 |
| RF-1103 | Conferir contra a planilha de eventos para identificar cadastros desatualizados | T | B1.1 |
| RF-1104 | Converter o código IBGE para o formato completo de sete dígitos | T | B1.1 |
| RF-1105 | Classificar a qualidade de cada CEP importado e encaminhar os problemáticos para a lista de pendências | T | B1.1 |
| RF-1106 | Produzir relatório de exceções da importação, para revisão pela recepção. Valor inválido da planilha não é importado: o campo fica vazio, o caso entra no relatório e o paciente é importado com a pendência correspondente | T | B1.1, **V4** — DEC-58 |
| RF-1107 | Importar todos os pacientes com documentação pendente | T | B1.1 |
| RF-1108 | Importar todos os pacientes sem sexo e sem naturalidade, marcados como pendentes | T | B1.1 |

**Critério de aceitação da carga.** Zero exceções não prova carga correta: o extrator de referência
passou sem erro com rótulos de telefone invertidos. A aceitação exige **conferência amostral humana**
de registros migrados contra a planilha de origem, além do relatório de exceções (RF-1106, RNF-103).
A carga é o último item construído, contra o modelo já estável (casos de uso §5.4).

#### 3.2.12 Configurações

| ID | Requisito | Verif. | Origem |
|---|---|---|---|
| RF-1201 | Dados institucionais usados nos documentos | T | B1.1 |
| RF-1202 | Logotipo da clínica, usado no crachá | T | B1.1 |
| RF-1203 | Os tipos de documento, sua família, a composição do checklist de cadastro e os documentos exigidos por evento são **definidos no sistema e não configuráveis pela tela**. Acrescentar ou alterar tipo exige nova versão, com análise de impacto. Não existe tipo genérico | I | **E01** — DEC-41, ND-96 |
| RF-1204 | Cadastro de convênios | T | B1.1 |
| RF-1205 | Tabela nacional de municípios com código IBGE | I | B1.1 |
| RF-1206 | Faixas etárias usadas nos relatórios, configuradas de dez em dez anos, de 0 a 100 ou mais (DEC-49) | T | B1.1 |

RF-1203 permanece nesta seção para preservar a numeração, embora deixe de ser configuração (DEC-41).

#### 3.2.13 Matriz de pendências por perfil

Referenciada por RF-1010. Cada linha é uma pendência; cada coluna, o perfil que a vê.

| Pendência | Recepção | Administração | Visualizador | TI | Enfermagem |
|---|---|---|---|---|---|
| Cadastro incompleto ou CEP não verificado | ✓ | ✓ | — | — | — |
| Documento do checklist faltante | ✓ | ✓ | — | — | — |
| Evento sem documento comprobatório | ✓ | ✓ | — | — | — |
| Sessão de turno não confirmada — **urgência** | ✓ | ✓ | — | — | — |
| **Termo a emitir e assinar — troca pontual ou sessão extra (RF-809)** | ✓ | ✓ | — | — | ✓ |
| **Paciente sem alocação (RF-403)** | ✓ | ✓ | — | — | ✓ |
| **Presença fora da escala sem registro prévio (RF-921)** | — | — | — | — | ✓ |
| Sessão extra além do limite mensal | ✓ | ✓ | — | — | ✓ |
| Possível duplicidade pela tríade | ✓ | ✓ | — | — | — |
| Pedido de titular, com prazo de resposta visível | ✓ | ✓ | ✓ | — | — |
| Solicitação de autorização (RF-1008) | — | ✓ | — | — | — |
| Falha na verificação da cadeia de auditoria (RF-1011) | — | ✓ aviso simples | — | ✓ diagnóstico | — |
| Rascunho próximo do descarte (RF-920) — só para o autor do rascunho | ✓ | ✓ | — | — | — |
| **Documento capturado aguardando conferência** | ✓ | ✓ | — | — | — |
| **Documento bloqueado por detecção no rescan ou hash divergente** | — | ✓ | — | ✓ só identificadores | — |
| **Documentos elegíveis para descarte ao fim da retenção** | — | ✓ | — | — | — |
| **Job agendado que não rodou no horário** | — | — | — | ✓ | — |
| **Assinaturas do antimalware desatualizadas (SEG-21)** | — | — | — | ✓ | — |
| **Ocupação de disco acima do limite (RNF-621)** | — | — | — | ✓ | — |
| **Âncora mensal da cadeia de auditoria, para anotação fora do sistema** | — | ✓ | — | — | — |

A coluna da administração nas linhas operacionais decorre da definição do perfil: "tudo da
recepção" (§1.5). As linhas em negrito foram acrescentadas por DEC-48; as seis seguintes, por DEC-70; a última, por DEC-72. Cadastro incompleto,
documento do checklist faltante e paciente sem alocação só valem para paciente em tratamento; após o
evento de saída, permanece apenas a pendência do evento sem documento comprobatório (DEC-71). A pendência de termo aparece também para a enfermagem, que
acompanha o que gerou. A assinatura e o carimbo da enfermeira na declaração de troca de turno são
colhidos em papel, fora do sistema; a emissão, a impressão e a digitalização continuam com a
recepção.

### 3.3 Regras de negócio

| ID | Regra | Observação |
|---|---|---|
| RN-01 | Até quatro sessões extras por paciente por mês; trocas pontuais não contam | O sistema conta e sinaliza a partir da quinta, **sem bloquear**. Quem decide é a enfermagem (modelo §7.9) |
| RN-02 | Nenhum fato datado pode existir após a data do óbito. A captura de documento após o óbito é permitida | INV-01, DEC-62 |
| RN-03 | Em divergência, a ficha de frequência assinada prevalece sobre o sistema | A ficha é o comprovante de faturamento (DEC-31) |
| RN-04 | A planilha de cadastro é a fonte da verdade na migração | DEC-13 |
| RN-05 | O histórico do sistema começa na data de implantação | DEC-14 |
| RN-06 | Documentos digitalizados são guardados por vinte anos | Lei nº 13.787/2018 |
| RN-07 | Paciente sem escala atribuída nunca é considerado em tratamento por omissão | RF-403 |
| RN-08 | Todo evento exige o documento comprobatório da §3.2.6; sem ele, o evento vale, mas fica pendente | Estendido do óbito aos cinco eventos por DEC-53 |

**Princípio geral (modelo §7.9): o sistema registra o que aconteceu; quem decide é a clínica.**
Ocupação de escala não bloqueia, a tríade alerta, a quinta extra sinaliza.

### 3.4 Requisitos lógicos de dados

#### 3.4.1 Contextos e entidades

O sistema é organizado em cinco contextos com fronteiras explícitas (RNF-701). O contexto de
Documentos conhece o paciente apenas pelo identificador.

| Contexto | Entidades |
|---|---|
| Cadastro | Paciente, Contato, Telefone, Período de tratamento, Evento, Cobertura |
| Operação | Escala (tabela fixa), Alocação, Sessão de turno, Presença, Compensação |
| Documentos | Documento, Tipo de documento (fixo), Emissão de documento, Foto do paciente |
| Acesso | Usuário, Perfil, Registro de auditoria, Requisição de titular, Solicitação de autorização |
| Configuração | Município (nacional, código IBGE de 7 dígitos), Convênio, Dados institucionais, Logotipo, Faixas etárias, Parâmetros de retenção e de digitalização |

A entidade **Solicitação de autorização** é acrescentada ao modelo de domínio por DEC-42: registra
quem pediu, o quê, quando, quem decidiu, a decisão e o motivo.

#### 3.4.2 Invariantes

| ID | Invariante | Tipo |
|---|---|---|
| INV-01 | Nenhum fato datado — presença, alocação, troca de turno, evento ou período de tratamento — pode ter data posterior a um óbito. A captura de documento, inclusive da certidão que comprova o óbito, é permitida depois dele (DEC-62) | Bloqueio |
| INV-02 | Um paciente tem no máximo um período de tratamento aberto por vez | Bloqueio |
| INV-03 | Alocação exige período de tratamento aberto | Bloqueio |
| INV-04 | Presença só existe em sessão cuja data esteja dentro de um período aberto do paciente | Bloqueio |
| INV-05 | O limite de quatro extras **não** é invariante: o sistema conta e sinaliza, sem bloquear (RN-01) | Sinalização |
| INV-06 | Documento armazenado não é alterado nem excluído — só recebe nova versão | Bloqueio |
| INV-07 | Número de prontuário é único | Bloqueio |
| INV-08 | Coincidência da tríade nome + data de nascimento + nome da mãe gera **alerta**, não bloqueio | Alerta |
| INV-09 | Vigências de cobertura de um mesmo período não se sobrepõem | Bloqueio |
| INV-10 | Vigências de alocação de um mesmo período não se sobrepõem | Bloqueio |
| INV-11 | Todo evento permanece pendente até que seu documento comprobatório seja anexado | Pendência |
| INV-12 | Telefone pertence ao paciente ou a um contato, nunca a ambos | Bloqueio |
| INV-13 | Documento anterior ao fim da retenção não pode ser eliminado | Bloqueio |
| INV-14 | Sessão de turno não confirmada não conta como frequência lançada | Bloqueio |
| INV-15 | CPF e CNS são únicos entre pacientes, quando informados. A recusa informa o paciente que já usa o número (DEC-59) | Bloqueio |

#### 3.4.3 Informação derivada, nunca armazenada

| Informação | Derivada de |
|---|---|
| Idade | Data de nascimento e data de referência |
| Faixa etária | Idade na data de referência do relatório |
| Situação do paciente | Períodos e eventos |
| Classificação da presença | Alocação vigente, trocas e compensações |
| Sessões previstas no mês | Calendário e alocação vigente |
| Contagem de extras no mês | Presenças fora da escala sem compensação — provisória com o mês aberto |
| Pendências | Campos, documentos e confirmações em falta |
| Ocupação por escala | Alocações vigentes |

Cada item desta tabela é um campo que **não** existirá no banco. Armazená-lo é defeito: a idade
impressa errada em documento real da clínica foi o exemplo que motivou a regra.

#### 3.4.4 Retenção

| Dado | Prazo | Origem |
|---|---|---|
| Documentos de prontuário digitalizados | 20 anos a contar do último registro; eliminação impedida antes do prazo | Lei nº 13.787/2018, RF-709, RNF-610 |
| Prova de integridade de cada documento | O mesmo do documento | RNF-628 |
| Cadastro, frequência e sessões | Acompanham o prontuário | Bases legais §6.1 |
| Registro de auditoria | 5 anos, com ponto de corte verificável no expurgo | DEC-45, RNF-628 |
| Contas de usuário | Inativadas, nunca excluídas | RF-1005 |
| Rascunho de cadastro | Prazo configurável, com aviso antes do descarte | RF-920 |
| Quarentena de ingestão | Expurgo automático por idade; fora do backup | SEG-29 |
| Backups | Ciclo de vida finito, para que dado eliminado não sobreviva indefinidamente | Bases legais §6.3 |

### 3.5 Requisitos de qualidade

Organizados pelas características da ISO/IEC 25010:2023. Cada requisito tem alvo e verificação.

#### 3.5.1 Adequação funcional

| ID | Requisito e alvo | Verificação |
|---|---|---|
| RNF-101 | **Correção dos cálculos derivados.** Idade, sessões previstas, contagem de extras e ocupação calculados sem divergência em 100% dos casos de teste | Bateria de testes com meses de 4 e 5 ocorrências de cada dia, admissões e saídas no meio do mês, e trocas de escala |
| RNF-102 | **Correção da validação de documentos.** CPF, CNS e código IBGE validados por dígito verificador, sem falso positivo nem falso negativo | Massa de teste com documentos válidos e inválidos conhecidos |
| RNF-103 | **Completude da migração.** 100% dos registros de origem resultam em carga ou em exceção registrada. Nenhum registro desaparece silenciosamente | Conferência de contagem entre origem e destino, mais relatório de exceções |

#### 3.5.2 Eficiência de desempenho

Volumetria de referência: 146 pacientes ativos, cerca de 1.200 acumulados em 20 anos.

| ID | Requisito e alvo | Verificação |
|---|---|---|
| RNF-201 | **Tempo de busca de paciente.** < 2 s com 1.200 pacientes na base | Medição com base sintética no volume de 20 anos |
| RNF-202 | **Abertura do cadastro completo.** < 2 s | Idem |
| RNF-203 | **Gravação do cadastro.** < 3 s | Idem |
| RNF-204 | **Marcação de presença individual na tela do turno.** < 1 s, sem recarregar a lista | Medição na tela de frequência com 30 pacientes |
| RNF-205 | **Confirmação da sessão de turno.** < 3 s | Idem |
| RNF-206 | **Geração de documento parametrizado.** < 10 s, da solicitação ao arquivo pronto | Medição por tipo de documento |
| RNF-207 | **Emissão de relatório mensal.** < 15 s para o mês completo da clínica | Medição com dados de 12 meses carregados |
| RNF-208 | **Ingestão de documento digitalizado.** < 30 s da captura à tela de conferência, incluindo varredura e reconstrução | Medição com documento A4 a 300 dpi |
| RNF-209 | **Consumo de armazenamento.** < 8 GB em 20 anos para documentos e fotos | Projeção aferida trimestralmente contra o real |

#### 3.5.3 Compatibilidade

| ID | Requisito e alvo | Verificação |
|---|---|---|
| RNF-301 | **Banco de dados.** MySQL 8.0, em **instância própria**, com banco e usuário dedicados, separada da instância do sistema de estoque e não alcançável pela rede (viabilidade §2.6) | Inspeção de configuração |
| RNF-302 | **Coexistência.** Nenhuma degradação mensurável do sistema de estoque após a implantação | Medição de tempo de resposta do sistema existente, antes e depois |
| RNF-303 | **Estações.** Windows, conforme o parque existente | Homologação em estação idêntica à da recepção |
| RNF-304 | **Periféricos.** Scanner Brother **com alimentador automático de documentos**; webcam a adquirir; nobreak com comunicação USB | Teste com o equipamento real antes da homologação, incluindo digitalização de documento de várias páginas em uma passagem |

#### 3.5.4 Capacidade de interação

| ID | Requisito e alvo | Verificação |
|---|---|---|
| RNF-401 | **Ordem dos campos do cadastro.** Idêntica à da ficha de papel revisada | Conferência lado a lado com a ficha |
| RNF-402 | **Esforço de lançamento de frequência.** Turno completo lançado em, no máximo, um clique por exceção mais a confirmação | Contagem de cliques em turno com 3 ausências |
| RNF-403 | **Tempo de cadastro completo.** < 5 min de transcrição, contra 15 min hoje | Cronometragem com a recepcionista, em homologação |
| RNF-404 | **Tempo de localização de paciente.** < 15 s, contra 3 min hoje | Idem |
| RNF-405 | **Emissão de documento.** < 1 min, contra 5 a 6 min hoje | Idem |
| RNF-406 | **Acessibilidade.** WCAG 2.1 nível AA | Auditoria com ferramenta automatizada e verificação de teclado e contraste |
| RNF-407 | **Proteção contra erro do usuário.** Toda ação irreversível exige confirmação explícita, e nenhuma exclusão de paciente é possível pela tela | Revisão de cada operação destrutiva |
| RNF-408 | **Visibilidade das pendências.** As pendências de cada perfil acessíveis numa tela única, com contagem (RF-1010) | Inspeção com cada perfil |

RNF-403 a RNF-405 comparam com o processo atual e são medidos **com a recepcionista**, em
homologação. São os requisitos que decidem a adoção.

#### 3.5.5 Confiabilidade

| ID | Requisito e alvo | Verificação |
|---|---|---|
| RNF-501 | **Disponibilidade na janela de operação.** 05:00 às 20:00, de segunda a sábado, cobrindo a preparação do primeiro turno (RF-922) (DEC-68). Manutenção apenas fora dessa janela | Registro de indisponibilidade |
| RNF-502 | **RPO — perda máxima aceitável de dados.** 24 h em falha de hardware com os discos preservados, correspondente ao backup diário; 7 dias em perda total do servidor, correspondente à cópia semanal fora da máquina (DEC-56) | Verificação da rotina |
| RNF-503 | **RTO — tempo máximo de retorno.** 4 h | **Teste de restauração cronometrado**, com evidência registrada |
| RNF-504 | **Cópia fora do servidor.** Ao menos uma cópia semanal mantida fora da máquina e fora da sala | Inspeção física e registro de rodízio |
| RNF-505 | **Restauração testada.** Ao menos um teste completo antes do go-live e um por semestre | Evidência datada |
| RNF-506 | **Contingência operacional.** Procedimento manual documentado para a recepção operar durante indisponibilidade | Documento aprovado e conhecido pela equipe |
| RNF-507 | **Tolerância a falha de serviço externo.** Indisponibilidade da consulta de CEP não impede cadastro nem qualquer outra função | Teste com o serviço bloqueado |
| RNF-508 | **Energia.** Nobreak mantém o servidor durante a falta de energia e a comutação para o gerador. Em bateria crítica, o servidor é desligado de forma ordenada e automática, com os bancos encerrados antes do sistema operacional | Teste em homologação: corte de energia com o gerador desligado, até o desligamento automático, seguido de verificação de integridade do banco e dos documentos |
| RNF-617 | Cópia fora do servidor cifrada com chave que não viaja com a mídia, desconectada após a gravação, com registro de localização e de destruição de cada mídia | Inspeção física e do registro; tentativa de leitura da mídia sem a chave |
| RNF-621 | Alerta de ocupação de disco; backup local em volume distinto do repositório | Teste de alerta com volume próximo do limite |
| RNF-622 | Chave de criptografia com cópia de custódia fora do servidor, em dois locais. O teste de restauração inclui a recuperação da chave | Teste de restauração em máquina limpa, sem acesso ao servidor original |

#### 3.5.6 Segurança

Fundamento: LGPD, arts. 37 e 46 a 49.

| ID | Requisito e alvo | Verificação |
|---|---|---|
| RNF-601 | **Autenticação individual.** Um login por pessoa. Nenhuma conta compartilhada. Uma sessão ativa por usuário: novo login encerra a anterior, com aviso (DEC-63) | Inspeção do cadastro de usuários; teste de login em duas estações |
| RNF-602 | **Bloqueio por inatividade.** Sessão bloqueada automaticamente; prazo configurável | Teste na estação |
| RNF-603 | **Menor privilégio no banco.** Usuário da aplicação sem permissão administrativa; perfil de TI sem acesso a dado de paciente | Inspeção de permissões |
| RNF-604 | **Criptografia em repouso.** Repositório de documentos digitalizados cifrado | Inspeção |
| RNF-605 | **Auditoria de escrita.** Toda criação, alteração e inativação registrada com autor, autorizador quando houver, instante e motivo | Amostragem de operações contra o log |
| RNF-606 | **Auditoria de leitura.** Toda consulta a documento de prontuário registrada | Idem |
| RNF-607 | **Auditoria de exportação.** Toda exportação de relatório registrada com filtros aplicados | Idem |
| RNF-608 | **Ingestão segura de arquivos.** Lista de permissão por assinatura binária, quarentena, varredura, reconstrução, armazenamento fora da raiz web | Teste com arquivo EICAR e com arquivo de extensão falsificada |
| RNF-609 | **Irretratabilidade.** Registro de auditoria não alterável pela aplicação | Inspeção de permissões |
| RNF-610 | **Retenção protegida.** Documento com menos de 20 anos não pode ser eliminado por nenhuma função do sistema | Teste de tentativa de exclusão |
| RNF-611 | **Superfície de rede.** Sem exposição de entrada. Saída restrita a uma **lista de destinos permitidos**: consulta de CEP, assinaturas antimalware e atualizações de segurança do sistema operacional e das dependências. Qualquer outro destino é bloqueado | Inspeção de configuração |
| RNF-612 | **Dados enviados a terceiros.** Somente o CEP. Nenhuma identificação do paciente sai do sistema por integração | Inspeção do código de integração |
| RNF-613 | Bloqueio progressivo após tentativas de login falhas; senhas armazenadas com função de hash adaptativa | Teste de tentativas sucessivas; inspeção do armazenamento |
| RNF-614 | O banco deste sistema aceita conexão apenas do servidor de aplicação e não é alcançável pela rede. Nenhuma estação conhece sua credencial. Como os terminais do estoque conectam direto ao MySQL, o banco do estoque fica em instância separada (viabilidade, §2.6) | Tentativa de conexão a partir de uma estação e de um terminal do estoque, com a credencial do estoque |
| RNF-615 | Trilha de auditoria encadeada por hash, incluindo o hash de cada documento ingerido. O último elo é registrado fora do servidor periodicamente, e a cadeia é verificada | Alteração deliberada de um registro em homologação, detectada na verificação |
| RNF-616 | Estações com criptografia de disco, conta de usuário sem privilégio administrativo e navegador atualizado. **Nenhuma cópia de documento permanece na estação após consulta** | Inspeção de downloads, cache e pastas temporárias após uso; inspeção das contas locais |
| RNF-618 | Tráfego entre estações e servidor cifrado, inclusive na rede local | Captura de tráfego em homologação |
| RNF-619 | Rede sem fio acessível a pacientes, acompanhantes ou dispositivos pessoais isolada da rede do servidor | Tentativa de acesso ao servidor a partir da rede sem fio |
| RNF-620 | Esta aplicação roda com conta de serviço própria no sistema operacional. Repositório e backup legíveis só por ela, e **nunca expostos como pasta compartilhada de rede** | Inspeção de permissões e de compartilhamentos |
| RNF-623 | Autorização verificada no servidor em cada operação, para cada documento. Identificador aleatório não substitui verificação | Teste de requisição direta com identificador de documento de outro paciente |
| RNF-624 | Logs técnicos contêm apenas identificadores internos. Nunca texto extraído, nome, CPF ou CNS | Revisão de logs após bateria de testes |
| RNF-625 | Acesso à trilha de auditoria restrito à administração e ao TI, e registrado. Para o TI, paciente identificado apenas pelo identificador interno, sem nome nem tipo de documento | Consulta à trilha com cada perfil, seguida de verificação do registro |
| RNF-626 | Metadados de documentos da família de prontuário seguem a permissão do conteúdo | Consulta com perfil sem permissão |
| RNF-627 | Toda leitura, reconstrução e extração de imagem ocorre no servidor da clínica. Nenhuma imagem ou texto de documento sai por integração | Revisão de código e inspeção de tráfego de saída |
| RNF-628 | O hash de cada documento e sua prova de encadeamento são mantidos junto ao documento pelo prazo dele (20 anos), independentes da trilha de auditoria. O expurgo da trilha após 5 anos (DEC-45) registra um ponto de corte verificável, e a cadeia remanescente continua conferível | Expurgo simulado em homologação, seguido de verificação da cadeia e da integridade dos documentos antigos |

#### 3.5.6.1 Estações fora de suporte — risco aceito

As estações permanecem como estão, com Windows 10 e Windows 11 (DEC-51). O Windows 10 não recebe
correções de segurança desde outubro de 2025, e o programa estendido para consumidores não se aplica
a uso comercial. A clínica aceita esse risco.

A compensação é manter os dados **fora** das estações e reduzir o que uma estação comprometida
alcança:

| Controle | Efeito |
|---|---|
| Nenhuma cópia de documento permanece na estação (SEG-19 revisado, SEG-28, RNF-616) | Uma estação comprometida não entrega acervo, porque não tem acervo |
| Conta local sem privilégio administrativo | Limita o que um programa malicioso instala |
| Antimalware ativo e atualizado (SEG-23) | Detecção corrente |
| Navegador sempre atualizado | É o programa que abre conteúdo externo; convém verificar até quando o fabricante o atualiza no Windows 10 |
| Banco inalcançável pela estação (RNF-614) | Credencial de banco não existe na estação |
| Repositório e backup sem compartilhamento de rede (RNF-620) | Ransomware na estação não alcança documentos nem backup |
| Bloqueio por inatividade e login individual (RNF-601, RNF-602) | Limita uso indevido no balcão |
| Criptografia de disco, por ferramenta própria onde a edição for Home | Protege contra furto da máquina |

Esta é a diferença prática que o servidor dedicado trouxe: com o servidor separado, a estação deixa
de ser onde os dados moram e passa a ser apenas por onde eles são vistos. Sem essa separação, o risco
aceito aqui seria bem maior.

**O que a criptografia em repouso protege.** Com a chave no mesmo servidor, RNF-604 protege contra
perda ou furto da mídia, não contra quem administra o servidor. Contra este, o controle é tornar
alterações detectáveis (RNF-615) — risco R-27, aceito com compensação.

#### 3.5.7 Manutenibilidade

| ID | Requisito e alvo | Verificação |
|---|---|---|
| RNF-701 | **Modularidade por contexto.** Os cinco contextos do modelo implementados com fronteiras explícitas; o de Documentos conhece o paciente apenas pelo identificador | Revisão de arquitetura |
| RNF-702 | **Extração de dados isolada.** A leitura automática pode ser desligada por configuração, sem afetar digitalização, armazenamento ou conferência | Teste com o recurso desativado |
| RNF-703 | **Documentos parametrizados.** Alterar cabeçalho, título ou texto de um documento não exige alteração de código | Teste de alteração por configuração |
| RNF-704 | **Provedor de CEP substituível.** Troca de fonte de consulta sem alteração fora da camada de integração | Revisão de arquitetura |
| RNF-705 | **Testabilidade das regras derivadas.** Classificação de presença, compensação, sessões previstas e pendências cobertas por testes automatizados | Relatório de cobertura |
| RNF-706 | **Documentação de operação.** Backup, restauração e implantação documentados a ponto de outra pessoa conseguir executá-los | Execução por terceiro, em homologação |

#### 3.5.8 Flexibilidade

| ID | Requisito e alvo | Verificação |
|---|---|---|
| RNF-801 | **Crescimento.** Comportamento estável até 1.500 pacientes e 25 mil documentos | Teste com base sintética |
| RNF-802 | **Novo perfil de acesso.** Acrescentar um quinto perfil, como enfermagem, por configuração e sem alteração estrutural | Revisão de arquitetura |
| RNF-803 | **Paciente menor de idade.** Estrutura de responsável legal presente desde a implantação, ativável quando houver | Inspeção do modelo |
| RNF-804 | **Tipos de documento fixos.** Tipos, família, retenção e participação no checklist definidos no sistema, **sem configuração pela tela**. Acrescentar ou alterar tipo exige nova versão, com análise de impacto (DEC-41) | Inspeção: nenhuma função permite criar ou alterar tipo |
| RNF-805 | **Escalas.** As seis escalas são tabela fixa (DEC-52). Acrescentar turno ou grupo de dias exige nova versão, sem reestruturação do banco | Revisão do modelo de dados |
| RNF-806 | **Instalação.** Procedimento de instalação reproduzível em máquina limpa | Execução em ambiente de homologação |

#### 3.5.9 Segurança operacional

| ID | Requisito e alvo | Verificação |
|---|---|---|
| RNF-901 | **O sistema não pode ser causa de sessão perdida.** Indisponibilidade não impede a clínica de operar, graças ao procedimento manual de contingência | Simulação de indisponibilidade em homologação |
| RNF-902 | **Alocação incorreta detectável.** Divergência entre a escala registrada e a ficha de presença assinada é visível no fechamento do mês | Teste do balanço mensal |
| RNF-903 | **Documento emitido com dados do paciente correto.** Geração sempre a partir do cadastro selecionado, sem reaproveitamento de arquivo anterior | Revisão do mecanismo de emissão |

### 3.6 Segurança da ingestão de documentos

Controles aplicados a todo arquivo que entra no sistema, na ordem do pipeline: captura, validação,
quarentena, varredura, reconstrução, extração, conferência, armazenamento.

| ID | Controle |
|---|---|
| SEG-01 | Upload permitido apenas a usuário autenticado e autorizado |
| SEG-02 | **Lista de permissão** de tipos aceitos (PDF, JPEG, PNG, TIFF), nunca lista de bloqueio |
| SEG-03 | Verificação do tipo real por assinatura binária (*magic bytes*), não por extensão nem por MIME declarado pelo cliente |
| SEG-04 | Rejeição de arquivos compactados, SVG, documentos de escritório e executáveis |
| SEG-05 | Rejeição de nomes com extensão dupla (`.jpg.exe`, `.gif.doc`) |
| SEG-06 | Limite de tamanho aplicado **no servidor**, não apenas na interface |
| SEG-07 | Renomeação para identificador aleatório; nome original guardado apenas como metadado sanitizado |
| SEG-08 | Gravação inicial em **área de quarentena**, isolada do armazenamento definitivo |
| SEG-09 | Varredura antimalware antes da promoção. ClamAV é a opção gratuita e integrável; deve-se registrar que testes independentes situam sua detecção abaixo de motores comerciais, o que justifica não depender só dele |
| SEG-10 | **Normalização do conteúdo (CDR)** — re-renderizar o arquivo para uma imagem limpa, descartando o original. Como o conteúdo útil é um documento escaneado, ou seja, uma imagem raster, essa reconstrução preserva 100% do valor e elimina JavaScript embarcado, macros e estruturas anômalas. **É o controle mais eficaz para este caso específico** |
| SEG-11 | Promoção ao armazenamento definitivo apenas após varredura e normalização bem-sucedidas |
| SEG-12 | Arquivo reprovado é bloqueado, registrado em log e comunicado ao operador; nunca armazenado |
| SEG-13 | Armazenamento **fora da raiz web**, em diretório sem permissão de execução — não como BLOB no MySQL |
| SEG-14 | Permissão de menor privilégio no diretório e usuário de banco dedicado ao módulo |
| SEG-15 | Hash calculado na ingestão, persistido e conferido na leitura (integridade — ND-13) |
| SEG-16 | Criptografia em repouso do repositório de documentos |
| SEG-17 | Imutabilidade: sem sobrescrita nem exclusão; correção apenas por nova versão com motivo registrado |
| SEG-18 | Acesso apenas por proxy de download autenticado, nunca por URL direta ao arquivo |
| SEG-19 | **Revisado.** Documentos são exibidos dentro da aplicação, como imagem, com cabeçalhos que impedem cache (`Cache-Control: no-store`). Download é ação explícita, restrita por perfil e auditada. A exigência de `Content-Type` correto e não executável permanece |
| SEG-20 | Log de **leitura** de documento de prontuário, além do log de escrita |
| SEG-21 | Atualização automática das assinaturas do antimalware, com alerta em caso de falha na atualização |
| SEG-22 | **Rescan periódico do acervo** — ameaça desconhecida na data da ingestão pode ser detectada meses depois |
| SEG-23 | Antimalware ativo e monitorado também na estação da recepção e nas estações da gestão |
| SEG-24 | Teste de eficácia em homologação com arquivo EICAR, com evidência registrada |
| SEG-25 | Revisão periódica dos controles — a funcionalidade de upload muda e as técnicas de ataque também |
| SEG-26 | A saída da extração é tratada como entrada não confiável: mesma validação e escape aplicados à digitação |
| SEG-27 | Cada etapa do pipeline verifica o hash do arquivo produzido pela etapa anterior |
| SEG-28 | A captura é recebida diretamente pela aplicação, sem gravação intermediária em pasta do usuário na estação |
| SEG-29 | Quarentena com cota, expurgo automático por idade, e excluída do backup |
| SEG-30 | Limites de dimensão em pixels, número de páginas e tempo de processamento; reconstrução e extração em processo isolado |
| SEG-31 | O texto integral lido na imagem não é armazenado nem indexado. Só os campos confirmados persistem |

SEG-16 e RNF-604 são o mesmo requisito, registrado nas duas listas.

### 3.7 Restrições de projeto

| ID | Restrição | Origem |
|---|---|---|
| DC-01 | Documentos digitalizados em módulo segregado, com permissões próprias. O papel permanece como registro de origem | DEC-04 |
| DC-02 | Nenhum dado clínico no sistema. Lista fechada de tipos de documento, sem categoria genérica | Escopo, DEC-41 |
| DC-03 | Nenhum compartilhamento de dados com terceiros. A única comunicação externa com conteúdo é o CEP isolado | DEC-11, RNF-612 |
| DC-04 | Todo processamento de imagem — leitura, reconstrução, extração — ocorre no servidor da clínica | RNF-627 |
| DC-05 | Banco em instância própria, não alcançável pela rede; o banco do estoque em instância separada | RNF-301, RNF-614 |
| DC-06 | Servidor dedicado, em local fechado, sem uso diário por ninguém | Viabilidade §2 |
| DC-07 | Documentos em PDF/A, 300 dpi, tons de cinza; foto do paciente em cores | Fase 0, confirmado em 21/09/2026 |
| DC-08 | Extração automática isolada e desativável por configuração, sem afetar o restante do módulo | RNF-702 |
| DC-09 | Modelos de documento criados do zero; nunca a partir de documento real editado | RNF-903 |
| DC-10 | Idade, situação, classificação de presença, pendências e ocupação nunca armazenadas | §3.4.3 |

### 3.8 Conformidade legal

#### 3.8.1 Bases legais por operação

Nenhuma operação sobre dado de paciente se apoia em consentimento. Detalhamento completo em
`fase2-bases-legais-por-operacao.md`.

| ID | Operação | Base legal |
|---|---|---|
| OP-01 | Cadastro e identificação do paciente | Art. 11, II, "f" — tutela da saúde |
| OP-02 | Registro de cobertura | Art. 11, II, "f" e art. 11, II, "a" — obrigação regulatória |
| OP-03 | Alocação em escala e turno | Art. 11, II, "f" |
| OP-04 | Frequência, ausências, reposições e sessões adicionais | Art. 11, II, "f" e art. 11, II, "a" |
| OP-05 | Guarda de documentos digitalizados | Art. 11, II, "a" — obrigação legal de guarda |
| OP-06 | Emissão de documentos ao paciente | Art. 11, II, "f" e art. 11, II, "d" — exercício regular de direitos |
| OP-07 | Fotografia para crachá | Art. 11, II, "f" |
| OP-08 | Relatórios gerenciais por faixa etária e sexo | Art. 11, II, "f" |
| OP-09 | Exportação de relatórios em PDF ou planilha | Art. 11, II, "f" |
| OP-10 | Migração dos dados legados | A mesma base da operação de origem |
| OP-11 | Backup e restauração | Art. 11, II, "f", com fundamento nos arts. 46 a 49 |
| OP-12 | Consulta de CEP a serviço externo | Não há tratamento de dado pessoal nesta operação |
| OP-13 | Registro de contatos e acompanhantes | Art. 7º, IX — legítimo interesse |
| OP-14 | Gestão de contas de usuário | Art. 7º, V — execução de contrato de trabalho |
| OP-15 | Registro de auditoria de ações | Art. 7º, II — obrigação legal, combinada com o art. 37 e os arts. 46 a 49 |

**OP-08 e OP-09.** Relatórios agregados são tratados como dado pessoal: com 146 pacientes, cruzamentos
finos identificam pessoas, e o art. 12 não se aplica. Não há supressão de células porque quem
exporta é a administração, que já acessa os dados nominais (DEC-44).

#### 3.8.2 Retenção

Ver §3.4.4.

#### 3.8.3 Transparência e direitos do titular

| Item | Como é atendido |
|---|---|
| Informação ao paciente, primeira camada | Frase na ficha de cadastro: "Os dados fornecidos serão armazenados junto a documentos no sistema de informação da clínica. Para mais informações, tratar com a recepção" (DEC-46) |
| Informação ao paciente, segunda camada | Aviso de privacidade completo, disponível na recepção (PJ-05) |
| Informação ao funcionário | Termo de ciência de uso, assinado após o treinamento; acesso em produção só com o termo assinado (DEC-47) |
| Canal do titular | Registro e acompanhamento de pedidos (RF-1009). A clínica opera sem encarregado, por decisão do controlador com parecer jurídico (DEC-12, risco R-14 aceito) |
| Acesso | Cópia dos dados e dos documentos do paciente, com registro da entrega (RF-1009) |
| Correção | Dado cadastral: alteração auditada. Documento: nova versão com motivo (RF-708) |
| Eliminação e revogação | Não se aplicam como direito sobre dado tratado por obrigação legal ou tutela da saúde, dentro do prazo de guarda |

#### 3.8.4 Pendências jurídicas

| ID | Pendência | Situação | Bloqueia |
|---|---|---|---|
| PJ-01 | Receita bruta contra o teto de pequeno porte | Aberta | — |
| PJ-02 | Classificação de alto risco | Aberta; pode tornar o encarregado obrigatório | — |
| PJ-03 | Prazo de guarda das fichas de frequência em papel | Aberta | — |
| PJ-04 | Prazo de retenção dos logs | Resolvida: 5 anos (DEC-45) | — |
| PJ-05 | Aviso de privacidade completo, frase da ficha, roteiro do canal do titular | Aberta | **Go-live** |
| PJ-06 | Termo de ciência de uso do sistema | Aberta; assinatura após o treinamento (DEC-47) | **Go-live** |
| PJ-07 | Necessidade de relatório de impacto | Depende de PJ-02 | — |
| PJ-08 | Desenvolvimento dentro do vínculo de emprego | Resolvida: confirmado. Reenquadrar o contrato existente como confidencialidade e titularidade do código | — |

### 3.9 Cenários de atributo de qualidade

Entrada principal da Macroentrega II. Cada cenário é também um roteiro de teste de homologação.

| ID | Cenário |
|---|---|
| QAS-01 | A recepcionista busca um paciente pelo nome, em horário de pico, com 1.200 pacientes na base. O sistema retorna a lista com desempate por data de nascimento e nome da mãe **em menos de 2 s**. |
| QAS-02 | Ao fim do turno, a recepcionista lança 3 ausências entre 24 pacientes e confirma a sessão. A operação completa consome **no máximo 4 interações** e **menos de 3 s** de resposta. |
| QAS-03 | O serviço de consulta de CEP fica indisponível durante um cadastro. O sistema **conclui o cadastro**, marca o CEP como não verificado e o inclui na lista de pendências, **sem impedir a gravação**. |
| QAS-04 | O servidor falha por defeito de hardware, com os discos preservados. A partir do backup diário, o sistema é restaurado e volta a operar **em até 4 h**, com perda máxima de **24 h** de dados (DEC-56). |
| QAS-05 | Um arquivo malicioso é apresentado à digitalização, com extensão permitida e conteúdo falsificado. O sistema o **recusa antes do armazenamento definitivo**, registra o bloqueio e informa o operador. |
| QAS-06 | Um documento de prontuário é consultado por um usuário. O sistema registra autor, documento e instante, e o registro **não pode ser alterado pela aplicação**. |
| QAS-07 | Ao fim de 20 anos de operação, com cerca de 1.200 pacientes e 25 mil documentos, os tempos de busca e de abertura de cadastro permanecem **dentro dos alvos de RNF-201 e 202**. |
| QAS-08 | A extração automática de dados apresenta qualidade insuficiente em homologação. O recurso é **desligado por configuração** e o sistema entra em produção com digitalização e conferência manual, **sem alteração de código**. |
| QAS-09 | A estação é deixada desatendida no balcão. A sessão é bloqueada automaticamente, e qualquer ação subsequente é atribuída ao usuário que se autenticar, **não ao anterior**. |
| QAS-10 | Um administrador autoriza a alteração de uma sessão já confirmada, com a recepcionista logada. O registro guarda **as duas identidades** separadamente, o valor anterior, o novo e o motivo. |
| QAS-11 | Uma estação é infectada por ransomware. O repositório de documentos e a cópia fora do servidor **permanecem íntegros**, porque nenhum dos dois é alcançável como pasta de rede e a cópia externa está desconectada. Pressupõe o servidor dedicado. |
| QAS-12 | Um dispositivo conectado à rede sem fio tenta conexão com o banco. A conexão é **recusada**, e a tentativa é registrada. |
| QAS-13 | Um registro de auditoria é alterado diretamente no banco. A **próxima verificação da cadeia aponta o registro alterado** e a data aproximada da alteração. |
| QAS-14 | O servidor é perdido e a pessoa de TI não está disponível. Com a documentação de operação (RNF-706) e a chave em custódia (RNF-622), **outra pessoa restaura o sistema e o acervo legível** dentro do RTO. |
| QAS-15 | O servidor é perdido por completo, com os discos. A partir da cópia semanal mantida fora da máquina, o sistema é restaurado com perda máxima de **7 dias** de dados. Os dias perdidos são reconstituídos a partir das fichas de frequência em papel, que continuam sendo o comprovante oficial (RN-03, DEC-56). |

---

## 4. Verificação

### 4.1 Ambiente

Desenvolvimento com dados fictícios. **Homologação no servidor dedicado**, nunca na estação da
recepção: homologar em ambiente diferente do de produção não prova nada sobre produção. A carga real
é ensaiada no servidor de produção antes do go-live.

### 4.2 Verificações que exigem preparação específica

| Verificação | Requisitos | Observação |
|---|---|---|
| Medição do sistema de estoque **antes** da implantação | RNF-302 | Sem medição anterior não há como provar ausência de degradação |
| Cronometragem com a recepcionista | RNF-403 a RNF-405 | Com a pessoa que vai usar, não em laboratório |
| Arquivo EICAR e arquivo com extensão falsificada | SEG-03, SEG-24, QAS-05 | Evidência registrada |
| Restauração completa em máquina limpa, **por outra pessoa**, incluindo a recuperação da chave | RNF-503, RNF-505, RNF-622, QAS-14 | Cronometrada contra o RTO de 4 h |
| Corte de energia com gerador desligado até o desligamento automático | RNF-508 | Seguido de verificação de integridade do banco e dos documentos |
| Alteração deliberada de registro de auditoria e expurgo simulado | RNF-615, RNF-628, QAS-13 | A verificação da cadeia deve apontar a alteração |
| Tentativa de conexão ao banco a partir de estação e de terminal do estoque | RNF-614, QAS-12 | Com a credencial do estoque |
| Inspeção da estação após uso | RNF-616, SEG-28 | Downloads, cache e pastas temporárias sem cópia de documento |
| Conferência amostral humana da carga | RF-1106, RNF-103 | Zero exceções não basta |
| Extração desligada por configuração | RNF-702, QAS-08 | O módulo de documentos continua funcionando |

### 4.3 Critério de aceitação da homologação

1. Todos os requisitos desta ERS verificados pelo método indicado, com evidência registrada.
2. Nenhum defeito aberto em requisito de segurança (§3.5.6 e §3.6) ou de cálculo derivado (RNF-101).
3. RNF-403 a RNF-405 atingidos com a recepcionista.
4. Cenários QAS-01 a QAS-14 demonstrados.
5. Termos de ciência de uso assinados por todos os usuários antes da liberação do acesso (DEC-47).

---

## 5. Pontos a validar

Itens que esta ERS precisou resolver ou deixar em aberto e que a validação da Fase 4 deve confirmar.
Nenhum bloqueia o início da arquitetura.

| # | Ponto | Proposta desta ERS | Bloqueia |
|---|---|---|---|
| 1 | ~~**Qual documento é exigido no óbito**~~ | **Resolvida (DEC-50):** certidão de óbito, emitida pelo cartório | — |
| 2 | ~~**Faixas etárias** dos relatórios~~ | **Resolvida (DEC-49):** onze faixas de dez anos, de 0–9 a 100 ou mais | — |
| 3 | ~~**Documento comprobatório para os cinco eventos**~~ | **Resolvida (DEC-53):** vale a tabela da §3.2.6 — os cinco eventos exigem documento | — |
| 4 | ~~**Escalas fixas ou configuráveis**~~ | **Resolvida (DEC-52):** as seis escalas são tabela fixa; acrescentar ou alterar escala exige nova versão | — |
| 5 | ~~**Windows das estações**~~ | **Resolvida (DEC-51):** o parque fica como está, com Windows 10 e 11. O risco de estação sem suporte de segurança é aceito e compensado pelos controles da §3.5.6.1 | — |
| 6 | ~~**Abertura da sessão de turno**~~ | **Resolvida (DEC-54):** abertura automática pelo calendário, como na §3.2.5 | — |
| 7 | **Refinamentos da Fase 2** listados no Apêndice A.2 | Validar em bloco | — |
| 8 | ~~**Escopo de acesso do perfil de enfermagem**~~ | **Resolvida (DEC-55):** identificação, escala, frequência e relatórios de sessões — RF-901, RF-906, RF-908 e RF-916. Sem módulo de documentos e sem relatórios de cadastro | — |
| 9 | ~~**Estação da enfermagem**~~ | **Resolvida (DEC-55):** terminal próprio, sob as mesmas regras das demais estações — login individual, bloqueio por inatividade, antimalware, criptografia de disco e nenhuma cópia residual (§3.5.6.1) | — |

---

## Apêndice A — Alterações sobre a baseline aprovada

### A.1 Emenda 01 — incorporada

Aprovada pela gestão, conforme informado pelo responsável do projeto em 22/09/2026. A formalização
por assinatura se dá na validação desta ERS (Fase 4).

| Item | Antes | Depois | Decisão |
|---|---|---|---|
| RF-913 a RF-918 | — | Relatório mensal bloqueado até confirmação; sinalização de sessões não confirmadas; marca de mês alterado; balanço mensal; ausências exibidas ao acrescentar paciente; pareamento automático | Modelo de domínio §7.11 a §7.14 |
| RF-919 e RF-920 | — | Rascunho de cadastro, com descarte automático | Casos de uso, UC-01 |
| RF-1008 | Exigir senha da administração para excluir cadastro criado por engano | Autorização a partir da sessão do próprio autorizador, estendida às alterações de registros confirmados | DEC-42 |
| RF-1203 | Tipos de documento, checklist e exigidos por evento como **configuração** | Definidos no sistema, **não configuráveis**; sem tipo genérico | DEC-41 |
| RF-712 e RF-713 | — | Identificação do paciente de destino na conferência; revinculação auditada | ND-92 |
| RF-1010 | — | Pendências por perfil, conforme matriz §3.2.13 | ND-97 |
| RF-1011 | — | Aviso de falha da cadeia de auditoria à administração | DEC-43 |

Contagem: a baseline declara 84 requisitos no rodapé, mas suas tabelas contêm 90. Vale o conteúdo
aprovado; o número do rodapé estava errado. Com a Emenda 01, são 102; com as alterações da validação, 104.

### A.2 Refinamentos da Fase 2 — a validar

Detalhamentos que não mudam o escopo aprovado, mas mudam texto de requisito ou de controle.

| Item | Refinamento | Origem |
|---|---|---|
| RF-501 | Abertura automática da sessão de turno (confirmado por DEC-54) | Modelo §7.5 |
| RF-504 | Extra como estado provisório do mês, convertível em reposição | Modelo §7.14 |
| RF-711 | Foto em cores | Confirmado em 21/09/2026 |
| RF-912 | Exportação só com as colunas do relatório | ND-94 |
| RF-1009 | Cópia dos documentos no atendimento de pedido de acesso | ND-95 |
| SEG-19 | Exibição dentro da aplicação, download explícito e auditado | Modelagem de ameaças §3.2 |
| RNF-301 | Instância de banco própria, separada da do estoque | Viabilidade §2.6 |
| RNF-408 | Pendências por perfil | ND-97 |
| RNF-611 | Lista de destinos de saída permitidos | Modelagem de ameaças §3.6 |
| RNF-804 | Tipos de documento fixos | DEC-41 |
| RNF-805 | Escalas fixas (confirmado por DEC-52) | Modelo §3.2 |
| RN-01 | Sinalização sem bloqueio | Modelo §7.9 |

### A.3 Alterações na validação (Fase 4)

| Item | Alteração | Decisão |
|---|---|---|
| RF-1001 | Quinto perfil: enfermagem | DEC-48 |
| RF-406 | Enfermagem registra alocação, trocas e sessões extras diretamente | DEC-48 |
| RF-809 | Pendência de termo para a recepção quando a enfermagem registra troca pontual ou sessão extra | DEC-48 |
| RF-921 | Presença não prevista vira pendência de ciência para a enfermagem | DEC-48 |
| §3.2.13 | Coluna de enfermagem na matriz de pendências | DEC-48 |
| RF-910, RF-1206 | Faixas etárias definidas: dez em dez anos, de 0–9 a 100 ou mais | DEC-49 |
| RF-607, §3.2.6 | O documento exigido no óbito é a certidão de óbito | DEC-50 |
| RNF-616, §3.5.6.1 | Estações permanecem como estão; risco aceito e compensado | DEC-51 |
| RNF-805 | Escalas como tabela fixa, alteráveis por nova versão | DEC-52 |
| RN-08, INV-11, §3.2.6 | Documento comprobatório exigido nos cinco eventos | DEC-53 |
| RF-501 | Abertura automática da sessão de turno | DEC-54 |
| §1.5, RF-1001 | Escopo de acesso da enfermagem e terminal próprio | DEC-55 |
| RNF-502, QAS-04, QAS-15 | Perda máxima de 24 h com os discos preservados e de 7 dias na perda total; cópia fora da máquina mantida semanal | DEC-56 |
| RF-102 | Mínimo para salvar o paciente; abaixo dele, só rascunho | DEC-57 |
| RF-103, RF-109, RF-1106, §3.2.13 | CPF e CNS inválidos não são gravados; na carga, valor inválido vai ao relatório de exceções | DEC-58 |
| INV-15 | CPF e CNS únicos | DEC-59 |
| RF-1008 | Confirmação automática quando a solicitação parte da administração | DEC-60 |
| RF-1008 | Exclusão de cadastro criado por engano descarta automaticamente o que está vinculado | DEC-61 |
| RN-02, INV-01 | Alcance limitado a fatos datados; captura de documento após o óbito permitida | DEC-62 |
| RNF-601 | Uma sessão ativa por usuário | DEC-63 |
| RF-922 | Apresentação antecipada do próximo turno, com as pendências de cada paciente | DEC-64 |
| RF-603, RF-604 | Trocas e extras planejadas após o evento de encerramento são canceladas automaticamente; presença posterior exige correção autorizada | DEC-65 |
| RF-507 | Sessão não realizada, registrada pela administração | DEC-66 |
| §3.2.5 | Confirmação liberada na última hora do turno | DEC-67 |
| RNF-501 | Janela de disponibilidade 05:00–20:00 | DEC-68 |
| RF-915 | Marca de mês alterado restrita aos relatórios de frequência | DEC-69 |
| §3.2.13 | Seis pendências acrescentadas à matriz | DEC-70 |
| §3.2.13, RF-109 | Pendências de cadastro, checklist e alocação só para paciente em tratamento | DEC-71 |
| §3.2.13 | Âncora mensal da cadeia de auditoria para a administração | DEC-72 |
| RF-303 | Removido: registro da instituição que encaminhou o paciente | DEC-73 |

## Apêndice B — Decisões registradas após a Fase 2

As decisões DEC-01 a DEC-40 estão nos documentos das Fases 0 a 2. As posteriores:

| ID | Decisão |
|---|---|
| DEC-41 | Tipos de documento fixos no sistema; novo tipo exige nova versão |
| DEC-42 | Autorização da administração a partir da sessão do próprio autorizador |
| DEC-43 | Falha na cadeia de auditoria notifica também a administração, que é quem encerra o aviso |
| DEC-44 | Sem supressão de células em relatórios agregados; agregados tratados como dado pessoal |
| DEC-45 | Registros de auditoria guardados por 5 anos; a prova de integridade dos documentos acompanha o documento por 20 anos |
| DEC-46 | Sem termo assinado de armazenamento. Frase informativa na ficha de cadastro e aviso completo na recepção |
| DEC-47 | Termo de ciência de uso assinado após o treinamento; acesso em produção só com o termo assinado |
| DEC-48 | Perfil de enfermagem provisionado: a gestão das escalas passa a ela; termos decorrentes geram pendência de impressão e assinatura para a recepção |
| DEC-49 | Faixas etárias dos relatórios: onze faixas de dez anos, de 0–9 a 100 ou mais |
| DEC-50 | O documento comprobatório do óbito é a certidão de óbito, emitida pelo cartório |
| DEC-51 | As estações permanecem com o Windows atual, sem migração. Risco de sistema sem suporte aceito, com os controles compensatórios da §3.5.6.1 |
| DEC-52 | As seis escalas são tabela fixa; acrescentar ou alterar escala exige nova versão |
| DEC-53 | Os cinco eventos exigem documento comprobatório, conforme a tabela da §3.2.6 |
| DEC-54 | A sessão de turno é aberta automaticamente pelo calendário; só vale depois de confirmada |
| DEC-55 | Enfermagem acessa identificação, escala, frequência e relatórios de sessões, em terminal próprio; sem módulo de documentos |
| DEC-56 | Perda máxima de 24 h em falha de hardware e de 7 dias em perda total do servidor; cópia fora da máquina mantida semanal |
| DEC-57 | Mínimo para salvar o paciente: nome, data de início do tratamento e número de prontuário. Sem o mínimo, só rascunho; com ele, o usuário escolhe |
| DEC-58 | CPF e CNS com dígito verificador inválido não são gravados; ausência gera pendência. Na carga inicial, valor inválido não é importado, vai ao relatório de exceções e o paciente entra com a pendência |
| DEC-59 | CPF e CNS únicos entre pacientes; a repetição bloqueia, como no prontuário |
| DEC-60 | Autorização solicitada pela própria administração é confirmada automaticamente |
| DEC-61 | Aprovada a exclusão de cadastro criado por engano, tudo o que está vinculado é descartado automaticamente; sem transferência a outro paciente |
| DEC-62 | A proibição de registro após o óbito alcança fatos datados; a captura de documento após o óbito é permitida |
| DEC-63 | Uma sessão ativa por usuário; novo login encerra a anterior |
| DEC-64 | Os pacientes do próximo turno são apresentados uma hora antes do início, com as pendências de cada um, para a recepção se organizar durante a limpeza da sala |
| DEC-65 | Ao registrar evento de encerramento, trocas e extras planejadas depois da data são canceladas automaticamente; presença confirmada depois da data, possível só com evento retroativo, exige correção autorizada antes do registro |
| DEC-66 | Sessão que não aconteceu, por fechamento excepcional da clínica, é registrada pela administração como não realizada, com motivo; sai das previstas e não gera ausências |
| DEC-67 | A confirmação da sessão de turno é liberada na última hora do turno, com antecedência configurável e igual para os três turnos |
| DEC-68 | Janela de disponibilidade de 05:00 às 20:00, de segunda a sábado; às 05:00 o sistema já mostra a preparação do turno 1 |
| DEC-69 | A marca de mês alterado aparece nos relatórios de frequência que incluam o mês; os demais relatórios não mudam com alteração de frequência |
| DEC-70 | Acrescentadas à matriz de pendências: documento aguardando conferência, documento bloqueado, documentos elegíveis para descarte, job que não rodou, antimalware desatualizado e disco acima do limite |
| DEC-71 | Pendências de cadastro incompleto, checklist e sem alocação valem só para paciente em tratamento |
| DEC-72 | A âncora mensal da cadeia de auditoria aparece como pendência da administração, para anotação fora do sistema |
| DEC-73 | A instituição que encaminhou o paciente deixa de ser registrada no sistema |

## Apêndice C — Rastreabilidade

Por grupo de requisitos. A rastreabilidade por requisito individual está na coluna "Origem" das
tabelas e nos documentos de origem.

| Grupo | Requisitos funcionais | Casos de uso | Base legal | Qualidade e segurança | Ameaças |
|---|---|---|---|---|---|
| Cadastro | RF-101–111, 919, 920 | UC-01, 02, 03 | OP-01 | RNF-101, 102, 201–203, 401, 403, 404 | — |
| Contatos | RF-201, 202 | UC-01, 03 | OP-13 | — | — |
| Cobertura | RF-301–302 | UC-01, 03 | OP-02 | — | — |
| Escala | RF-401–406 | UC-04 (ator: enfermagem) | OP-03 | RNF-902 | — |
| Frequência | RF-501–507, 917, 918, 921, 922 | UC-05, 06, 14 | OP-04 | RNF-204, 205, 402, 705 | — |
| Eventos | RF-601–607 | UC-07, 14 | OP-01, 05 | RNF-101 | — |
| Documentos | RF-701–713 | UC-08 | OP-05, 07 | RNF-208, 604, 606, 610, 615–628; SEG-01–31 | T-04 a T-08, T-10 a T-22, T-24, T-26 |
| Emissão | RF-801–809 | UC-09, 10 | OP-06, 07 | RNF-206, 405, 703, 903 | — |
| Relatórios | RF-901–916 | UC-11, 12, 13 | OP-08, 09 | RNF-207, 607 | LINDDUN 5.1, 5.2 |
| Acesso | RF-1001–1011 | UC-14, 15, 16, 18 | OP-14, 15 | RNF-601–603, 605, 609, 613, 623, 625 | T-01, 02, 09, 23, 25 |
| Migração | RF-1101–1108 | UC-17 | OP-10 | RNF-103 | — |
| Configuração | RF-1201–1206 | UC-15 | — | RNF-703, 804 | — |

## Apêndice D — Siglas

| Sigla | Significado |
|---|---|
| ANPD | Autoridade Nacional de Proteção de Dados |
| CDR | Reconstrução de conteúdo, do inglês *content disarm and reconstruction* |
| CNS | Cartão Nacional de Saúde |
| ERS | Especificação de Requisitos de Software |
| IBGE | Instituto Brasileiro de Geografia e Estatística — código de município |
| LGPD | Lei Geral de Proteção de Dados Pessoais |
| PDF/A | Formato PDF para arquivamento de longo prazo |
| QAS | Cenário de atributo de qualidade |
| RPO / RTO | Perda máxima de dados aceitável / tempo máximo de retorno |
| TLS | Protocolo de cifragem do tráfego de rede |

---

## Registro de validação e aprovação

| Papel | Nome | Data | Assinatura |
|---|---|---|---|
| Coordenação administrativa | | | |
| Direção clínica | | | |
| Responsável pelo projeto | Marco Túlio Silva Oliveira | | |

---

*Totais: 104 requisitos funcionais, 8 regras de negócio, 75 requisitos de qualidade, 31 controles de ingestão, 6 requisitos de interface com o usuário, 10 restrições de projeto, 15 invariantes, 15 cenários de atributo de qualidade.*
