**PLANO DE TESTES**

Sistema de Apoio à Recepção — SAR

PT_recepcao · Versão 1.0

*Elaborado com base no SWEBOK 4.0 (Software Testing) e na ISO/IEC/IEEE 29119-3*

Data: 2026-10-06 · Classificação: Confidencial — uso interno

## Controle de revisões

| **Versão** | **Data** | **Autor** | **Descrição** |
|---|---|---|---|
| 1.0 | 2026-10-06 | Equipe de desenvolvimento | Versão inicial aprovada. Estratégia, ambientes, casos por área de risco, dados de teste, testes não funcionais, rastreabilidade verificada por máquina, integração contínua, homologação e gestão de defeitos. |

---

## 1. Introdução

### 1.1 Propósito

Define como o SAR é verificado e validado: o que se testa, em que nível, com que técnica, em que
ambiente, com que dados e com que critério se aceita. É o plano que a Macroentrega IV (construção)
executa e que a homologação encerra.

### 1.2 Referências

- ERS-002 v1.0 — requisitos funcionais (RF), de qualidade (RNF), controles de ingestão (SEG),
  invariantes (INV), regras de negócio (RN) e cenários de atributo de qualidade (QAS)
- DDS_recepcao — decisões de design (DD), contratos, esquema físico e guia de componentes
- DAS_recepcao v1.0 — arquitetura e riscos (R-xx)
- SWEBOK v4.0, capítulo Software Testing; ISO/IEC/IEEE 29119-3 (documentação de teste)
- OWASP ASVS 4.0, nível 2, como lista de verificação de segurança da aplicação

### 1.3 Princípios

1. **Teste guiado por risco.** O esforço vai para onde o erro custa mais: frequência que vira
   faturamento, trilha de auditoria, permissões, documentos de prontuário e a migração.
2. **Todo requisito tem verificação, e a rastreabilidade é verificada por máquina** (§7).
3. **Nenhum dado real em teste.** Só dados fictícios gerados (§5). Planilhas reais da clínica nunca
   entram no repositório nem no ambiente de teste.
4. **Todo defeito corrigido ganha um teste** que falharia antes da correção (§10).
5. **O banco garante o que pode garantir**, e o teste confirma que garante (esquema e privilégios).

---

## 2. Estratégia

### 2.1 Níveis

| **Nível** | **O que cobre** | **Ferramenta** | **Onde roda** | **Proporção** |
|---|---|---|---|---|
| Unidade | Regras puras: `CompensacaoEngine`, lista esperada, classificação, prazos derivados, dígitos verificadores, conversão do IBGE, serialização canônica da auditoria, matriz de permissões | pytest, Hypothesis | Toda alteração | Maioria |
| Integração | Serviços com MySQL real: transações, travas, invariantes no banco, privilégios, migrações, fila de ingestão, jobs | pytest com MySQL em contêiner | Toda alteração | Média |
| Contrato | Fronteiras entre módulos e portas do núcleo | import-linter, testes de porta com implementação falsa | Toda alteração | Pequena |
| Sistema | Fluxos completos no navegador, com servidor real | Playwright | Antes de cada entrega | Pequena |
| Aceitação | Roteiros por caso de uso com a recepcionista e a administração; QAS de usabilidade e recuperação | Roteiros manuais (§9) | Homologação | Por marco |

### 2.2 Técnicas (SWEBOK, Test Techniques)

| **Técnica** | **Onde se aplica** |
|---|---|
| Partição de equivalência e valor-limite | Datas (início e fim de período, dia do evento, virada do mês, último minuto antes da liberação da confirmação), tamanhos de arquivo, limites de parâmetros |
| Tabela de decisão | Permissões por perfil e operação (§4 do DDS); situação do paciente; regras da lista esperada |
| Transição de estados | Sessão de turno (futura → preparação → aberta → liberada → vencida → confirmada), ingestão, solicitação de autorização |
| Teste baseado em propriedades | `CompensacaoEngine` (DD-29), serialização canônica da auditoria, conversão do IBGE |
| Teste de mutação, por amostragem | Regras puras críticas; aponta testes que passam sem verificar nada |
| Suposição de erro | Corpus de arquivos maliciosos na ingestão; entradas hostis em todo campo de texto |

