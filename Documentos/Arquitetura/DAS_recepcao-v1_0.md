**DOCUMENTO DE ARQUITETURA DE SOFTWARE**

Sistema de Apoio à Recepção — SAR

DAS_recepcao · Versão 1.0

*Elaborado com base no SWEBOK 4.0 e na ISO/IEC/IEEE 42010*

Data: 2026-09-28 · Classificação: Confidencial — uso interno

## Controle de revisões

| **Versão** | **Data** | **Autor** | **Descrição** |
|---|---|---|---|
| 1.0 | 2026-09-28 | Equipe de desenvolvimento | Versão inicial aprovada. Drivers arquiteturais, estilo, decisões AD-01 a AD-27, módulos, sequências, modelo de dados, implantação, riscos e avaliação da arquitetura. Baseado na ERS-002 v1.0. |

---

## 1. Introdução

### 1.1 Propósito

Este documento descreve a arquitetura de software do Sistema de Apoio à Recepção (SAR). Serve como
referência técnica durante a construção, estabelecendo decisões arquiteturais, estrutura de módulos,
modelo de dados e visão de implantação, e registrando o motivo de cada escolha.

### 1.2 Escopo

O DAS cobre a arquitetura interna do SAR e a sua convivência com o Sistema de Controle de Estoque
(SCE) no mesmo servidor dedicado. Não cobre a arquitetura interna do SCE, exceto onde ela condiciona
decisões deste sistema — instância de banco, endereçamento e backup.

### 1.3 Referências

- ERS-002 v1.0 — Especificação de Requisitos de Software do SAR
- DAS-001 v1.5 — Documento de Arquitetura de Software do SCE
- Análise de viabilidade e fechamento da Fase 2, §2 — especificação do servidor dedicado
- Modelagem de ameaças e de privacidade (STRIDE e LINDDUN)
- SWEBOK v4.0 — Guide to the Software Engineering Body of Knowledge, IEEE, 2024
- ISO/IEC/IEEE 42010:2022 — Architecture description

### 1.4 Drivers arquiteturais

Nem todo requisito condiciona a arquitetura. Estes condicionam, e cada decisão da §3 responde a pelo
menos um deles.

| **Driver** | **Origem na ERS** | **Implicação arquitetural** |
|---|---|---|
| Nenhuma credencial de banco nas estações | RNF-614, QAS-12 | O banco só é acessado pelo servidor. Estações não podem executar cliente com acesso direto ao MySQL |
| Estações com Windows 10 sem suporte | DEC-51, §4.6.1 | Dados e software fora das estações. Nada instalado além do navegador, exceto onde inevitável |
| Nenhuma cópia de documento na estação | RNF-616, SEG-19, SEG-28 | Documentos exibidos no navegador sem download implícito e sem cache; captura sem arquivo intermediário |
| Câmera só funciona em conexão segura | RF-711, RNF-618 | TLS obrigatório na rede local, com certificado confiável nas estações |
| Tarefas que não dependem de usuário | DEC-54, RNF-615, RNF-628, RF-920 | Agendamento no servidor, em execução permanente — não no processo de interface |
| Pipeline de ingestão de arquivos não confiáveis | SEG-01 a SEG-31 | Processamento isolado, com limites de recurso, fora do processo que atende o usuário |
| Guarda de vinte anos | RN-06, RNF-610, RNF-622 | Formato de arquivamento, integridade verificável e custódia de chaves que sobrevivam a trocas de tecnologia e de pessoa |
| Uma pessoa desenvolve e mantém | R-25, RNF-706 | Mesma base tecnológica do SCE; pilha legível por qualquer desenvolvedor; implantação reproduzível |
| Frequência lançada em poucos cliques | RNF-204, RNF-402, QAS-02 | Atualização parcial de tela, sem recarregar a lista |
| Servidor compartilhado com o SCE | RE-05, RNF-302, RNF-620 | Instâncias de banco separadas; isolamento de processos e de arquivos; o SCE não pode ficar mais lento |
| Extração automática incerta | RNF-702, QAS-08 | Componente isolado e desligável sem alteração de código |

---

## 2. Visão geral da arquitetura

### 2.1 Estilo arquitetural

O SAR adota o mesmo estilo do SCE: **monólito modular**. Um único código-fonte em Python, organizado
em módulos com responsabilidades e interfaces delimitadas, que correspondem aos cinco contextos do
modelo de domínio. A justificativa é a mesma do DAS-001: volume pequeno, poucos usuários simultâneos,
rede local e manutenção por uma pessoa.

A diferença em relação ao SCE está na **superfície de apresentação**. O SCE é uma aplicação desktop
instalada em cada estação, conectada diretamente ao banco. O SAR é uma aplicação web servida pelo
servidor dedicado, e as estações usam apenas o navegador. Os drivers da §1.4 tornam o modelo desktop
inviável aqui: credencial de banco na estação, agendamento dependente de um aplicativo aberto e
software instalado em estações sem suporte são exatamente o que a ERS proíbe ou procura reduzir.

Não se trata de uma tecnologia nova para a casa. O SCE já possui uma superfície web em Flask e
Waitress, o serviço de coleta do MOD-07. No SAR, essa superfície deixa de ser exceção e passa a ser a
principal.

O código roda em **dois processos**, a partir da mesma base: o processo web, que atende as estações,
e o processo worker, que executa agendamentos e o pipeline de ingestão. Não são microsserviços: os dois
compartilham código, serviços de negócio e banco. A separação existe porque as tarefas do worker não
podem depender de uma requisição de usuário, e porque o processamento de arquivos não confiáveis não
deve disputar recursos com a interface.

### 2.2 Camadas da arquitetura

Quatro camadas, com dependência unidirecional, como no SCE:

