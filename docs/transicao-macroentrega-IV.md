re# Transição — Sistema de Apoio à Recepção (SAR)

**Data:** 2026-10-06
**Finalidade:** ponto de partida da Macroentrega IV (Codificação e verificação) em um chat novo ou no
Claude Code. Resume o estado do projeto, o que foi decidido no design e a ordem de construção. Os
documentos completos continuam sendo a referência.

---

## 1. O projeto em uma página

Sistema de apoio à recepção do Centro de Uro-Nefrologia de Jataí-GO, clínica de hemodiálise. Substitui o
cadastro em planilhas Excel. **Não é prontuário eletrônico.** Implantação real, em produção, conduzida
pelo SWEBOK v4.0 e pela legislação brasileira, com atenção central à LGPD: todo o cadastro é dado
pessoal sensível de saúde.

- Cerca de 146 pacientes. Três turnos por dia — primeiro (06:00–10:00), segundo (11:00–15:00) e terceiro
  (16:00–20:00) —, em dois grupos de dias (segunda, quarta e sexta; terça, quinta e sábado), inclusive
  em feriados. Na interface, os turnos se chamam primeiro, segundo e terceiro; os códigos de escala
  (1-seg a 3-ter) ficam para as telas da enfermagem.
- Cinco perfis: recepção, administração, visualizador, TI e enfermagem.
- Desenvolvido e mantido pelo TI da clínica — uma pessoa só.
- Convive com o Sistema de Controle de Estoque (SCE), que passará para o mesmo servidor dedicado.
- Entrega integral, sem faseamento. A coordenação não tem restrição de prazo.

## 2. Estado das macroentregas

| Macroentrega | Situação | Documento de referência |
|---|---|---|
| I — Requisitos | Concluída. ERS em assinatura, com as decisões DEC-57 a DEC-73 incorporadas antes da assinatura | `fase3-ers-v1_0.md` (ERS-002 v1.0) |
| II — Arquitetura | Aprovada; revisada na Macroentrega III | `DAS_recepcao-v1_1.md` |
| III — Design detalhado | **Concluída e aprovada em 2026-10-06** | `DDS_recepcao-v1_1.md`, `PT_recepcao-v1_1.md` (as v1.0 aprovadas ficam no histórico do Git) |
| IV — Codificação e verificação | **Em andamento:** incrementos 0 a 5 concluídos (§5) | `DDS_recepcao-v1_1.md`, `PT_recepcao-v1_1.md`, `comandos.md` |

## 3. O que a Macroentrega III entregou

### 3.1 Documentos

Registro do que foi entregue. As versões 1.0, o roteiro e o pacote do teste R-34 saíram do repositório depois
de incorporados (estão no histórico do Git); os documentos em uso são os de `docs/`.

| Documento | Conteúdo |
|---|---|
| DDS_recepcao v1.0 | Decisões DD-01 a DD-80; convenções transversais (§3); catálogo de operações e matriz de permissões (§4); design tático de MOD-01 a MOD-11 (§5 a §15); esquema físico (§12.4); protocolo do agente (§8.5); limites de processamento (§10.1) |
| PT_recepcao v1.0 | Estratégia por nível e técnica; cerca de 60 casos por área de risco; corpus hostil; desempenho; recuperação; acessibilidade; integração contínua em 11 etapas; homologação |
| DAS_recepcao v1.1 | Arquitetura atualizada com tudo o que o design mudou |
| ERS-002 v1.0 | Atualizada antes da assinatura: DEC-57 a DEC-73, RF-922 novo, RF-303 removido |
| ROTEIRO_R34 | Teste do agente de captura, executado com sucesso na estação da recepção |

### 3.2 Código já pronto, testado, para o repositório