### 2.3 Tipos de teste

Funcional, segurança, desempenho, recuperação, acessibilidade, usabilidade e migração. Cada tipo tem
sua seção abaixo.

---

## 3. Ambientes

| **Ambiente** | **Uso** | **Banco** | **Dados** |
|---|---|---|---|
| Desenvolvimento | Docker no Windows; unidade, integração e sistema | MySQL em contêiner | Fábrica de dados fictícios |
| Integração contínua | GitHub Actions, a cada envio ao repositório (§8) | Serviço MySQL na mesma imagem de produção | Fábrica de dados fictícios |
| Homologação | Servidor provisório da clínica, rede local; aceitação, desempenho, recuperação | Imagem de produção (MySQL 9.7 LTS) | Base sintética no volume de 20 anos (§5.2) e carga simulada |
| Produção | Só testes de fumaça após cada implantação, sem criar dado | Produção | Reais, somente leitura no teste |

O relógio é injetável (`Relogio`, §3.7 do DDS): os testes de sessão, prazo e retenção fixam data e
hora, sem depender do relógio da máquina.

---

## 4. Itens de teste por área de risco

### 4.1 Frequência e compensação (risco mais alto: vira faturamento)

| **ID** | **Caso** | **Técnica** | **Rastreia** |
|---|---|---|---|
| CT-FRQ-01 | Lista esperada: alocação vigente, troca chegando, extra planejada, troca saindo pré-marcada como ausente | Tabela de decisão | §7.2 do DDS, P-10 |
| CT-FRQ-02 | Estado da sessão em cada minuto-limite: preparação às 05:00, 10:00 e 15:00; liberação às 09:00, 14:00 e 19:00; vencida após o fim | Valor-limite, transição de estados | DD-23, DD-30, DD-32 |
| CT-FRQ-03 | Confirmação materializa todas as presenças numa transação; nada gravado antes além das exceções | Integração | DD-24, INV-14 |
| CT-FRQ-04 | Duas estações confirmam a mesma sessão ao mesmo tempo: uma confirma, a outra recebe conflito | Integração, concorrência | DD-17 |
| CT-FRQ-05 | Pareamento: ausência mais antiga com presença mais antiga, no mesmo mês | Unidade | RF-918 |
| CT-FRQ-06 | Propriedades da engine: um par por item, mesmo mês, pares = menor conjunto livre, independência da ordem, previstas = regulares + ausências | Propriedades, milhares de meses gerados | DD-29, RNF-101 |
| CT-FRQ-07 | Meses com 4 e 5 ocorrências de cada dia, início e fim de período no meio do mês, dia do evento contando como previsto | Valor-limite | RNF-101, P-09 |
| CT-FRQ-08 | Quinta extra: aviso na 4ª, pendência a partir da 5ª, nunca bloqueio | Valor-limite | RN-01, INV-05 |
| CT-FRQ-09 | Sessão não realizada: sai das previstas e não gera ausência | Unidade | DEC-66 |
| CT-FRQ-10 | Alteração autorizada em mês fechado gera a marca de mês alterado | Integração | DD-26, RF-915 |

### 4.2 Auditoria e autorização

| **ID** | **Caso** | **Rastreia** |
|---|---|---|
| CT-AUD-01 | Serialização canônica: mesmo registro, mesmo hash, em qualquer ordem de campos e após ida e volta ao banco | §3.10 do DDS |
| CT-AUD-02 | Cem operações concorrentes em web e worker: cadeia contínua, sem elo repetido nem faltando | DD-03, DD-71 |
| CT-AUD-03 | Registro alterado diretamente no banco: a verificação aponta o primeiro elo divergente | QAS-13 |
| CT-AUD-04 | Usuário de banco da aplicação não altera nem apaga a trilha | QAS-06, DD-58 |
| CT-AUD-05 | Expurgo de mais de 5 anos preserva a verificação a partir do ponto de corte | RNF-628 |
| CT-AUD-06 | Autorização: duas identidades gravadas; confirmação automática quando a administração pede; invalidação quando o alvo mudou | QAS-10, P-01, §5.3 do DDS |