- **Apresentação:** rotas Flask, modelos Jinja2, fragmentos htmx e o módulo JavaScript de captura da
  webcam. Recebem a requisição, chamam serviços de aplicação e devolvem HTML. Nunca acessam
  repositórios.
- **Aplicação:** serviços que implementam os casos de uso e aplicam as regras de negócio, as
  invariantes e a verificação de autorização por operação e por recurso (RNF-623).
- **Infraestrutura:** repositórios SQLAlchemy, cliente de antimalware, reconstrução de imagem,
  extração de texto, geração de PDF e XLSX, cliente de CEP, cifragem e agendador.
- **Dados:** instância MySQL própria e repositório de documentos cifrado no sistema de arquivos do
  servidor.

A regra de camadas vale para os dois processos: um job do worker chama serviços de aplicação, nunca
repositórios diretamente.

### 2.3 Superfícies de interação

| **Superfície** | **Executada em** | **Capacidades** |
|---|---|---|
| Aplicação web | Navegador das estações, servida pelo servidor dedicado | Todas as funcionalidades, conforme o perfil |
| Agente de captura | Estação da recepção | Somente acionar o scanner e enviar a imagem ao servidor. Nenhum dado de paciente armazenado nem exibido |
| Worker | Servidor dedicado, sem interface | Agendamentos, pipeline de ingestão, verificação da cadeia de auditoria, expurgos |

---

## 3. Decisões arquiteturais

Todas as decisões abaixo estão aprovadas.

| **ID** | **Decisão** | **Escolha** | **Justificativa** |
|---|---|---|---|
| AD-01 | Estilo arquitetural | Monólito modular, com módulos pelos cinco contextos do modelo de domínio | Mesmo estilo do SCE. Volume pequeno, rede local, manutenção por uma pessoa (R-25) |
| AD-02 | Linguagem | Python 3.14, na última correção disponível | Mesma linguagem do SCE, versão estável mais recente. Recebe correções de segurança até outubro de 2030; a 3.12 do SCE, até outubro de 2028. |
| AD-03 | Apresentação | Web, com páginas geradas no servidor: Flask 3 e Jinja2 | Estações só com navegador (RNF-614, DEC-51). Flask já é usado no SCE (AD-14 do DAS-001). Autorização e sessão ficam no servidor |
| AD-04 | Interatividade | htmx 4 para atualização parcial de tela; Alpine.js 3, na versão compatível com política de segurança de conteúdo; sem aplicação de página única | Resposta imediata na frequência (RNF-204) sem segunda linguagem de aplicação e sem build de JavaScript. O htmx 4 deixou de guardar o histórico de páginas no armazenamento local do navegador, o que atende diretamente o RNF-616 |
| AD-05 | Estilo visual | Tailwind CSS, gerado pelo executável standalone; guia curto de componentes | Aparência moderna e responsiva sem Node. Conjunto fixo de componentes garante consistência entre telas |
| AD-06 | Ativos de interface | Servidos pelo próprio servidor, com versões fixadas; nenhum CDN | Interface independente de internet; nenhum acesso revelado a terceiros; compatível com RNF-611 |
| AD-07 | Servidor de aplicação | Waitress | Mesmo servidor WSGI do SCE. Puro Python, adequado ao volume |
| AD-08 | TLS na rede local | Proxy reverso Caddy com autoridade certificadora interna; certificado emitido para o IP fixo do servidor; certificado raiz instalado uma vez em cada estação | Condição para a câmera funcionar (RF-711) e para cifrar o tráfego (RNF-618). A rede não tem DNS interno (AD-21 do DAS-001), por isso o certificado é para o IP |
| AD-09 | Banco de dados | MySQL 9.7 LTS, em instância própria, sem porta publicada na rede | Série LTS mais recente, lançada em abril de 2026, com cinco anos de suporte principal e três de estendido. A 8.0 está sem suporte desde 30/04/2026. Instância própria atende RNF-301 e RNF-614 |
| AD-10 | ORM e evolução do schema | SQLAlchemy 2.0 e Alembic; models.py como fonte da verdade; nenhuma alteração manual em produção | Mesmo ORM do SCE. Adota desde o início a política que o SCE só alcançou com o AD-20, após divergência entre banco e código |
| AD-11 | Processos | Dois processos da mesma base: web e worker | O agendamento no processo de interface é a origem do R-01 do SCE. O pipeline de ingestão não deve disputar recursos com a interface (SEG-30) |
| AD-12 | Agendamento | APScheduler 3.11 no worker; jobs idempotentes; toda execução registrada | A abertura automática das sessões (DEC-54) precisa rodar mesmo com todas as estações desligadas. A série 4.0 continua em pré-lançamento, com aviso expresso contra uso em produção |
| AD-13 | Armazenamento de documentos | Sistema de arquivos do servidor, fora da raiz web, com nomes aleatórios e cifragem pela aplicação | Mantém SEG-13. O SCE guarda anexos como BLOB (AD-22 do DAS-001) para unificar o backup; num acervo de vinte anos, os riscos R-14 e R-15 do próprio SCE pesam mais. O custo — backup de duas fontes — é tratado no AD-25 |
| AD-14 | Integridade | Hash SHA-256 de cada documento; trilha de auditoria encadeada por hash; último elo exportado periodicamente para fora do servidor | Torna alterações diretas detectáveis (RNF-615, R-27). A prova de cada documento acompanha o documento por vinte anos, independente do expurgo da trilha (RNF-628) |
| AD-15 | Pipeline de ingestão | No worker: validação por assinatura binária, varredura com ClamAV, reconstrução por rasterização e geração de PDF/A **sem camada de texto** | Atende SEG-01 a SEG-31. Ferramentas que geram PDF/A pesquisável embutem o texto lido no arquivo, o que violaria SEG-31. Conformidade PDF/A verificada com validador durante a construção |
| AD-16 | Extração de dados | Tesseract com modelo de português, local, isolado e desligável por configuração | RNF-627 impede serviço externo. RNF-702 exige que o sistema funcione sem ele |
| AD-17 | Captura do scanner | Agente local em Python na estação da recepção, empacotado como o SCE (AD-11 do DAS-001), acionando o scanner por WIA e enviando a imagem por HTTPS, sem gravar arquivo | Única opção que atende SEG-28 sem depender de recurso do scanner. Primeira tarefa da construção: verificação com o equipamento real, incluindo o alimentador automático |
| AD-18 | Captura da foto | API de câmera do navegador, em módulo JavaScript próprio | Nenhum software instalado. Exige TLS (AD-08) |
| AD-19 | Autenticação | Sessão no servidor; cookie Secure, HttpOnly e SameSite Strict; senhas com bcrypt; bloqueio progressivo por tentativas | Mesmo algoritmo do SCE (AD-09 do DAS-001). Atende RNF-601, RNF-602 e RNF-613 |
| AD-20 | Autorização | Verificação no servidor em toda operação, por perfil e por recurso; matriz de permissões única no código | RNF-623: identificador aleatório não substitui controle de acesso. Uma matriz única evita regra de acesso espalhada pelas telas |
| AD-21 | Emissão de documentos | Modelos HTML em Jinja2, convertidos em PDF por WeasyPrint; cabeçalho e textos em configuração | Alterar texto ou cabeçalho sem mudar código (RNF-703). O SCE usa reportlab, adequado a layout fixo; aqui os textos mudam com a clínica |
| AD-22 | Planilhas | XlsxWriter para gerar os relatórios XLSX. O extrator da carga inicial mantém o OpenPyXL | O sistema só escreve planilhas, nunca lê (RF-912). O XlsxWriter é dedicado à escrita, maduro e com manutenção ativa; o OpenPyXL não tem versão nova desde 2024. O extrator da migração já foi validado com OpenPyXL e roda uma única vez, sobre arquivos da própria clínica — trocá-lo exigiria refazer a validação sem ganho |
| AD-23 | Consulta de CEP | Cliente com provedor substituível; ViaCEP como principal e fonte alternativa; tempo limite curto; envia somente o CEP | RNF-507, RNF-612, RNF-704. Consulta individual, nunca em massa |
| AD-24 | Sistema operacional e implantação | Ubuntu Server 26.04 LTS e Docker Engine com Compose. Contêineres: proxy, web, worker, MySQL do SAR, MySQL do SCE e ClamAV | Suporte até abril de 2031. ClamAV, Tesseract e WeasyPrint são nativos no Linux. Contêineres isolam as duas instâncias de banco e tornam a instalação reproduzível (RNF-806). Sem custo de licença |
| AD-25 | Backup | restic, com snapshots cifrados do dump consistente do banco e do repositório de documentos, no disco local e no pen drive; senha em custódia dupla | Uma ferramenta cobre as duas fontes de dados do AD-13, cifra por padrão (RNF-617) e restaura por data. A senha com TI e administração atende RNF-622 |
| AD-26 | Endereçamento | IP fixo reservado. O servidor dedicado assume o IP atual do servidor do SCE, e o serviço de coleta do SCE mantém a mesma porta | O IP e a porta do serviço de coleta estão gravados nos QR Codes de patrimônio já impressos (AD-15, AD-21 e R-08 do DAS-001). Trocar qualquer um dos dois inutilizaria todas as etiquetas |
| AD-27 | Servidor provisório | Notebook reservado, com Ubuntu Server LTS e a mesma pilha do AD-24, até a chegada do servidor dedicado. IP fixo próprio, diferente do IP do SCE. Backup local em disco USB dedicado. O SCE permanece onde está e migra uma única vez, direto para o servidor definitivo | A compra do servidor dedicado pode demorar mais que o desenvolvimento. Uma máquina provisória, também dedicada, mantém a premissa da ERS e a arquitetura intacta. A migração para o definitivo é feita restaurando o backup, o que serve como o teste de restauração exigido antes do go-live (RNF-505, QAS-14) |

