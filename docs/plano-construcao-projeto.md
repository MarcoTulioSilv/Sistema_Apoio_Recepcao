# Plano de Construção do Projeto de Software
### Fundamentado no SWEBOK v4.0 (IEEE Computer Society, 2024) e na legislação brasileira aplicável

**Versão:** 0.1 (rascunho inicial — a ser refinado após definição do domínio)
**Data:** 03/09/2026
**Status:** Aguardando caracterização do sistema-alvo

---

## 1. Propósito deste plano

Definir o processo, os artefatos, os papéis e os pontos de controle que conduzirão o projeto desde a
elicitação de requisitos até a codificação, com conformidade legal projetada desde o início
(*privacy by design*, art. 46 da LGPD) e não acrescentada ao final.

O plano cobre quatro macroentregas encadeadas:

| # | Macroentrega | KA SWEBOK v4.0 predominante | Onde acontece |
|---|---|---|---|
| I | **Requisitos** | Software Requirements | **Este chat** |
| II | Arquitetura | Software Architecture | Chat seguinte |
| III | Design detalhado | Software Design | Chat seguinte |
| IV | Codificação e verificação | Software Construction / Testing | Chat seguinte |

Atravessam todas: *Software Security*, *Software Quality*, *Software Configuration Management*,
*Software Engineering Management* e *Professional Practice*.

---

## 2. Base normativa e legal

### 2.1 Engenharia de software

- **SWEBOK v4.0** — guia de referência das 18 áreas de conhecimento.
- **ISO/IEC/IEEE 29148:2018** — engenharia de requisitos; estrutura da ERS (Especificação de Requisitos de Software), StRS e SyRS.
- **ISO/IEC 25010:2023** — modelo de qualidade de produto; taxonomia dos requisitos não funcionais.
- **ISO/IEC/IEEE 42010** — descrição de arquitetura (visões e pontos de vista).
- **ISO/IEC 27001 / 27002** — controles de segurança da informação.
- **ISO/IEC 27701** — extensão de privacidade (PIMS), ponte natural com a LGPD.
- **ISO 31000** — gestão de riscos.

### 2.2 Legislação brasileira — núcleo comum

| Norma | O que impõe ao projeto |
|---|---|
| **Lei 13.709/2018 (LGPD)** | Bases legais, direitos do titular, segurança, RIPD, encarregado, incidentes |
| **Lei 15.352/2026** | Transformou a ANPD em autarquia especial (agência reguladora), com fiscalização ampliada |
| **Resoluções CD/ANPD** | Encarregado, comunicação de incidentes, transferência internacional, dosimetria de sanções, agentes de pequeno porte |
| **Lei 12.965/2014 (Marco Civil)** + Decreto 8.771/2016 | Guarda de logs de acesso, neutralidade, responsabilidade de provedores |
| **Lei 8.078/1990 (CDC)** | Se houver relação de consumo: informação clara, direito de arrependimento, vedação a práticas abusivas |
| **Lei 13.146/2015 (LBI)** + WCAG 2.1 / eMAG | Acessibilidade digital obrigatória |
| **Lei 14.063/2020** | Assinaturas eletrônicas (simples, avançada, qualificada/ICP-Brasil) |
| **Lei 15.211/2025 (ECA Digital)** + Decreto 12.880/2026 | Vigente desde 17/03/2026. Aplica-se a qualquer produto de TI direcionado a menores **ou de acesso provável por eles** — verificação de idade confiável, vinculação a responsável, vedação a publicidade comportamental e a *design* manipulativo. Fiscalizada pela ANPD |

### 2.3 Legislação setorial — a confirmar conforme o domínio