### 4.3 Acesso e permissões

| **ID** | **Caso** | **Rastreia** |
|---|---|---|
| CT-ACE-01 | Matriz completa: cada operação do catálogo (§4 do DDS) contra cada perfil, gerada a partir da própria matriz em código | Tabela de decisão |
| CT-ACE-02 | TI nunca recebe dado de paciente em nenhuma resposta, inclusive em pendências e mensagens de erro | RF-1004, RNF-625 |
| CT-ACE-03 | Enfermagem não alcança documentos por nenhuma rota | DEC-55 |
| CT-ACE-04 | Bloqueio progressivo de login; tempo de resposta igual para login existente e inexistente | §5.2 do DDS |
| CT-ACE-05 | Uma sessão ativa por usuário; novo login encerra a anterior | DEC-63 |
| CT-ACE-06 | Inatividade encerra a sessão; requisição automática de atualização não renova | QAS-09, DD-19 |
| CT-ACE-07 | Token de sessão e de captura gravados só como hash | DD-05 |

### 4.4 Cadastro

| **ID** | **Caso** | **Rastreia** |
|---|---|---|
| CT-CAD-01 | Mínimo para salvar o paciente (nome, início, prontuário); abaixo dele, só rascunho | DEC-57 |
| CT-CAD-02 | CPF e CNS: válidos, inválidos conhecidos, repetidos, ausentes | DEC-58, DEC-59, RNF-102 |
| CT-CAD-03 | Tríade coincidente: alerta com confirmação; adiada enquanto faltar um dos três | INV-08 |
| CT-CAD-04 | Serviço de CEP fora do ar: cadastro concluído, CEP não verificado, pendência criada | QAS-03 |
| CT-CAD-05 | Telefones: um dono só; telefone de contato não vai para o paciente | INV-12 |
| CT-CAD-06 | Anulação: impacto mostrado antes; tudo descartado na aprovação | DEC-61 |
| CT-CAD-07 | Evento retroativo com presença posterior: impede e oferece a autorização | DEC-65 |

### 4.5 Documentos e ingestão

| **ID** | **Caso** | **Rastreia** |
|---|---|---|
| CT-DOC-01 | Corpus hostil (§6.2): cada arquivo recusado antes do armazenamento, com o motivo | QAS-05, SEG-02 a 12 |
| CT-DOC-02 | EICAR com extensão permitida: detectado e registrado | SEG-24 |
| CT-DOC-03 | Reconstrução: saída é PDF/A sem camada de texto, validada pelo veraPDF; foto sem metadados | SEG-10, DC-07 |
| CT-DOC-04 | Hash conferido em cada etapa; arquivo alterado no disco bloqueia a leitura | SEG-15, SEG-27, DD-38 |
| CT-DOC-05 | Worker interrompido no meio do processamento retoma a ingestão do início | §8.4 do DDS |
| CT-DOC-06 | Quarentena cifrada, expira em 24 h e fica fora do backup | DD-34, SEG-29 |
| CT-DOC-07 | Campos candidatos apagados ao concluir, rejeitar ou expirar; texto integral nunca gravado | P-18, SEG-31 |
| CT-DOC-08 | Extração desligada por configuração: digitalização e conferência seguem | QAS-08, RNF-702 |
| CT-DOC-09 | Retenção derivada: sem prazo em tratamento; 20 anos do último registro; zerada no retorno | DD-01 |
| CT-DOC-10 | Descarte destrói a chave; o documento fica ilegível também no backup após o horizonte | DD-04 |
| CT-DOC-11 | Agente: origem não configurada recebe 403 sem acionar o scanner; segunda captura simultânea recebe 409 | DD-39 |
| CT-DOC-12 | Agente: página em BMP chega ao servidor como PNG; nenhum arquivo de imagem criado na estação | DD-77, SEG-28 |
| CT-DOC-13 | Agente: alimentador com N folhas gera N páginas; alimentador vazio gera a mensagem certa | §8.5 do DDS |
| CT-DOC-14 | Agente: queda de rede no meio do envio repete a página e, esgotadas as tentativas, interrompe sem página faltando em silêncio | §8.5 do DDS |