### 3.1 Decisões que divergem do SCE

Para quem mantém os dois sistemas, as divergências precisam ser poucas e explicadas:

| **Tema** | **SCE** | **SAR** | **Motivo** |
|---|---|---|---|
| Interface | Desktop CustomTkinter | Web Flask | Credencial de banco, estações sem suporte, TLS para a câmera |
| Acesso ao banco | Estações conectam direto na porta 3306 | Só o servidor acessa | RNF-614 |
| Agendamento | Dentro do aplicativo desktop | Worker permanente no servidor | Tarefas que não podem depender de aplicativo aberto |
| Documentos | BLOB no banco | Sistema de arquivos cifrado | Acervo de vinte anos, pipeline de segurança, módulo segregado |
| PDF | reportlab | WeasyPrint | Textos configuráveis |
| MySQL | 8.x | 9.7 LTS | Suporte vigente por mais tempo |
| Python | 3.12 | 3.14 | Suporte vigente por mais tempo; cada sistema tem o próprio interpretador, no seu contêiner ou no seu instalador |
| Planilhas | OpenPyXL | XlsxWriter | Só escrita, com manutenção ativa |

**Recomendação ao SCE.** A série 8.0 do MySQL está sem suporte desde 30/04/2026. A migração do banco do
SCE para o servidor dedicado é a oportunidade natural de levá-lo à 9.7 LTS. Como a mudança de servidor
já exige copiar os dados, o caminho mais simples é exportar o banco atual e importá-lo na instância
nova, testando a aplicação do SCE contra a 9.7 antes da troca. O mesmo vale para o Python: a 3.12 do
SCE sai de suporte em outubro de 2028, e a atualização deve entrar no planejamento do SCE antes disso.

### 3.2 Critério de versões