- **Saúde:** Lei 13.787/2018 (prontuário eletrônico), resoluções CFM, certificação SBIS/CFM, RDCs da Anvisa para SaMD.
- **Financeiro:** normas do BCB (Open Finance, Res. Conjunta nº 1/2020), Circular 3.909, Lei 9.613/1998 (PLD/FT).
- **Setor público:** Lei 12.527/2011 (LAI), Lei 14.133/2021 (licitações), Lei 14.129/2021 (Governo Digital), ePING/ePWG.
- **Trabalhista/RH:** eSocial, Portaria 671/2021 (ponto eletrônico — REP-P).
- **IA embarcada:** a regulamentação está em curso; a IA é foco declarado de fiscalização da ANPD no biênio 2026-2027. Tratar como risco regulatório monitorado.

> ⚠️ O ambiente normativo brasileiro está em movimento acelerado (Agenda Regulatória ANPD 2025-2026).
> Todo requisito de conformidade deve registrar a **data de verificação** da norma citada.

---

## 3. Fases da Macroentrega I — Requisitos

Segue o processo de requisitos do SWEBOK v4.0: *Elicitation → Analysis → Specification → Validation*,
com *Requirements Management* em paralelo.

### Fase 0 — Contexto e escopo (sessões 1–2)

**Objetivo:** entender o problema antes de descrever a solução.

- Declaração do problema e objetivos de negócio (mensuráveis).
- Identificação de *stakeholders* e classificação por influência/interesse.
- Fronteira do sistema: diagrama de contexto, sistemas externos, integrações.
- Restrições conhecidas: orçamento, prazo, plataforma, equipe, legado.
- Premissas e dependências.
- **Triagem legal preliminar:** o sistema trata dados pessoais? Sensíveis (art. 11)? De menores? Há relação de consumo? É setor regulado?

**Saídas:** Documento de Visão e Escopo · Matriz de Stakeholders · Diagrama de Contexto · Nota de Triagem Legal.

---

### Fase 1 — Elicitação (sessões 3–5)

**Objetivo:** descobrir necessidades, não coletar pedidos.

Técnicas do SWEBOK a combinar:

| Técnica | Quando usar |
|---|---|
| Entrevistas estruturadas | Aprofundar papéis-chave |
| Workshops facilitados (JAD) | Resolver conflitos entre áreas |
| Análise de documentos | Legislação, normas internas, sistema legado |
| Observação / etnografia | Processos tácitos que ninguém sabe descrever |
| Cenários e histórias de usuário | Fluxo ponta a ponta |
| Prototipagem de baixa fidelidade | Requisitos de interface e usabilidade |
| Análise de sistemas concorrentes | *Benchmark* de funcionalidades |

**Saídas:** Backlog bruto de necessidades · Glossário do domínio (termo → definição → sinônimos) · Registro de fontes.

---

### Fase 2 — Análise e modelagem (sessões 6–8)

**Objetivo:** transformar necessidades em requisitos consistentes.

- Classificação: requisitos de negócio → de usuário → funcionais → não funcionais → regras de negócio → requisitos de dados → restrições de projeto.
- Modelagem: casos de uso ou histórias com critérios de aceitação (Gherkin), modelo de domínio conceitual, diagramas de atividade para processos críticos, máquina de estados para entidades com ciclo de vida.
- Negociação e resolução de conflitos entre *stakeholders*.
- Priorização: MoSCoW combinado com WSJF ou valor × risco.
- Análise de viabilidade técnica e econômica.
- **Modelagem de ameaças** (STRIDE) e **modelagem de privacidade** (LINDDUN) sobre os fluxos de dados.

**Saídas:** Modelo de casos de uso · Modelo de domínio · Backlog priorizado · Registro de riscos · Matriz de rastreabilidade v1.

---

### Fase 3 — Especificação (sessões 9–11)

**Objetivo:** produzir a ERS — a fonte única de verdade.

Estrutura conforme ISO/IEC/IEEE 29148:

1. Introdução (propósito, escopo, definições, referências)
2. Descrição geral (perspectiva, funções, usuários, ambiente operacional, restrições, premissas)
3. Requisitos específicos
   3.1 Interfaces externas
   3.2 Requisitos funcionais
   3.3 Requisitos não funcionais (por ISO/IEC 25010: desempenho, segurança, usabilidade, confiabilidade, manutenibilidade, portabilidade, compatibilidade, adequação funcional, proteção)
   3.4 **Requisitos de conformidade legal** (seção dedicada — ver §4)
   3.5 Regras de negócio