### 4.6 Emissão e relatórios

| **ID** | **Caso** | **Rastreia** |
|---|---|---|
| CT-EMI-01 | Modelo .docx hostil (macro, laço, filtro, vínculo externo, variável desconhecida) recusado no envio | DD-42 |
| CT-EMI-02 | Variável com texto contendo `{{ }}`, `<` e `&` sai literal no PDF | DD-42 |
| CT-EMI-03 | Conversor sem rede: tentativa de buscar recurso externo falha | DD-46 |
| CT-REL-01 | Relatório mensal bloqueado com sessão pendente, com a lista do que falta | RF-913 |
| CT-REL-02 | Tela, PDF e XLSX com as mesmas colunas e marcas | RF-912, DD-44 |
| CT-REL-03 | Nome iniciando com `=`, `+`, `-` ou `@` sai como texto no XLSX | DD-45 |

### 4.7 Migração

| **ID** | **Caso** | **Rastreia** |
|---|---|---|
| CT-MIG-01 | Planilhas sintéticas com os defeitos reais conhecidos (§5.3): contagem fecha, nenhuma linha some | RNF-103 |
| CT-MIG-02 | Conversão do IBGE de 6 para 7 dígitos por consulta, inclusive em município fora da regra do dígito | DD-53 |
| CT-MIG-03 | Simulação não deixa nada no banco além do relatório | DD-66 |
| CT-MIG-04 | Segunda efetivação recusada | DD-66, DD-72 |
| CT-MIG-05 | Terminal do TI mostra só contagens | DD-65 |

### 4.8 Invariantes

Cada invariante tem ao menos um teste que tenta violá-la e confirma a recusa, no nível mais baixo
que a garante.

| **Invariante** | **Garantida em** | **Caso** |
|---|---|---|
| INV-01 | Serviço | Fato datado após o óbito recusado; certidão aceita depois do óbito |
| INV-02 | Banco | Segundo período aberto recusado pelo índice (já em `verificar_esquema.sh`) |
| INV-03, INV-04 | Serviço | Alocação e presença fora de período aberto recusadas |
| INV-05 | Regra pura | Quinta extra sinalizada, nunca bloqueada |
| INV-06 | Banco | Usuários de banco não alteram arquivo, hash nem chave (já em `verificar_esquema.sh`) |
| INV-07, INV-15 | Banco | Prontuário, CPF e CNS repetidos recusados |
| INV-08 | Serviço | Tríade gera alerta com confirmação |
| INV-09, INV-10 | Banco | Unicidade de período e início (DD-27, DD-70) |
| INV-11 | Consulta | Evento sem comprovante aparece como pendência até a ligação |
| INV-12 | Banco | Telefone sem dono ou com dois donos recusado (já em `verificar_esquema.sh`) |
| INV-13 | Serviço e banco | Descarte antes do prazo recusado |
| INV-14 | Estrutural | Presença só existe após confirmação, exceto exceções |

---

## 5. Dados de teste

### 5.1 Fábrica de dados fictícios

Faker em português do Brasil, com CPF e CNS válidos gerados por algoritmo, municípios de Goiás
reais da tabela do IBGE e nomes que nunca coincidem com a base real. Cada teste cria o que usa e
desfaz no fim; nenhum teste depende de outro.

### 5.2 Base de volume