Cada tecnologia é adotada na versão estável mais recente — nunca alfa, beta ou candidata — e, onde o
projeto mantém linhas de suporte longo, na linha LTS mais recente. As versões exatas são fixadas no
arquivo de dependências e nas imagens de contêiner no momento da aprovação. Mudanças posteriores geram
nova versão deste documento.

---

## 4. Módulos do sistema

### 4.1 Visão geral dos módulos

Os seis primeiros módulos correspondem aos contextos do modelo de domínio; os demais são de
infraestrutura e de operação.

| **ID** | **Módulo** | **Responsabilidade** | **Componentes** | **Depende de** |
|---|---|---|---|---|
| MOD-01 | Acesso e auditoria | Login, sessão, perfis, autorização por operação e por recurso, trilha de auditoria encadeada, fila de autorização da administração, pedidos de titular | AuthService, SessionManager, PermissionGuard, AuditService, AutorizacaoService, TitularService | MOD-08 |
| MOD-02 | Cadastro | Paciente, contatos e telefones, períodos de tratamento e cobertura, eventos, rascunho de cadastro, alerta de tríade | PacienteService, EventoService, RascunhoService, CepClient | MOD-01, MOD-06, MOD-08 |
| MOD-03 | Operação | Escalas fixas, alocação com vigência, trocas, sessões de turno, presença, compensação, balanço e fechamento do mês | EscalaService, SessaoTurnoService, FrequenciaService, CompensacaoEngine | MOD-01, MOD-02, MOD-08 |
| MOD-04 | Documentos | Pipeline de ingestão, repositório cifrado, versões, retenção, prova de integridade, revinculação, cópia ao titular | IngestaoService, DocumentoService, ExtratorCampos, CofreDocumentos, IntegridadeService | MOD-01, MOD-06, MOD-08 |
| MOD-05 | Emissão e relatórios | Sete documentos parametrizados e crachá, relatórios em tela, exportação PDF e XLSX auditada | EmissaoService, RelatorioService, PdfBuilder, XlsxBuilder | MOD-01, MOD-02, MOD-03, MOD-06 |
| MOD-06 | Configuração | Municípios, convênios, estabelecimentos, dados institucionais, logotipo, faixas etárias, parâmetros | ConfigService | MOD-01, MOD-08 |
| MOD-07 | Pendências | Consulta das pendências por perfil (RF-1010). Não grava nada: pendência é consulta, não entidade | PendenciaService | MOD-01 a MOD-04 |
| MOD-08 | Dados | Único ponto de acesso ao MySQL: engine, sessões, repositórios, migrações | DatabaseEngine, repositórios, migrações Alembic | MySQL |
| MOD-09 | Agendamento | Jobs do worker: abertura de sessões, lembrete de confirmação, verificação da cadeia, expurgos, descarte de rascunhos | Scheduler, jobs | MOD-01 a MOD-04 |
| MOD-10 | Carga inicial | Migração única das planilhas, relatório de exceções, apoio à conferência amostral | ExtratorP1, CargaService | MOD-02, MOD-03, MOD-08 |

### 4.2 Regras de dependência

- MOD-08 é o único módulo que acessa o banco. Nenhum outro escreve SQL.
- MOD-04 é o único módulo que acessa o repositório de documentos e as chaves de cifragem de
  documento. Os demais recebem apenas identificadores.
- MOD-04 conhece o paciente só pelo identificador (RNF-701). Não importa entidades de MOD-02.
- MOD-01 avalia toda autorização. Os demais módulos consultam o resultado e não implementam regra de
  acesso própria — mesma regra do SCE.
- Toda escrita registra auditoria por MOD-01, **na mesma transação**. Se a auditoria falhar, a
  operação falha.
- MOD-07 só lê, por meio dos serviços dos outros módulos.
- Jobs de MOD-09 chamam serviços, nunca repositórios.
- O ExtratorCampos pode ser desligado por configuração; nenhum outro componente depende dele
  (RNF-702).
- O único código que acessa a internet é o CepClient.
- As rotas web são apresentação: chamam serviços e devolvem HTML. Nenhuma regra de negócio vive em
  rota ou em modelo Jinja.

### 4.3 Componentes com decisão relevante

| **Componente** | **Responsabilidade** |
|---|---|
| PermissionGuard | Verifica, em toda requisição, se aquele usuário pode executar aquela operação sobre aquele recurso. Matriz de permissões única, em código (AD-20) |
| AuditService | Grava o registro com hash do anterior e hash próprio (AD-14). Serializa a escrita da trilha para que dois registros não disputem o mesmo elo |
| AutorizacaoService | Fila de solicitações da DEC-42. A operação pedida só executa quando a administração aprova, na própria sessão |
| SessaoTurnoService | Abre as sessões do dia a partir do calendário e das escalas fixas. Idempotente: a unicidade de data e escala no banco impede sessão duplicada |
| CompensacaoEngine | Deriva a classificação das presenças e faz o pareamento cronológico entre falta e extra dentro do mês (RF-918). Função pura sobre os dados do mês, testável isoladamente (RNF-705) |
| CofreDocumentos | Cifra e decifra documentos com chave própria por documento, protegida pela chave mestra (§6.3). Nenhum outro componente vê chave ou arquivo em claro no disco |
| IngestaoService | Conduz o pipeline da §5.3 no worker, com limites de tamanho, dimensão, páginas e tempo (SEG-30) |
| ExtratorCampos | Lê os campos candidatos da imagem com Tesseract. O texto integral nunca é persistido (SEG-31); só os campos confirmados vão ao cadastro, validados como digitação (SEG-26) |
| PdfBuilder | WeasyPrint com busca de recursos restrita a arquivos locais do próprio sistema |

### 4.4 Estrutura de pacotes Python