| Artefato | Destino no repositório | Verificação feita |
|---|---|---|
| `nucleo/*.py` | `sar/nucleo/` | Contexto, erros, eventos, unidade de trabalho, parâmetros e portas; importado e exercitado |
| `importlinter.ini` | `.importlinter` (raiz) | 25 contratos; mantidos no esqueleto; violações de teste detectadas |
| `0001_esquema_inicial.py`, `0002_dados_fixos.py`, `env.py` | `sar/modulo_08_dados/migracoes/` | 40 tabelas; migração, reversão e nova migração em MySQL 8.0 |
| `usuarios_banco.sql` | `sar/modulo_08_dados/` | Usuários por processo, privilégio por tabela e coluna |
| `verificar_esquema.sh` | `scripts/` | 24 verificações de invariantes e privilégios, todas passando |
| `verificar_rastreabilidade.py` | `scripts/` | Lê os 258 itens da ERS; aponta lacunas e requisitos removidos |
| `prototipo-sar.zip` | `docs/prototipo/` (referência) | Telas e guia de componentes; tokens de cor e tipografia em `src/sar.css` |
| `teste-r34.zip` | `agente_captura/` (ponto de partida) | WIA, vidro e alimentador no Brother DCP-1610NW |

## 4. Decisões que mais mudam o código

As DD completas estão no DDS, §2.1. As que um desenvolvedor precisa ter em mente desde o primeiro dia:

| ID | Decisão |
|---|---|
| DD-02 | Portas no núcleo e raiz de composição: um módulo nunca importa outro que dependa dele |
| DD-03, DD-71 | Cadeia de auditoria serializada pela trava da cabeça no banco; id atribuído pela aplicação; serialização canônica |
| DD-12 | Modelos ORM com `lazy="raise"`; regras de negócio em funções puras |
| DD-16 | Fronteiras verificadas pelo `import-linter` a cada alteração |
| DD-22 | CPF e CNS com dígito inválido não são gravados |
| DD-23, DD-24 | Sessão de turno derivada do relógio; presenças só materializadas na confirmação |
| DD-25, DD-29 | Pareamento automático calculado pela `CompensacaoEngine`, função pura testada por propriedades |
| DD-42 | Documentos por modelo .docx com variáveis de lista fechada, convertidos por LibreOffice sem rede |
| DD-58 | Um usuário de banco por processo, com privilégio por tabela e coluna |
| DD-73 | Parâmetros declarados e lidos pelo núcleo |
| DD-76 | Tela inicial integra o ciclo da sessão; presentes e faltantes em quadros de cartões |
| DD-77 | Agente converte a página de BMP para PNG em memória e envia página por página |
| DEC-57 | Mínimo para salvar o paciente: nome, data de início e prontuário |
| DEC-61 | Anulação de cadastro descarta tudo o que está vinculado, na aprovação da administração |
| DEC-67, DEC-68 | Confirmação liberada na última hora do turno; sistema disponível das 05:00 às 20:00 |
| DEC-73 | Instituição que encaminhou o paciente não é registrada |

## 5. Ordem de construção

Incrementos curtos, cada um entregue com seus testes e com o pipeline verde. A ordem segue dependência e
risco: a fundação primeiro; depois o que vira faturamento e o que guarda documento de vinte anos.

| # | Incremento | Conteúdo | Pronto quando |
|---|---|---|---|
| 0 | Fundação | Repositório; Docker Compose de desenvolvimento; núcleo; MOD-08 (unidade de trabalho, repositórios, migrações); relógio e cifra; pipeline de integração contínua; fábrica de dados fictícios; script de rastreabilidade | Pipeline completo verde num serviço vazio; `verificar_esquema.sh` dentro do pipeline |
| 1 | Acesso e auditoria | MOD-01 (login, sessão, matriz de permissões, cadeia de auditoria, autorizações, usuários); valores de parâmetros do MOD-06; layout base das telas | CT-ACE e CT-AUD passando; cadeia íntegra sob 100 operações concorrentes |
| 2 | Cadastro | MOD-02 com rascunho, tríade, CEP, contatos e telefones, eventos, anulação; telas de cadastro | CT-CAD passando; cadastro completo cronometrado com dados fictícios |
| 3 | Operação | MOD-03: primeiro a `CompensacaoEngine` com testes por propriedade; depois escalas da enfermagem e a tela inicial com o ciclo da sessão | CT-FRQ passando; tela inicial no Playwright, inclusive arraste e teclado |
| 4 | Documentos | MOD-04: pipeline, quarentena, cofre, conferência, versões, retenção; agente de captura empacotado | CT-DOC passando, com o corpus hostil; captura real até a conferência dentro de 30 s |
| 5 | Emissão, relatórios e titular | MOD-05 (modelos .docx, conversor, relatórios, exportação) e MOD-11 | CT-EMI e CT-REL passando; modelos iniciais a partir dos formulários em branco da clínica (DEC-76) |
| 6 | Pendências e jobs | MOD-07 e MOD-09; backup pelo sistema operacional registrado como job | Matriz de pendências igual à da ERS (DD-55); jobs com trava e intervalo máximo |
| 7 | Carga inicial | MOD-10 com planilhas sintéticas que reproduzem os defeitos reais | CT-MIG passando; contagem fecha em toda simulação |
| 8 | Homologação e go-live | Servidor provisório ou dedicado; desempenho com base de volume; ensaios de recuperação; ZAP e ASVS; roteiros com as usuárias; carga real; conferência amostral; decisão do R-43 (scanner pela rede ou agente à prova de leigo, DAS §8); ata | Critérios da §9.2 do PT_recepcao |