4. Matriz de rastreabilidade
5. Anexos: protótipos, dicionário de dados, inventário de dados pessoais

**Padrão de escrita de requisito:**
`RF-###` / `RNF-###` / `RCL-###` (conformidade legal) / `RN-###` (regra de negócio)

Cada requisito carrega: identificador · descrição na forma "O sistema **deve**…" · justificativa ·
origem (*stakeholder* ou norma) · prioridade · critério de verificação · dependências.

**Saída:** ERS versão 1.0.

---

### Fase 4 — Validação (sessão 12)

**Objetivo:** confirmar que a ERS descreve o sistema certo.

- Revisão técnica formal com checklist de qualidade da ISO/IEC/IEEE 29148: cada requisito deve ser **necessário, inequívoco, completo, singular, consistente, verificável, rastreável e viável**.
- Validação com *stakeholders* via protótipo e cenários.
- Derivação de casos de teste de aceitação a partir dos critérios de aceitação (verifica testabilidade).
- **Parecer de conformidade legal:** revisão da seção RCL e decisão sobre necessidade de RIPD (art. 38 da LGPD).

**Saída:** ERS aprovada e sob *baseline* · Casos de teste de aceitação · Parecer de conformidade.

---

### Fase 5 — Gestão contínua (a partir da Fase 3)

- Controle de versão da ERS e *baselines* nomeadas.
- Processo de mudança: solicitação → análise de impacto (via rastreabilidade) → aprovação → atualização.
- Rastreabilidade bidirecional: `necessidade ↔ requisito ↔ elemento de arquitetura ↔ módulo de código ↔ caso de teste`.
- Métricas: volatilidade de requisitos, densidade de defeitos de requisitos, cobertura de rastreabilidade.

---

## 4. Trilha de conformidade — executada em paralelo, não ao final

Cada fase de requisitos tem um entregável de privacidade correspondente:

| Fase | Entregável de conformidade | Fundamento |
|---|---|---|
| 0 | Triagem legal: o sistema está no escopo da LGPD? Do ECA Digital? De norma setorial? | Art. 3º e 4º, LGPD |
| 1 | **Inventário de dados pessoais**: que dado, de quem, para quê, por quanto tempo | Art. 37 (registro das operações) |
| 1 | Mapa de fluxo de dados: coleta → uso → compartilhamento → descarte | Art. 6º, VI (transparência) |
| 2 | **Definição da base legal por operação** — uma por finalidade, não uma para o sistema todo | Art. 7º (dados comuns) e art. 11 (sensíveis) |
| 2 | Aplicação da minimização: cada campo precisa justificar sua existência | Art. 6º, III |
| 2 | LINDDUN / STRIDE sobre os fluxos | Art. 46 (segurança) |
| 3 | Requisitos dos **direitos do titular** (RCL): confirmação, acesso, correção, anonimização, portabilidade, eliminação, informação sobre compartilhamento, revogação de consentimento — cada um vira funcionalidade concreta com prazo de resposta | Art. 18 |
| 3 | Requisitos de retenção e descarte automatizado por finalidade | Art. 15 e 16 |
| 3 | Requisitos de trilha de auditoria, criptografia em trânsito e repouso, controle de acesso por menor privilégio, pseudonimização | Art. 46 a 49 |
| 3 | Requisitos de **revisão de decisões automatizadas**, se houver perfilamento ou IA | Art. 20 |
| 3 | Requisitos de transferência internacional, se houver nuvem ou fornecedor no exterior | Art. 33 a 36 |
| 3 | Requisitos de consentimento granular e revogável para cookies e marketing (banner "aceitar tudo" sem recusa granular contraria o entendimento da ANPD) | Art. 8º + Guia de Cookies ANPD |
| 3 | Se houver menores: verificação de idade confiável (autodeclaração é vedada), vinculação a responsável, ausência de publicidade comportamental | Lei 15.211/2025 |
| 4 | **RIPD** (Relatório de Impacto), quando houver dados sensíveis, larga escala, vigilância sistemática, decisões automatizadas ou tratamento de menores | Art. 38 |
| 4 | Plano de resposta a incidentes com fluxo de comunicação à ANPD e aos titulares | Art. 48 |
| Contínuo | Definição do papel: controlador, operador ou controladores conjuntos — e cláusulas contratuais correspondentes | Art. 5º, VI–VII e art. 39 |
| Contínuo | Encarregado (DPO) nomeado e canal de contato publicado | Art. 41 |