- `sar/modulo_01_acesso/`
- `sar/modulo_02_cadastro/`
- `sar/modulo_03_operacao/`
- `sar/modulo_04_documentos/`
- `sar/modulo_05_emissao/`
- `sar/modulo_06_config/`
- `sar/modulo_07_pendencias/`
- `sar/modulo_08_dados/` — modelos, repositórios e `migrations/`
- `sar/modulo_09_agendamento/`
- `sar/modulo_10_carga/`
- `sar/web/` — rotas, modelos Jinja, fragmentos htmx, estáticos compilados
- `sar/wsgi.py` — ponto de entrada do processo web
- `sar/worker.py` — ponto de entrada do worker
- `agente_captura/` — projeto separado, empacotado para Windows

Mesma convenção de nomes do SCE, para que a navegação entre os dois códigos seja familiar.

### 4.5 Agente de captura

Programa pequeno, instalado apenas na estação da recepção. Recebe do navegador um pedido de captura
associado a uma ingestão já aberta no servidor, aciona o scanner, recebe a imagem em memória e a envia
por HTTPS ao servidor, autenticado por um token de uso único emitido para aquela ingestão. Não grava
arquivo, não guarda credencial e não exibe dado de paciente.

---

## 5. Diagramas de sequência

### 5.1 Abertura automática e confirmação da sessão de turno

No início de cada dia, o job de abertura cria as sessões das escalas daquele dia da semana, com todos
os pacientes alocados na data marcados como presentes. A criação usa a unicidade de data e escala: se o
worker reiniciar no meio do job, a segunda execução não duplica nada. Ao fim do horário de cada turno,
outro job marca como pendente de urgência toda sessão não confirmada. Na confirmação, a recepcionista
salva e o serviço grava a confirmação e o registro de auditoria na mesma transação. O mês só pode ser
fechado para relatório quando não restar sessão sem confirmação (RF-913).

### 5.2 Lançamento de ausência

A recepcionista marca a ausência na linha do paciente. O htmx envia a requisição com o token de
proteção contra requisição forjada no cabeçalho; o servidor verifica permissão, grava a presença e a
auditoria, recalcula a classificação do mês daquele paciente e devolve só a linha atualizada. Nada é
guardado no navegador.

### 5.3 Ingestão de documento

1. A recepcionista escolhe o paciente e o tipo de documento. O servidor abre uma ingestão e emite um
   token de captura.
2. A imagem chega pelo agente ou pela webcam e vai para a quarentena, com hash registrado.
3. O worker valida a assinatura binária e os limites, varre com ClamAV e, se aprovado, rasteriza e
   gera o PDF/A sem camada de texto. Cada etapa confere o hash da anterior (SEG-27).
4. Se a extração estiver ligada, os campos candidatos são lidos e mantidos só em memória para a tela de
   conferência.
5. A conferência exibe o documento reconstruído e, em destaque, a identificação do paciente de destino
   (RF-712). A recepcionista confirma.
6. O CofreDocumentos cifra e grava o arquivo; o banco recebe os metadados e o hash; a trilha recebe o
   registro com o hash do documento; a quarentena é apagada.

Rejeição em qualquer etapa encerra a ingestão com motivo registrado, sem armazenamento definitivo.

### 5.4 Consulta de documento

O PermissionGuard verifica perfil, família do documento e paciente. A leitura é auditada antes da
entrega. O CofreDocumentos decifra em memória e o documento é servido como imagem dentro da aplicação,
com cabeçalhos que impedem cache (SEG-19). Download só por ação explícita, também auditada.

### 5.5 Autorização da administração

A recepcionista solicita, por exemplo, a correção de uma presença já confirmada, com motivo. A
solicitação entra na fila e aparece nas pendências da administração. A administração abre a
solicitação na própria sessão e aprova ou recusa. Na aprovação, a operação executa, e a auditoria grava
solicitante e autorizador em campos distintos (RF-1008, QAS-10).

### 5.6 Verificação da cadeia de auditoria

Um job recalcula a cadeia a partir da última âncora. Se tudo confere, registra a nova âncora e a
exporta para o destino fora do servidor. Se encontrar divergência, cria o aviso: o TI vê o diagnóstico
com o primeiro registro divergente; a administração vê o aviso simples, sem detalhe técnico e sem dado
de paciente, e só ela o encerra, registrando a explicação recebida (RF-1011).

### 5.7 Cadastro com consulta de CEP

Ao informar o CEP, o htmx pede ao servidor o preenchimento do endereço. O CepClient consulta o
provedor principal com tempo limite curto e, em falha, o alternativo. Sem resposta, o cadastro segue
com o CEP marcado como não verificado, que vira pendência. Ao gravar, o serviço verifica a tríade e,
havendo coincidência, exibe o alerta sem bloquear.

### 5.8 Emissão de documento parametrizado

O EmissaoService monta os dados a partir do cadastro selecionado — nunca de arquivo anterior
(RNF-903) —, renderiza o modelo Jinja com os dados institucionais da configuração e o PdfBuilder gera o
PDF. A emissão é registrada. Quando o documento exige assinatura e guarda, como a declaração de troca
de turno, a pendência de termo é criada para a recepção (RF-809).

---

## 6. Modelo de dados

### 6.1 Banco de dados

MySQL na linha LTS, instância exclusiva do SAR, InnoDB em todas as tabelas, utf8mb4. O usuário da
aplicação tem permissões apenas de leitura e escrita nas tabelas do SAR; as migrações usam um usuário
separado, usado só na implantação. Datas e horas de eventos são gravadas em UTC; datas de calendário,
como a data da sessão, em data local da clínica.

### 6.2 Tabelas por módulo dono