Base sintética com o volume de 20 anos: 1.200 pacientes, 25 mil documentos, 12 meses de frequência
completos. Usada nos testes de desempenho (§6.3) e no QAS-07.

### 5.3 Planilhas sintéticas da migração

Mesma estrutura das planilhas da clínica, preenchidas com dados fictícios e com os defeitos que a
Fase 2 encontrou nas reais: rótulos de telefone trocados, códigos do IBGE de 6 dígitos, CPF com dígito
errado, prontuário repetido, paciente na base sem linha de entrada, paciente com evento de saída
ainda listado. Servem para provar o critério de aceitação da carga antes de ela tocar dado real.

---

## 6. Testes não funcionais

### 6.1 Segurança

| **Verificação** | **Como** | **Quando** |
|---|---|---|
| Controles de ingestão SEG-01 a SEG-31 | Casos CT-DOC e corpus hostil | Integração contínua |
| CSP estrita (DD-09) | Teste de sistema confere o cabeçalho e ausência de código inline nos modelos | Integração contínua |
| Fronteiras e acesso ao banco e à internet | import-linter, 25 contratos | Integração contínua |
| Privilégios de banco | `verificar_esquema.sh`, 24 verificações | Integração contínua e na imagem de produção |
| Análise estática e de dependências | bandit, pip-audit | Integração contínua |
| Segredos no repositório | gitleaks | A cada envio |
| Varredura dinâmica | OWASP ZAP em modo básico contra a homologação | Antes do go-live |
| Rede | Conexão ao banco a partir da rede sem fio recusada | QAS-12, em homologação |
| ASVS nível 2 | Lista de verificação preenchida e anexada | Antes do go-live |

### 6.2 Corpus hostil da ingestão

Arquivos montados para o teste, nunca baixados de fonte externa: EICAR em PDF e em JPEG; executável
renomeado para `.pdf`; extensão dupla; ZIP, SVG e DOCX renomeados; PDF com JavaScript embutido; PDF
poliglota (válido como PDF e como outro formato); bomba de descompressão em PNG; imagem com 50 mil
pixels de lado; PDF com 500 páginas; arquivo vazio; arquivo acima do limite de tamanho; token de
captura vencido e reutilizado.

### 6.3 Desempenho

Na homologação, com a base de volume (§5.2), na rede da clínica, medindo do clique à tela pronta.

| **Medida** | **Alvo** | **Requisito** |
|---|---|---|
| Busca de paciente | < 2 s | RNF-201, QAS-01, QAS-07 |
| Abertura do cadastro | < 2 s | RNF-202, QAS-07 |
| Gravação do cadastro | < 3 s | RNF-203 |
| Mover cartão de paciente | < 1 s, sem recarregar a lista | RNF-204 |
| Confirmação da sessão | < 3 s | RNF-205, QAS-02 |
| Documento emitido | < 10 s | RNF-206 |
| Relatório mensal | < 15 s | RNF-207 |
| Captura até a conferência | < 30 s, A4 a 300 dpi | RNF-208 |
| Rotinas pesadas da madrugada | Terminam ou param às 04:30 | DD-64 |

### 6.4 Recuperação

Ensaios reais, cronometrados, com relatório:

1. **Falha de hardware com discos preservados (QAS-04):** restaurar o backup diário noutro equipamento;
   meta de 4 h e perda máxima de 24 h.
2. **Perda total (QAS-15):** restaurar a partir do pen drive semanal; conferir a perda máxima de 7 dias
   e reconstituir um dia pela ficha em papel.
3. **Sem o TI (QAS-14):** outra pessoa executa o item 1 só com a documentação de operação e a chave em
   custódia.
4. **Ransomware (QAS-11):** confirmar que o repositório e a cópia externa não são alcançáveis como
   pasta de rede a partir da estação.

Antes do go-live e depois a cada seis meses, conforme o DAS.

### 6.5 Acessibilidade e usabilidade