**Princípio operacional:** todo requisito de conformidade é escrito como requisito verificável, com
critério de teste. "O sistema deve respeitar a LGPD" não é requisito. "O sistema deve permitir ao
titular exportar seus dados em formato estruturado e interoperável em até 15 dias corridos da
solicitação, registrando a operação em log de auditoria" é.

---

## 5. Preparação para as macroentregas seguintes

Os requisitos já devem ser escritos pensando no que virá:

- **Arquitetura (KA Software Architecture):** os RNFs são os *drivers* arquiteturais. Serão consolidados em *quality attribute scenarios* (estímulo → ambiente → artefato → resposta → medida) para alimentar decisões de estilo arquitetural e ADRs.
- **Design (KA Software Design):** o modelo de domínio da Fase 2 é a semente do design tático (agregados, entidades, serviços).
- **Codificação (KA Software Construction):** critérios de aceitação viram testes automatizados; requisitos de conformidade viram *guardrails* de código e verificações de esteira.
- **Segurança (KA Software Security):** modelagem de ameaças da Fase 2 alimenta controles de design e testes de segurança.

---

## 6. Cadência de trabalho neste chat

| Sessão | Foco | Entregável |
|---|---|---|
| 1 | Caracterização do sistema e triagem legal | Visão e Escopo |
| 2 | Stakeholders e contexto | Matriz + Diagrama de Contexto |
| 3–5 | Elicitação | Backlog bruto + Glossário |
| 6 | Classificação e modelagem funcional | Casos de uso |
| 7 | RNFs por ISO 25010 + modelo de domínio | Catálogo de RNFs |
| 8 | Inventário de dados, bases legais, ameaças | Mapa de dados + registro de riscos |
| 9–11 | Redação da ERS | ERS v1.0 |
| 12 | Validação e *baseline* | ERS aprovada + testes de aceitação |

A cadência é indicativa e se ajusta ao tamanho real do sistema.

---

## 7. Riscos do processo de requisitos

| Risco | Mitigação |
|---|---|
| Escopo indefinido / *scope creep* | *Baseline* + controle de mudanças com análise de impacto |
| *Stakeholder* ausente descobre requisito tarde | Matriz de stakeholders validada na Fase 0 |
| Requisitos não verificáveis | Checklist 29148 na Fase 4 |
| Conformidade tratada como camada final | Trilha do §4 executada em paralelo |
| Mudança normativa durante o projeto | Data de verificação em cada RCL + revisão trimestral |
| Requisito implícito nunca declarado | Prototipagem e observação na Fase 1 |

---

## 8. O que preciso para iniciar a Fase 0

1. **Qual é o sistema?** Domínio, problema que resolve, quem usa.
2. **Contexto organizacional:** setor privado, público ou acadêmico? Porte?
3. **Natureza dos dados:** haverá dados pessoais? Sensíveis (saúde, biometria, origem racial, opinião política, filiação sindical, religião, dado genético, vida sexual)? De crianças ou adolescentes?
4. **Restrições conhecidas:** prazo, equipe, plataforma-alvo, orçamento, tecnologia obrigatória.
5. **Formalidade esperada:** documentação acadêmica completa ou enxuta e ágil?

---

*Documento vivo. Revisar ao final de cada fase.*