| **Tabela** | **Módulo** | **Principais colunas e observações** |
|---|---|---|
| usuario | MOD-01 | id, nome, login, senha_hash, perfil (recepcao, administracao, visualizador, ti, enfermagem), ativo, termo_ciencia_em, tentativas_falhas, bloqueado_ate |
| sessao_usuario | MOD-01 | id aleatório, usuario_id, criada_em, ultimo_acesso, expira_em |
| auditoria | MOD-01 | id, instante, usuario_id, autorizador_id, operacao, entidade, entidade_id, antes, depois, motivo, hash_anterior, hash_registro |
| auditoria_ancora | MOD-01 | id, ate_registro_id, hash, exportada_em |
| aviso_integridade | MOD-01 | id, detectado_em, registro_divergente_id, encerrado_por, encerrado_em, explicacao |
| solicitacao_autorizacao | MOD-01 | id, tipo, entidade, entidade_id, motivo, solicitante_id, solicitada_em, decisor_id, decidida_em, decisao |
| requisicao_titular | MOD-01 | id, paciente_id, tipo, recebida_em, prazo, situacao, atendida_em, atendente_id |
| paciente | MOD-02 | id, prontuario, nome, data_nascimento, sexo, nome_mae, cpf, cns, rg, rg_orgao, naturalidade_municipio, endereço, cep, cep_verificado, municipio. **Sem idade e sem situação** |
| contato, telefone | MOD-02 | contato: id, paciente_id, nome, parentesco. telefone: id, dono, número, tipo |
| periodo_tratamento | MOD-02 | id, paciente_id, inicio, fim, cobertura (sus, convenio), convenio_id, carteirinha, estabelecimento_id, medico_referencia |
| evento | MOD-02 | id, paciente_id, periodo_id, tipo, data, observacao |
| rascunho_cadastro | MOD-02 | id, usuario_id, conteúdo cifrado, criado_em, expira_em |
| escala | MOD-03 | Tabela fixa, carregada por migração: código (1-seg a 3-ter), turno, dias da semana, horários |
| alocacao | MOD-03 | id, paciente_id, escala_id, vigencia_inicio, vigencia_fim |
| troca_turno | MOD-03 | id, paciente_id, data_origem, escala_origem, data_destino, escala_destino |
| sessao_turno | MOD-03 | id, data, escala_id, aberta_em, confirmada_em, confirmada_por. **Único por data e escala** |
| presenca | MOD-03 | id, sessao_id, paciente_id, presente, incluida_pela_recepcao |
| compensacao | MOD-03 | id, falta_id, reposicao_id, automatica, revertida_em |
| mes_frequencia | MOD-03 | ano_mes, fechado_em, alterado_apos_fechamento |
| tipo_documento | MOD-04 | Tabela fixa (DEC-41): código, família (prontuario, cadastro), anos de retenção, integra checklist, evento exigente |
| documento | MOD-04 | id aleatório, paciente_id, tipo, versao, substitui_id, arquivo (nome aleatório), chave_documento_cifrada, hash_sha256, prova_encadeamento, paginas, origem (scanner, webcam), capturado_em, capturado_por, reter_ate |
| ingestao | MOD-04 | id, paciente_id, tipo, estado, motivo_rejeicao, hash_entrada, criada_em, usuario_id. **Sem texto extraído** |
| emissao_documento | MOD-05 | id, paciente_id, modelo, emitido_em, emitido_por |
| municipio, convenio, estabelecimento | MOD-06 | Municípios com código IBGE de 7 dígitos |
| dados_institucionais, faixa_etaria, parametro | MOD-06 | Configuração editável pelo perfil TI |
| job_execucao | MOD-09 | id, job, inicio, fim, sucesso, detalhe |

### 6.3 Decisões de design do banco

- **Nada derivado é armazenado.** Idade, situação do paciente, classificação da presença, sessões
  previstas, pendências e ocupação são calculadas. A tabela acima marca as ausências mais tentadoras.
- **Idempotência pelo banco.** A unicidade de data e escala em sessao_turno é o que torna seguro o job
  de abertura.
- **Cifragem em envelope.** Cada documento tem chave própria, gravada cifrada pela chave mestra. A
  chave mestra fica fora do banco e fora do repositório, com cópias em custódia (RNF-622). Trocar a
  chave mestra exige recifrar só as chaves dos documentos, não os arquivos.
- **Hash sobre o conteúdo em claro.** A prova de integridade independe da cifragem, e continua válida
  se a chave mestra for trocada.
- **Identificadores aleatórios** para documento e sessão de usuário. Não substituem a verificação de
  permissão (RNF-623).
- **Nenhuma exclusão física de paciente, documento ou usuário.** Inativação e revinculação são
  operações auditadas.
- **Auditoria com antes e depois** para escrita. A trilha é, ela própria, dado sensível: acesso
  restrito e auditado (RNF-625).

### 6.4 Política de evolução do schema

Toda alteração de schema é uma migração Alembic versionada no repositório, com models.py como fonte da
verdade. Nenhuma alteração manual em produção — a mesma política do AD-20 do SCE, adotada desde o
início.

---

## 7. Visão de implantação

### 7.1 Topologia

- **Servidor dedicado:** Ubuntu Server LTS com Docker. Hospeda o SAR e o banco do SCE, em local fechado,
  sem uso diário, ligado ao nobreak.
- **Estação da recepção:** navegador e agente de captura; scanner e webcam.
- **Demais estações, inclusive o terminal da enfermagem:** apenas navegador.
- **Estações com o SCE:** aplicação desktop do SCE, conectando ao banco do SCE no servidor novo.
- **Impressora:** emissão de documentos e crachá.
- **Pen drives de backup:** dois, em rodízio, sob custódia registrada.

### 7.2 Contêineres

| **Contêiner** | **Rede** | **Porta publicada** | **Observação** |
|---|---|---|---|
| proxy (Caddy) | borda | 443 | Único ponto de entrada do SAR. Guarda a certificadora interna |
| web | borda, interna | — | Waitress com o processo web |
| worker | interna | — | Agendamento e ingestão |
| mysql-sar | interna | **nenhuma** | Inalcançável pela rede (RNF-614) |
| clamav | interna | — | Atualização automática de assinaturas |
| mysql-sce | sce | 3306, só para a rede local | Mesma porta de hoje |
| coleta-sce | sce | A mesma de hoje | Serviço de coleta do SCE, se for migrado para contêiner |