- **Automático:** axe-core nos testes de sistema, em todas as telas, sem violação de nível AA (RNF-406).
- **Teclado:** todo fluxo da recepção feito sem mouse, inclusive mover cartão de paciente pelo botão.
- **Contraste:** pares do guia de componentes, todos acima de 4,5:1.
- **Com a recepcionista, em homologação:** cadastro completo em menos de 5 min (RNF-403), localizar
  paciente em menos de 15 s (RNF-404), emitir documento em menos de 1 min (RNF-405), turno com 3 faltas
  em até 4 interações (RNF-402, QAS-02). Cronometrado, com a ficha em papel ao lado.

---

## 7. Rastreabilidade verificada por máquina

Cada teste automatizado declara o que verifica:

```python
@pytest.mark.requisito("RF-918", "DD-29")
def test_pareamento_cronologico(): ...
```

Os requisitos verificados por inspeção, análise ou demonstração ficam na tabela
`testes/verificacao_manual.md`, com o roteiro e a evidência.

O script `verificar_rastreabilidade.py` lê a ERS, junta as marcas dos testes e a tabela manual, e
falha a integração contínua se:

- algum requisito com verificação por **teste** (coluna "Verif." = T) não tiver teste automatizado;
- algum requisito não tiver verificação nenhuma;
- algum teste citar requisito que não existe ou foi removido.

| **Grupo da ERS** | **Requisitos** | **Suíte principal** |
|---|---|---|
| §3.2.1 Cadastro | 11 | `testes/cadastro/` |
| §3.2.2 Contatos e telefones | 2 | `testes/cadastro/` |
| §3.2.3 Cobertura | 2 | `testes/cadastro/` |
| §3.2.4 Escala e alocação | 6 | `testes/operacao/` |
| §3.2.5 Frequência | 7 | `testes/operacao/` |
| §3.2.6 Eventos | 7 | `testes/cadastro/` |
| §3.2.7 Documentos | 13 | `testes/documentos/` |
| §3.2.8 Emissão | 9 | `testes/emissao/` |
| §3.2.9 Relatórios e frequência estendida | 22 | `testes/emissao/`, `testes/operacao/` |
| §3.2.10 Acesso | 11 | `testes/acesso/` |
| §3.2.11 Migração | 8 | `testes/carga/` |
| §3.2.12 Configurações | 6 | `testes/configuracao/` |
| RNF, SEG, INV, RN, QAS | 75 + 31 + 15 + 8 + 15 | Distribuídos; não funcionais em `testes/qualidade/` |

---

## 8. Integração contínua

Ordem do pipeline no GitHub Actions; a primeira falha interrompe.

| # | **Etapa** | **Comando** |
|---|---|---|
| 1 | Formatação e estilo | `ruff check .` e `ruff format --check .` |
| 2 | Tipos | `mypy sar` |
| 3 | Fronteiras | `lint-imports` |
| 4 | Segredos e dependências | `gitleaks detect`, `pip-audit` |
| 5 | Análise estática | `bandit -r sar` |
| 6 | Unidade | `pytest testes -m "not integracao and not sistema"` |
| 7 | Migração e esquema | `alembic upgrade head`, `alembic downgrade base`, `alembic upgrade head`, `./verificar_esquema.sh` |
| 8 | Integração | `pytest testes -m integracao` |
| 9 | Interface | `tailwindcss -i sar/web/src/sar.css -o sar/web/static/css/sar.css --minify`, pelo executável standalone, sem Node (AD-05) |
| 10 | Sistema | `pytest testes -m sistema` (Playwright e axe-core) |
| 11 | Rastreabilidade e cobertura | `python verificar_rastreabilidade.py --estrito` e relatório de cobertura |

**Cobertura mínima:** regras puras com 100% de ramos; serviços com 85% de linhas; projeto com 80%.
Cobertura é piso, não meta: o teste de mutação por amostragem mostra se ela é real.

---

## 9. Aceitação e homologação

### 9.1 Roteiros