**Andamento (10/11/2026).** Incrementos 0 a 5 concluídos e na `main` (o 5 pelo PR #6). **Incremento 6** concluído na
branch `incremento-6`, à espera do PR. Próximo: **Incremento 7** (carga inicial).

- **Incremento 6:** CT-PEN-01 a 05 e CT-JOB-01 a 07 passando (PT §4.10). MOD-07 com a matriz única igual à da ERS
  (DD-55), as 19 fontes ligadas, a tela de pendências, a contagem no início e as pendências de cada paciente nos
  cartões do turno e na ficha. MOD-09 com o APScheduler no worker, trava no banco, registro de cada execução, cursor
  das rotinas da madrugada (migração 0008) e a tela de jobs do TI, só leitura. Backup e cópia para o pen drive pelo
  sistema operacional, registrados como job (`scripts/servidor/`, DD-62). Decisões do incremento: DD-111 (alarme de
  disco por parâmetro, 85%) e DD-112 (execução manual de job só pela linha de comando do servidor).
- **Incremento 5:** CT-EMI-01 a 03 e CT-REL-01 a 03 passando; modelos iniciais (DOC-02, DOC-03, DOC-04, DOC-07 e
  crachá) a partir dos formulários da clínica, embutidos como versão 0 (DD-103). Decisões do incremento: DD-103 a
  DD-110 e a emenda DEC-76.
- **RNF-206, ensaio em desenvolvimento** (10/11/2026, conversor local, cinco emissões de cada): de 0,21 s a 0,36 s
  de mediana por modelo .docx, 0,70 s no pior caso; PDF em leiaute fixo pelo WeasyPrint, 0,13 s. A medição que vale
  é a da homologação, com a base de volume e na rede da clínica (PT §6).
- **Seguem para depois:** a medição dos 30 s da captura na estação (Incremento 4) e a decisão do R-43 sobre o agente
  de captura, ambas na homologação (Incremento 8). O backup real (restic, systemd e Docker no Ubuntu) e o primeiro
  ensaio de restauração também ficam para a homologação (PT §6.4).

**Regra de cada incremento:** nenhum requisito sai do incremento sem teste marcado com
`@pytest.mark.requisito(...)`. O relatório de rastreabilidade mostra o que falta e vai zerando.

## 6. Como começar o repositório

Feito no Incremento 0. Para preparar uma máquina nova, siga `docs/comandos.md` (seções 1 e 2). O arquivo
`dados/municipios_ibge.csv` já está no repositório; para regerá-lo, `comandos.md`, seção 9.

**Ferramenta usada na construção:** Claude Code, trabalhando no repositório, com os documentos de `docs/` como
referência. Um chat no Projeto continua útil para decisões e revisões.

## 7. Pendências abertas

**Da clínica**

- Assinatura da ERS, com o `.docx` gerado em 06/10/2026.
- Validação dos protótipos com a recepcionista (início com o ciclo da sessão, cadastro, pendências).
- Compra do servidor dedicado; enquanto isso, montagem do notebook provisório (DAS §7.6).
- Medir o desempenho atual do SCE antes de qualquer implantação (RNF-302).
- Ficha de cadastro em papel revisada, com a frase informativa da DEC-46.
- AP-07: aprovação em bloco dos refinamentos da Fase 2.

**Jurídicas**

- Bloqueiam o go-live: PJ-05 (aviso de privacidade completo e roteiro do canal do titular) e PJ-06
  (termo de ciência de uso).
- Abertas, sem bloquear: PJ-01, PJ-02, PJ-03, PJ-07, PJ-08.

**Pedido em análise, fora do escopo até decisão**

- Na reunião de aprovação das telas, a gestão pediu um **perfil Médico** (lista de pacientes, ficha só
  para leitura, relatórios) com um **resumo clínico** em texto livre, visível só para médicos e
  administração. A médica responsável sinalizou discordância, e uma nova reunião vai decidir.
- Enquanto não houver decisão, **nada disso entra na construção**. A ERS continua dizendo que o sistema
  não é prontuário eletrônico.
- Se for aprovado, entra como mudança controlada: escopo da ERS (§1.2), sexto perfil, módulo isolado
  (MOD-12) com texto cifrado, versões sem exclusão, auditoria de toda leitura, guarda de 20 anos,
  prontuário oficial continuando em papel, e acesso da administração condicionado a parecer jurídico
  (PJ-09) e termo de sigilo. O desenho atual comporta essa adição sem retrabalho: perfil novo é uma
  migração e uma linha na matriz; o módulo novo não toca os existentes.

**Técnicas**

- Teste da aplicação do SCE contra o MySQL LTS novo antes da migração (R-35).
- Repetir `verificar_esquema.sh` na imagem do MySQL 9.7 LTS de produção.
- Medir o processamento da ingestão no servidor (alvo de 15 s por página, DDS §8.5).

**Ajuste da reunião de aprovação já aplicado:** telefones e contatos do cadastro em linhas
alternadas, branco e cinza (componente `lista-zebrada` no guia de componentes).

**Resolvidas no Incremento 5:** logotipo e dados institucionais, cadastrados pela tela "Dados da clínica"; textos
dos documentos, tirados dos formulários em branco da clínica (DEC-76: DOC-05 e DOC-06 fora; DOC-01 em leiaute fixo).
**Resolvida antes:** o CSV de municípios do IBGE (`dados/municipios_ibge.csv`, `scripts/gerar_municipios_ibge.py`).

**Resolvidas na Macroentrega III:** teste do agente de captura (R-34 mitigado); modelo do scanner
confirmado (Brother DCP-1610NW); webcam disponível na estação (USB, 1280×720).

## 8. Como trabalhamos

- Documentos em português, no padrão da casa; o `.md` é a fonte versionada no Git. O `.docx` da ERS e
  da DAS é gerado quando preciso (assinatura, envio) e não fica no repositório; o DDS e o plano de testes ficam só
  em `.md`.
- **Durante o desenvolvimento não se registram versões.** Depois da aprovação, qualquer mudança gera nova
  versão do documento.
- Tecnologias na versão estável mais recente, linha LTS onde existir; versões exatas fixadas no arquivo
  de dependências e nas imagens.
- **Nenhum dado real de paciente em arquivos de trabalho, testes, issues ou capturas de tela.** Dados
  fictícios sempre; planilhas sintéticas para a carga.
- Decisões numeradas e rastreáveis. Mudança em requisito aprovado passa por emenda; mudança de design
  vira DD nova no DDS, e o que afeta a arquitetura entra numa nova versão da DAS.
- O sistema registra o que aconteceu; quem decide é a clínica: alertas e sinalizações, não bloqueios,
  salvo onde a ERS exige.
- Interface: CSP estrita, sem código inline; estado visual só por atributo; componente novo entra
  primeiro no guia de componentes.

## 9. Últimos identificadores em uso

| Família | Último | Família | Último |
|---|---|---|---|
| RF | RF-1011 (e RF-922; RF-303, RF-806 e RF-807 removidos) | DEC | DEC-76 |
| RNF | RNF-628 | AD | AD-27 |
| SEG | SEG-31 | DD | DD-112 |
| QAS | QAS-15 | P (pontos validados) | P-29 |
| INV | INV-15 | R (riscos) | R-43 |
| MOD | MOD-11 | DOC | DOC-07 |
| CT (casos de teste) | por área: CT-FRQ-10, CT-AUD-06, CT-ACE-07, CT-CAD-07, CT-DOC-14, CT-EMI-03, CT-REL-03, CT-MIG-05, CT-PEN-05, CT-JOB-07 | PJ | PJ-08 |