Volumes persistentes: banco do SAR, banco do SCE, repositório de documentos, quarentena, dados do
Caddy e segredos. A quarentena fica fora do backup (SEG-29); os dados do Caddy entram, porque contêm a
certificadora.

### 7.3 Requisitos de infraestrutura

- IP fixo reservado no gateway: o mesmo IP do servidor atual do SCE (AD-26).
- Firewall do host liberando para a rede local apenas a 443 do SAR e as portas do SCE.
- **Atenção:** o Docker, por padrão, publica portas por regras próprias que passam por fora do
  firewall configurado no Ubuntu. As regras de acesso precisam ser aplicadas na cadeia que o Docker
  respeita, e a publicação de porta deve ser feita apenas no endereço da rede local.
- Saída para a internet restrita à consulta de CEP, às assinaturas do ClamAV e às atualizações do
  sistema operacional e das imagens (RNF-611).
- Sincronização de relógio ativa. Abertura de sessão, prazos de pendência e cadeia de auditoria
  dependem da hora correta.
- Nobreak com desligamento ordenado configurado e testado (RNF-508).
- Certificado raiz da certificadora interna instalado em todas as estações, inclusive a da
  enfermagem.

### 7.4 Backup e restauração

1. Diariamente, dump consistente do banco do SAR e do banco do SCE.
2. Snapshot restic cifrado dos dumps, do repositório de documentos, dos dados do Caddy e da
   configuração, no HD local separado.
3. Semanalmente, cópia para o pen drive da vez, que depois é desconectado.
4. Verificação periódica da integridade do repositório de backup.
5. Teste de restauração completa, em máquina limpa e por outra pessoa, antes do go-live e a cada
   semestre, incluindo a recuperação da chave mestra e da senha do restic (QAS-14).

A senha do restic e a chave mestra ficam em custódia dupla, com o TI e a administração. O backup do
servidor passa a cobrir também o SCE, e a rotina própria de backup do SCE pode ser mantida em paralelo
até a confiança na nova estar estabelecida.

### 7.5 Operação

- Reinício automático de todos os contêineres, com verificação de saúde.
- Todo job registra execução em job_execucao; job que não roda no horário vira pendência do TI. É a
  resposta à falha silenciosa de tarefa agendada que o SCE já viveu (§7.3 do DAS-001).
- Logs técnicos sem dado pessoal (RNF-624).
- Alerta de ocupação de disco (RNF-621).

### 7.6 Servidor provisório (AD-27)

Até a chegada do servidor dedicado, o SAR roda num notebook reservado, com a mesma pilha. Cuidados:

1. Verificar a saúde do disco antes da instalação e trocá-lo se houver setores realocados ou erros.
2. Conexão por cabo de rede.
3. A bateria funciona como nobreak; o desligamento ordenado em bateria crítica é configurado como no
   RNF-508.
4. Suspensão ao fechar a tampa desativada.
5. Backup local diário em disco USB dedicado, que garante a perda máxima de 24 horas do QAS-04.
6. Local fora do balcão, ventilado, sem uso diário por ninguém.
7. IP fixo diferente do IP do servidor do SCE.

Na chegada do servidor dedicado: instalar a pilha, restaurar o backup do restic — incluindo os dados
do Caddy, para que o certificado raiz das estações continue válido —, conferir a integridade dos
documentos e da cadeia de auditoria, e só então migrar o SCE (§7.7). O endereço do SAR muda uma vez,
nessa troca.

### 7.7 Migração do SCE para o servidor dedicado

1. Medir o desempenho atual do SCE, para servir de linha de base (RNF-302).
2. Subir o banco do SCE em contêiner, na versão LTS, e importar o dump do banco atual.
3. Testar a aplicação desktop do SCE contra o banco novo **antes** da troca — ver R-35.
4. Na janela de troca, transferir o IP do servidor atual para o dedicado e subir o serviço de coleta na
   mesma porta.
5. Conferir uma etiqueta de patrimônio impressa lendo o QR Code com um celular.
6. Manter o servidor antigo desligado, mas intacto, até a confirmação.

---

## 8. Riscos arquiteturais e mitigações

Numeração contínua com o registro de riscos do projeto.

| **ID** | **Risco** | **Impacto** | **Mitigação** |
|---|---|---|---|
| R-33 | htmx 4 tem pouco tempo de mercado | Defeito de biblioteca atrasa a homologação | Uso restrito a atributos básicos; reserva na série 2 com histórico local desligado |
| R-34 | Agente de captura não conversa bem com o scanner ou com o alimentador | Captura manual por arquivo, violando SEG-28 | Verificação com o equipamento real como primeira tarefa da construção (AD-17) |
| R-35 | Aplicação do SCE não conecta ao MySQL LTS novo | Estoque parado na migração | A série 9 removeu o método de autenticação antigo do MySQL. Testar o driver do SCE antes da troca e ajustar a configuração de conexão, se necessário |
| R-36 | Portas publicadas pelo Docker contornam o firewall do host | Banco do SCE ou outra porta exposta além do previsto | Regras na cadeia respeitada pelo Docker; publicação só no endereço da rede local; varredura de portas a partir de uma estação na homologação |
| R-37 | Perda dos dados do Caddy | Certificado raiz novo, reinstalação em todas as estações | Dados do Caddy no backup |
| R-38 | Job agendado falha em silêncio | Sessão não aberta, cadeia não verificada | Registro de execução, verificação de saúde e pendência para o TI quando um job não roda no horário |
| R-39 | Relógio do servidor errado | Sessões abertas no dia errado, prazos incorretos | Sincronização de horário e alerta de divergência |
| R-40 | Assinaturas do ClamAV desatualizadas | Varredura obsoleta | Saída liberada para os espelhos de assinatura; alerta de defasagem (SEG-21) |
| R-41 | Worker e web disputam o repositório de documentos | Arquivo parcial ou órfão | Escrita definitiva só pelo CofreDocumentos, com gravação em arquivo temporário e renomeação atômica |
| R-42 | Notebook provisório com disco único, em operação contínua | Falha de disco ou superaquecimento para o sistema | Verificação de saúde do disco antes e durante o uso, backup diário em disco USB, local ventilado, migração ao servidor dedicado assim que ele chegar |