Um roteiro por caso de uso da Fase 2, executado pela própria usuária, com dados fictícios na base de
homologação:

| **Perfil** | **Roteiros** |
|---|---|
| Recepção | Cadastrar paciente; completar pendências; preparar o turno; marcar faltas e confirmar; acrescentar paciente fora da escala; digitalizar e conferir documento; emitir documentos e crachá; registrar evento; atender pedido de titular |
| Enfermagem | Alocar em lote; registrar troca pontual e extra; dar ciência de presença fora da escala |
| Administração | Aprovar e recusar autorizações; anular cadastro; emitir e exportar relatórios; enviar e ativar modelo de documento; tratar exceções e aceitar a carga |
| TI | Criar usuários; executar a carga; verificar a cadeia; restaurar o backup (§6.4) |

### 9.2 Critérios de aceite

- Todos os roteiros executados sem defeito crítico ou alto aberto.
- QAS-01 a QAS-15 demonstrados, com evidência.
- Ensaios de recuperação 1 e 3 (§6.4) cronometrados dentro das metas.
- Conferência amostral da carga aceita (§14.3 do DDS).
- Ata de homologação assinada pela coordenação administrativa e pela direção clínica.

---

## 10. Gestão de defeitos

| **Severidade** | **Definição** | **Exemplo** | **Bloqueia entrega?** |
|---|---|---|---|
| Crítica | Dado errado de frequência, documento ou auditoria; quebra de segurança ou de LGPD | Presença perdida na confirmação; TI vê nome de paciente | Sim |
| Alta | Fluxo principal impedido, sem contorno | Não consegue confirmar a sessão | Sim |
| Média | Fluxo com contorno, ou regra secundária errada | Contagem de extras errada na tela, certa no relatório | Não, com prazo |
| Baixa | Aparência, texto | Rótulo cortado | Não |

Registro em GitHub Issues, com passos, esperado, obtido e o requisito afetado. Nenhum dado real de
paciente em issue, captura de tela ou log anexado. Todo defeito corrigido ganha um teste de regressão
marcado com o requisito.

---

## 11. Critérios de entrada, saída e suspensão

| **Critério** | **Definição** |
|---|---|
| Entrada na homologação | Pipeline verde; rastreabilidade sem lacunas; cobertura mínima atingida; nenhum defeito crítico ou alto aberto |
| Saída da homologação | Critérios de aceite da §9.2 |
| Suspensão | Defeito crítico que invalide os testes seguintes, como perda de dado ou falha de segurança; ambiente de homologação divergente da produção |
| Retomada | Correção com teste de regressão e nova execução do pipeline completo |

---

## 12. Responsabilidades

| **Papel** | **Quem** | **Responsabilidade** |
|---|---|---|
| Desenvolvimento e testes automatizados | Analista de TI | Escrever e manter os testes; pipeline; ensaios técnicos |
| Homologação operacional | Recepcionista | Roteiros da recepção; cronometragem dos RNF-402 a 405 |
| Homologação da enfermagem | Enfermagem | Roteiros de escala |
| Aceite | Coordenação administrativa e direção clínica | Roteiros da administração; assinatura da ata |
| Ensaio sem o TI (QAS-14) | Pessoa indicada pela clínica | Restauração só com a documentação |

---

## 13. Riscos do próprio teste

| **Risco** | **Tratamento** |
|---|---|
| Uma pessoa só desenvolve e testa (R-25) | Rastreabilidade automática, testes por propriedade e mutação compensam a falta de revisor; homologação com usuárias reais |
| Homologação divergente da produção | Mesma imagem de MySQL, mesmo compose, mesma CSP |
| Pressão para usar planilha real "só para testar" | Proibido (§1.3); planilhas sintéticas reproduzem os defeitos reais (§5.3) |
| Teste dependente de horário | Relógio injetável em todo teste de sessão e prazo |
| Teste de interface frágil | Seletores por atributo de dados e por papel acessível, nunca por classe de estilo |