Riscos do projeto que continuam valendo e têm tratamento arquitetural neste documento: R-12 servidor
compartilhado (§7.2), R-25 dependência de uma pessoa (§7.4 e RNF-706), R-27 acesso administrativo
(AD-14), R-29 perda da chave (§6.3 e §7.4) e R-31/R-32 servidor dedicado (AD-24).

---

## Apêndice A — Avaliação da arquitetura

Avaliação no estilo ATAM, enxuta: cada cenário de atributo de qualidade da ERS confrontado com as
decisões que o atendem, registrando pontos de sensibilidade — onde uma escolha pequena muda o
resultado — e conflitos entre atributos.

### A.1 Cenários

| **Cenário** | **Decisões que atendem** | **Resultado** | **Ponto de sensibilidade** |
|---|---|---|---|
| QAS-01 Busca em menos de 2 s | AD-03, AD-09; 1.200 registros | Atendido | Busca sem distinção de acento depende da collation do banco |
| QAS-02 Frequência em até 4 interações | AD-04, §5.2 | Atendido | — |
| QAS-03 CEP indisponível | AD-23, §5.7 | Atendido | Tempo limite curto do CepClient |
| QAS-04 Falha de hardware, perda máxima de 24 h | AD-25, §7.4, espelhamento de discos | Atendido | Backup local em disco separado do espelhamento |
| QAS-15 Perda total, perda máxima de 7 dias | AD-25, §7.4 | Atendido | Rodízio semanal do pen drive cumprido |
| QAS-05 Arquivo malicioso recusado | AD-15, §5.3 | Atendido | A reconstrução é a defesa principal; o ClamAV tem limites de detecção (SEG-09) |
| QAS-06 Leitura registrada e inalterável pela aplicação | AD-14, §5.4 | Atendido **com item de projeto** | Permissões do usuário do banco na tabela de auditoria — ver A.2 |
| QAS-07 Desempenho em 20 anos | AD-09, AD-13 | Atendido | Backup incremental do restic evita crescimento proporcional do tempo |
| QAS-08 Extração desligável | AD-16, §4.2 | Atendido | — |
| QAS-09 Estação desatendida | AD-19 | Atendido | Prazo de inatividade: segurança contra usabilidade no balcão |
| QAS-10 Duas identidades na autorização | AD-20, §5.5 | Atendido | — |
| QAS-11 Ransomware numa estação | AD-24, AD-25, §7.2 | Atendido | Repositório nunca exposto como pasta de rede |
| QAS-12 Conexão ao banco recusada e registrada | AD-09, §7.2 | Atendido **com item de projeto** | Registro da tentativa exige log no firewall — ver A.2 |
| QAS-13 Alteração da trilha detectada | AD-14, §5.6 | Atendido **com item de projeto** | Destino da âncora fora do servidor — ver A.2 |
| QAS-14 Restauração por outra pessoa | AD-25, §7.4, RNF-706 | Atendido | Depende do manual de operação estar atualizado |

### A.2 Itens de projeto revelados pela avaliação

1. **Auditoria inalterável pelo banco, não só pela aplicação (QAS-06).** O usuário do banco usado pela
   aplicação recebe apenas inserção e leitura na tabela de auditoria — nenhuma alteração nem exclusão.
   O expurgo dos cinco anos (DEC-45) usa um usuário separado, restrito a essa operação.
2. **Registro de tentativas de conexão (QAS-12).** O banco do SAR não tem porta publicada, então uma
   tentativa não encontra nada escutando. Para que ela fique registrada, o firewall do host registra
   conexões recusadas nas portas não publicadas.
3. **Destino da âncora da cadeia (QAS-13).** A âncora é só um hash, sem dado pessoal. Ela é gravada no
   backup do dia e exibida à administração na tela de pendências uma vez por mês, para anotação fora do
   sistema. Assim, alterar a trilha e a âncora juntas exige também alterar o que a administração
   anotou.

### A.3 Conflito resolvido: perda máxima de dados

A avaliação encontrou conflito entre o QAS-04, que exigia perda máxima de 24 horas restaurando da cópia
fora da máquina, e o RNF-504, que prevê essa cópia semanalmente. A clínica decidiu manter a rotina
semanal e reescrever o requisito (DEC-56): falha de hardware com discos preservados perde no máximo 24
horas (QAS-04); perda total do servidor perde no máximo sete dias (QAS-15). Os dias perdidos na perda
total são reconstituídos a partir das fichas de frequência em papel, que continuam sendo o comprovante
oficial.

### A.4 Trocas conscientes

| **Troca** | **Escolha feita** |
|---|---|
| Segurança × usabilidade no balcão | Bloqueio por inatividade, com prazo configurável ajustado na homologação |
| Confidencialidade × recuperabilidade | Cifragem de tudo, com chaves em custódia dupla e restauração testada com recuperação de chave |
| Isolamento × simplicidade | Dois processos e contêineres separados, ao custo de mais peças na implantação |
| Autonomia das estações × dependência do servidor | Estações sem dados; se o servidor cair, a recepção segue o procedimento manual (RNF-506) |
