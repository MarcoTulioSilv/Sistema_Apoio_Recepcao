**DOCUMENTO DE DESIGN DE SOFTWARE**

Sistema de Apoio à Recepção — SAR

DDS_recepcao · Versão 1.1

*Elaborado com base no SWEBOK 4.0 e na ISO/IEC/IEEE 1016*

Data: 2026-10-06 · Classificação: Confidencial — uso interno

## Controle de revisões

| **Versão** | **Data** | **Autor** | **Descrição** |
|---|---|---|---|
| 1.0 | 2026-10-06 | Equipe de desenvolvimento | Versão inicial aprovada. Decisões DD-01 a DD-80, convenções, catálogo de operações e matriz de permissões, design tático de MOD-01 a MOD-11, esquema físico implementado, contratos, protocolo do agente de captura, protótipos e guia de componentes. Baseado na ERS-002 v1.0 e na DAS v1.1. |
| 1.1 | 2026-10-06 | Equipe de desenvolvimento | DD-81: logs técnicos estruturados e minimizados, correlação entre auditoria e log (migração 0003), buscas por POST, erros sem mensagem nem valor, MySQL sem logs de instrução, guarda de 90 dias e verificação automática do RNF-624. Linhas alternadas em telefones e contatos (componente `lista-zebrada`). DD-82: log binário do MySQL desligado. Emenda à DD-81: campos `erro` e `restricao` na lista permitida. |

---

## 1. Introdução

### 1.1 Propósito

Este documento detalha o design do SAR a partir da arquitetura aprovada no DAS_recepcao v1.0. Define,
por módulo, agregados, entidades, regras, serviços públicos e eventos de domínio; os contratos entre
módulos; o esquema físico do banco; a matriz de permissões; o design das telas, do pipeline de
ingestão, do agente de captura e dos jobs; e o plano de testes.

### 1.2 Escopo

Cobre os módulos MOD-01 a MOD-11. As decisões arquiteturais do DAS não são rediscutidas aqui; quando
o design exige ajuste no DAS, o ajuste é listado na §2.2 e incorporado numa nova versão do DAS ao fim
da Macroentrega III.

### 1.3 Referências

- ERS-002 v1.0 — Especificação de Requisitos de Software do SAR
- DAS_recepcao v1.0 — Documento de Arquitetura de Software do SAR
- Fase 2 — Modelo de domínio v1.0 e Casos de uso
- Modelagem de ameaças e de privacidade (STRIDE e LINDDUN)
- SWEBOK v4.0 — Software Design, Software Construction e Software Testing
- ISO/IEC/IEEE 1016:2009 — Software design descriptions
- Lei nº 13.709/2018 (LGPD); Lei nº 13.787/2018; Decreto nº 10.278/2020

### 1.4 Organização pelos pontos de vista da ISO/IEC/IEEE 1016

| **Ponto de vista** | **Seção** |
|---|---|
| Contexto e composição | DAS §4, e §3 e §5 deste documento |
| Lógico (agregados, entidades, regras) | §5 a §15 |
| Dependências e interfaces | §3.3 e contratos de cada módulo |
| Informação (esquema físico) | Convenções na §12; tabelas no esquema de cada módulo; migração completa a elaborar (§16) |
| Interação e estado | Sequências e máquinas de estado de cada módulo |
| Algoritmo | Regras puras de cada módulo |
| Recursos | Jobs e pipeline — a elaborar |

### 1.5 Convenções

- Decisões de design numeradas como **DD-nn**, distintas das AD do DAS e das DEC da clínica.
- Pontos que dependem de validação com a clínica numerados como **P-nn** (§17).
- Nenhum dado real de paciente neste documento. Exemplos são fictícios.

---

## 2. Decisões de design

### 2.1 Registro

| **ID** | **Decisão** | **Motivo** |
|---|---|---|
| DD-01 | **Retenção derivada.** Nenhuma coluna de prazo no documento. Com período de tratamento aberto, não há prazo. Encerrado o último período, o marco é a data mais recente entre o evento de encerramento e o último documento incorporado do paciente; o prazo é o marco somado aos anos de retenção do tipo. Novo período anula o prazo. Ao fim do prazo, o documento fica **elegível** para descarte (DD-04), nunca é descartado automaticamente | Lei nº 13.787/2018, art. 6º: vinte anos a contar do último registro. ERS §3.5, RF-709, RNF-610. Coerente com "nada derivado é armazenado" (DAS §6.3) |
| DD-02 | **Portas definidas pelo consumidor, implementadas pelo provedor, ligadas na raiz de composição.** Quando um módulo-base precisa de algo de um módulo que depende dele, o módulo-base define uma interface (`Protocol`) e um registro; o outro módulo implementa e é registrado em `sar/composicao.py`. Aplica-se à execução de autorizações (Command), aos impedimentos de encerramento de período, à fonte do marco de retenção e aos eventos de domínio | Elimina os ciclos MOD-01 ↔ MOD-02/03/04. SWEBOK, Software Design: princípio de inversão de dependência |
| DD-03 | **Cadeia de auditoria serializada no banco e com formato canônico.** Tabela de linha única `auditoria_cabeca` travada com `SELECT … FOR UPDATE`, como última operação antes do commit. Hash sobre serialização canônica versionada (§3.10) | Web multithread e worker em processos separados: trava em memória não serializa. Serialização canônica impede falsa divergência após atualização de biblioteca |
| DD-04 | **Descarte ao fim da retenção por destruição da chave.** A proibição de exclusão física (DAS §6.3) vale antes do prazo. Após o prazo, o descarte é operação autorizada pela administração (DEC-42) e auditada: destrói a chave do documento e remove o arquivo; o hash e o registro do descarte permanecem. A política de retenção do restic tem horizonte declarado, após o qual o documento descartado deixa de existir também no backup | LGPD, art. 16. INV-13 continua valendo antes do prazo |
| DD-05 | **Tokens gravados só como hash.** Sessão de usuário e token de captura: 256 bits aleatórios (`secrets.token_urlsafe(32)`); o banco guarda apenas o SHA-256 | Um dump do banco, presente no backup e no pen drive, não entrega sessões válidas |
| DD-06 | **Telefone com duas chaves estrangeiras e verificação.** `paciente_id` e `contato_id`, anuláveis, com `CHECK` de exatamente um preenchido. Confirmada (P-07) | INV-12 garantida pelo banco, como exige o §6 do modelo de domínio |
| DD-07 | **Cifragem por finalidade.** Componente `Cifra` no núcleo compartilhado, AES-256-GCM (biblioteca `cryptography`), com chaves derivadas da chave mestra por HKDF-SHA256, uma por finalidade (`documentos`, `rascunhos`). O identificador do registro entra como dado associado, impedindo a troca de cifrados entre registros. O CofreDocumentos usa a finalidade `documentos` em envelope; o rascunho usa `rascunhos` | Rascunho cifrado (DAS §6.2) sem expor a chave de documentos ao MOD-02 |
| DD-08 | **Recuperação de jobs.** Cada job declara agrupamento de execuções perdidas, tolerância de atraso e se roda na partida do worker. A abertura de sessões roda na partida e a cada hora do período de funcionamento, apoiada na idempotência. Fuso `America/Sao_Paulo` via `zoneinfo`, com `tzdata` atualizado na imagem | Servidor fora do ar às 06:00 não pode deixar o dia sem sessão (R-38) |
| DD-09 | **Política de segurança de conteúdo estrita.** `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'`. htmx sem avaliação de código e sem estilos injetados; nenhum atributo de evento inline. Alpine no build CSP: toda lógica em componentes registrados com `Alpine.data()`, sem expressões nos atributos. Os nomes exatos das opções da série 4 do htmx são confirmados na construção Exceção única: nas telas de captura, `connect-src` inclui o endereço de loopback do agente (DD-39) | Condiciona o guia de componentes e os protótipos |
| DD-10 | **Auditoria minimizada.** Escrita registra só os campos alterados (`{campo: [antes, depois]}`). Leitura registra só identificadores. Busca registra a quantidade de resultados, nunca o termo buscado | LGPD, art. 6º, III. A trilha é dado sensível guardado por cinco anos |
| DD-11 | **Metadados mínimos do Decreto nº 10.278/2020** gravados em cada documento desde a captura | O papel continua sendo o registro de origem (DEC-04); os metadados mantêm aberto, a baixo custo, o caminho para um eventual descarte do papel |
| DD-12 | **Modelos ORM sem carregamento implícito.** Modelos SQLAlchemy em MOD-08, com relacionamentos `lazy="raise"`; repositórios carregam explicitamente o que cada caso precisa. Regras de domínio em funções puras (`regras.py` de cada módulo), testáveis sem banco | Garante na prática a regra "só MOD-08 acessa o banco": um objeto não dispara consulta escondida fora do repositório. Atende RNF-705 |
| DD-13 | **Evento embutido no período de tratamento.** A relação é 0..1; os campos do evento ficam em `periodo_tratamento`. INV-02 garantida por coluna gerada e índice único (§6.4) | Invariante estrutural sem gatilho. Correção de evento é atualização auditada da mesma linha |
| DD-14 | **Cobertura em tabela própria, com vigência.** Corrige o DAS §6.2, que trazia a cobertura como colunas do período | Modelo de domínio §3.1 e §7.1, RF-302, INV-09 |
| DD-15 | **Eventos de domínio síncronos, na mesma transação.** Barramento em processo, no núcleo compartilhado. Manipuladores registrados na raiz de composição; falha no manipulador desfaz a operação inteira. Manipuladores não produzem efeito fora do banco | Monólito pequeno: consistência imediata sem fila externa |
| DD-16 | **Fronteiras verificadas automaticamente.** Contratos do `import-linter` (`lint-imports`) no pipeline: módulos só importam `contrato` de outros módulos; regras do DAS §4.2 como contratos proibitivos | Regra de dependência que só vive em documento se degrada |
| DD-17 | **Concorrência otimista.** Coluna `versao` nos agregados editáveis por tela (paciente, usuário); conflito informa quem alterou e pede recarga | Duas estações editando o mesmo cadastro |
| DD-18 | **Prazo do pedido de titular derivado.** Removida a coluna `prazo`; prazo = data de recebimento + parâmetro (15 dias por padrão) | LGPD, art. 19, II. "Nada derivado é armazenado" |
| DD-19 | **Sessão encerrada por inatividade.** Após o prazo configurável, a sessão é encerrada no servidor; a próxima ação exige login e é atribuída a quem entrar. Requisições automáticas da tela (atualização de pendências) não renovam a inatividade. Cookie `__Host-sar_sessao`; identificador trocado a cada login; limite absoluto de duração; uma sessão ativa por usuário (P-02) | QAS-09, RNF-602. O rascunho no servidor garante a retomada |
| DD-20 | **Atendimento ao titular em módulo orquestrador próprio: MOD-11.** Depende de MOD-01, MOD-02, MOD-04, MOD-05 e MOD-08; só o MOD-07 o consulta | O pedido de acesso precisa de cadastro e documentos; no MOD-01 criaria ciclo |
| DD-21 | **Alcance da INV-01.** Nenhum fato datado pode ter data posterior ao óbito: presença, alocação, troca de turno, evento e período de tratamento. A captura de documento não é fato datado e é permitida após o óbito, inclusive a certidão que o comprova e documentos de cadastro que ainda faltavam. Os contratos do MOD-03 consultam `data_obito`; o MOD-04 não a usa para recusar captura | A certidão de óbito é emitida dias depois do óbito (DEC-50, RF-607); a leitura literal do critério do UC-07 impediria anexá-la. Resolve P-05; incorporada à ERS (DEC-62) |
| DD-22 | **CPF e CNS inválidos não são gravados.** O dígito verificador é conferido na digitação e no serviço; CPF ou CNS inválido impede salvar o paciente e a atualização. O campo vazio continua permitido, como pendência. **Na carga inicial (MOD-10), todo dado inválido da planilha segue a mesma regra:** o valor não é importado, o campo fica vazio, o caso vai ao relatório de exceções e o paciente é cadastrado com a pendência correspondente | Evita a entrada de cadastros com identificador errado, que depois seriam difíceis de encontrar e de corrigir. A carga não trava por dado ruim da planilha, e nenhum dado ruim entra na base. Incorporada à ERS antes da assinatura (DEC-58); prevalece sobre o UC-01 A4 pela regra de precedência da ERS |
| DD-23 | **Sessão de turno derivada do calendário.** A sessão de cada data e escala existe por definição, a partir da data de implantação (RN-05). A linha em `sessao_turno` só é gravada na primeira marcação ou na confirmação, com unicidade por data e escala. Não há job de abertura nem job de lembrete: a tela inicial calcula as sessões devidas e não confirmadas | Cumpre RF-501 e DEC-54 — a sessão "abre sozinha" — sem depender de o worker rodar na hora certa. Elimina o modo de falha do DD-08 para a abertura e reduz o R-38 aos demais jobs |
| DD-24 | **Presença materializada na confirmação.** Antes da confirmação, gravam-se só as exceções: ausência marcada e paciente acrescentado. Na confirmação, a lista esperada é resolvida e todas as presenças são gravadas, na mesma transação | O padrão "todos presentes" não vira dado antes de alguém afirmá-lo (modelo §7.5). Mudança de alocação ou de evento antes da confirmação não exige sincronização |
| DD-25 | **Pareamento automático derivado; só a escolha humana é gravada.** O pareamento cronológico (RF-918) é recalculado a cada consulta pela função pura `CompensacaoEngine`. Gravam-se apenas as ligações escolhidas pela recepção (ao acrescentar o paciente ou ao refazer o pareamento) e as trocas pontuais | Pareamento gravado teria de ser refeito a cada ausência nova, e divergiria da regra. "Nada derivado é armazenado" |
| DD-26 | **Fechamento do mês derivado.** O mês está fechado quando terminou e todas as suas sessões estão confirmadas. A marca de alteração após o fechamento (RF-915) é fato gravado, criada automaticamente por toda operação autorizada que alcance mês fechado | Sem ato de fechamento a esquecer. Reabrir sessão reabre o mês; reconfirmar fecha de novo; a marca permanece |
| DD-27 | **Alocação só com data de início.** O fim é derivado da alocação seguinte ou do encerramento do período. Alocação com escala nula registra "sem alocação a partir de" | Um único valor a manter por vigência. RF-403: ficar sem escala é fato explícito, nunca omissão |
| DD-28 | **Troca pontual e extra planejada são intenções registradas pela enfermagem**, que alteram a lista esperada das sessões. O termo assinado (DOC-03 ou DOC-07) é ligado por evento de domínio, como o comprovante de evento (§6.5) | RF-406, RF-809, DEC-48. A pendência de termo encerra por derivação |
| DD-29 | **`CompensacaoEngine` testada por propriedades.** Além dos casos da regra, testes com geração aleatória (Hypothesis) verificam as propriedades do §7.6: cada ausência e cada presença em no máximo um par; pares só no mesmo mês; número de pares automáticos igual ao menor dos dois conjuntos livres; resultado independente da ordem de entrada | É o cálculo mais sensível do sistema e alimenta o relatório de faturamento. RNF-705 |
| DD-30 | **Preparação do turno (RF-922, DEC-64).** A sessão entra em "preparação" a partir do início do turno menos a antecedência configurada no MOD-06 (60 minutos por padrão). A tela mostra a lista esperada, com as pendências de cada paciente obtidas do MOD-07 e filtradas pelo perfil de quem consulta. Continua derivada do relógio, sem job | A sala é limpa nessa hora e a recepção separa fichas e crachás. A composição usa só contratos de leitura: MOD-03 fornece a lista, MOD-07 as pendências |
| DD-31 | **Evento de encerramento e fatos posteriores (P-08, DEC-65).** Trocas e extras planejadas depois da data do evento são canceladas automaticamente, na mesma transação, com registro. Presença em data posterior impede o evento; ocorre só com evento de data retroativa, e a tela oferece a solicitação de autorização para corrigir as presenças | Coerente com a INV-01 e com a regra de que sessão confirmada só se altera por autorização (RF-1008) |
| DD-32 | **Confirmação na última hora do turno (DEC-67).** A confirmação é liberada a partir do fim do turno menos a antecedência configurada no MOD-06 (60 minutos por padrão), igual para os três turnos; o pedido de confirmação aparece nesse momento. Terminado o turno sem confirmação, a sessão vira pendência de urgência. Janela de disponibilidade 05:00–20:00, de segunda a sábado (DEC-68); backups, verificação da cadeia e manutenção rodam entre 20:00 e 05:00 | Com três horas de diálise, ninguém chega na última hora: quem veio já está definido. A recepção encerra o expediente às 20:00, e a confirmação do turno 3 precisa caber nele |
| DD-33 | **Fila de ingestão no próprio banco.** O estado da ingestão é a fila; o worker toma trabalho com `SELECT … FOR UPDATE SKIP LOCKED`. Sem broker de mensagens | Um contêiner a menos para manter; a fila herda backup e transação do banco |
| DD-34 | **Quarentena cifrada e com prazo.** O arquivo recebido é gravado cifrado (finalidade `quarentena`, DD-07), fora do backup (SEG-29). Ingestão não concluída em 24 h expira, e o arquivo é apagado | A quarentena guarda imagem de documento de paciente; RNF-604 vale para ela também |
| DD-35 | **Processamento isolado e limitado.** Validação, reconstrução e extração rodam em subprocesso do worker, com limite de memória e de CPU, tempo máximo, limite de pixels e de páginas (SEG-30). O contêiner do worker só alcança o banco e o ClamAV | Arquivo hostil derruba no máximo o subprocesso, nunca o worker nem a interface |
| DD-36 | **Documento imutável; versão e vínculo como metadados.** Nova versão é nova linha que aponta a anterior (`substitui_id`); a vigente é derivada. A revinculação (RF-713) altera só o paciente do documento, com motivo e auditoria, e publica `DocumentoRevinculado` | INV-06, RF-708. Arquivo e hash nunca mudam |
| DD-37 | **Incorporação em duas fases.** O arquivo cifrado é gravado em temporário e renomeado antes do commit; a prova de encadeamento é preenchida na fase de commit da auditoria (DD-03). Uma varredura noturna remove arquivo sem linha correspondente | R-41. Falha entre gravar e confirmar deixa no máximo um arquivo órfão, nunca uma linha sem arquivo |
| DD-38 | **Toda leitura confere o hash.** Divergência bloqueia a exibição e abre aviso de integridade para a administração e o TI | SEG-15. Detecta alteração do arquivo no disco no momento em que importa |
| DD-39 | **Agente de captura fechado.** O endereço do servidor e o certificado raiz estão na configuração do agente, nunca na requisição. O agente só aceita chamadas da origem do servidor (cabeçalho `Origin` e CORS restrito) e responde à verificação de acesso à rede local do navegador. Recebe do navegador só a ingestão e o token de uso único | Impede que uma página qualquer use o agente para escanear e enviar a outro destino. A chamada de página em rede local para o próprio computador é restringida pelos navegadores atuais; o teste do R-34 confirma o comportamento no navegador da recepção |
| DD-40 | **Extração por tipo e confirmação campo a campo.** Cada tipo define os campos candidatos (por exemplo, CNS no cartão do SUS, CEP no comprovante de endereço). A conferência mostra cada campo ao lado do valor atual do cadastro; só o que a recepcionista confirmar vai ao MOD-02, pelo contrato de atualização, com a mesma validação da digitação (SEG-26). O documento é incorporado mesmo que algum campo seja recusado | RF-703, RF-704, SEG-31. Os candidatos esperam a conferência gravados cifrados na ingestão (finalidade `quarentena`) e são apagados ao concluir, rejeitar ou expirar, no máximo em 24 h (P-18) |
| DD-41 | **Verificações periódicas na janela noturna.** Varredura antimalware do acervo toda semana (SEG-22) e conferência de hash de todo o acervo todo mês, entre 20:00 e 05:00 | Não disputa recursos com a operação (DEC-68) |
| DD-42 | **Modelos de documento em .docx, enviados pela administração.** Cada documento (DOC-01 a DOC-07 e crachá) tem um modelo .docx com variáveis `{{ nome }}`, `{{ cpf }}`, `{{ data_extenso }}`…, de uma lista fechada por documento. O envio passa pela validação da §9.2; o modelo só vale depois de prévia com dados fictícios e ativação. Preenchimento com docxtpl em ambiente Jinja2 isolado (*sandbox*), com escape e erro para variável desconhecida. O .docx preenchido é convertido em PDF por serviço de conversão com LibreOffice, em contêiner próprio sem acesso à rede; a estação recebe só o PDF | RNF-703 em sua forma mais forte: a clínica muda texto **e** leiaute no Word, sem programador. A validação e o isolamento impedem que um modelo enviado execute código ou busque recurso externo |
| DD-43 | **Emissão sem guardar o arquivo nem o texto livre.** Cada emissão gera o PDF de novo, a partir do cadastro atual (RNF-903), e o entrega em memória. Registra-se só modelo, paciente, referência (troca ou competência), instante e autor. Texto livre da carta de recusa e dados digitados do profissional não são gravados: a versão assinada volta pela digitalização | Minimização (LGPD, art. 6º, III); o texto livre pode descrever o que foi recusado. Nenhum PDF antigo para reaproveitar por engano |
| DD-44 | **Relatório como tabela única com três saídas.** Cada relatório é uma consulta que produz um modelo tabular — colunas, linhas, filtros aplicados e marcas (início da série, sessões não confirmadas, mês alterado, prévia). Tela, PDF e XLSX são renderizadores do mesmo modelo (Strategy) | RF-912: o arquivo tem exatamente as colunas da tela, por construção. As marcas aparecem nas três saídas |
| DD-45 | **Exportação segura e auditada.** XLSX escrito só com valores (texto como texto, sem fórmulas), o que impede injeção de fórmula; PDF pelo mesmo leiaute da tela. Toda exportação registra relatório, filtros e formato (RNF-607). Arquivo gerado em memória, entregue com `Cache-Control: no-store` | Relatório agregado é dado pessoal (DEC-44) |
| DD-46 | **Geradores de PDF sem acesso externo.** Nos relatórios, o WeasyPrint recebe um buscador de recursos que só aceita dados embutidos — logotipo, foto e fontes locais. Qualquer URL é recusada Nos documentos, o conversor roda sem rede, e o modelo .docx com referência externa é recusado no envio | Nenhum dado sai por gerador de PDF (RNF-611, RNF-627); impede que configuração ou modelo faça o servidor buscar endereço externo |
| DD-47 | **Prévia do mês corrente separada do relatório mensal.** A prévia usa o mesmo cálculo, mas carrega a marca "PRÉVIA — mês em aberto" no título e em cada página, e nunca é oferecida como relatório mensal | Modelo §7.12: o relatório mensal só existe com o mês completo (RF-913) |
| DD-48 | **Parâmetros tipados, declarados no código.** Cada parâmetro é declarado num registro em código: nome, tipo, unidade, mínimo, máximo, padrão e perfil que pode alterá-lo. O banco guarda só o valor alterado. Valor fora dos limites é recusado; parâmetro não declarado não existe. Leitura por operação, sem cache entre processos | Configuração errada é causa comum de falha; limites no código impedem, por exemplo, inatividade de zero minuto. Web e worker sempre leem o mesmo valor |
| DD-49 | **Dados de referência são inativados, nunca excluídos.** Convênio em uso por cobertura fica no histórico; inativado, deixa de ser oferecido em novo registro | O histórico de cobertura e os relatórios de períodos passados continuam corretos (RF-302, RF-905) |
| DD-50 | **Logotipo tratado como arquivo não confiável.** Só PNG ou JPEG, conferidos por assinatura binária, com limite de tamanho e de pixels, reencodados em subprocesso com limites antes de gravar | Mesmo princípio do SEG-10, aplicado ao único arquivo de configuração |
| DD-51 | **Data de implantação imutável após o uso.** Definida pelo TI na implantação; travada a partir da primeira sessão confirmada | Ela define o início das séries (RF-907, RN-05) e das sessões devidas (DD-23); alterá-la depois reescreveria o passado |
| DD-52 | **Municípios: inclusão pela tela, sem alteração nem exclusão.** A tabela nacional do IBGE, já com códigos de 7 dígitos, é carregada na implantação. Município criado depois é incluído pelo TI, com código de 7 dígitos e UF; código cujo dígito verificador não confere gera alerta com confirmação, não bloqueio, porque a tabela oficial tem exceções à regra do dígito. Nome e código de município existente não mudam | Um município novo não deve exigir nova versão do sistema. Mudar ou apagar um existente alteraria cadastros, relatórios por cidade e documentos já emitidos, e duplicar criaria divergência de grafia (modelo §7.8) |
| DD-53 | **Conversão de 6 para 7 dígitos por consulta à tabela, não por cálculo (RF-1104).** Código de 6 dígitos (formato usado no DATASUS e nas planilhas) é convertido procurando na tabela do IBGE o código de 7 dígitos que começa por ele; os seis primeiros dígitos identificam o município de forma única. Código sem correspondência vai ao relatório de exceções da carga (RF-1106, DEC-58). O cálculo do dígito verificador serve só de conferência | A regra do dígito tem exceções na tabela oficial; calcular erraria justamente nesses municípios, enquanto a consulta acerta todos. Vale para a carga inicial (MOD-10) e para qualquer entrada de 6 dígitos |
| DD-54 | **Pendências por fontes registradas.** Cada módulo que origina pendência implementa a porta `FontePendencia` (código, prioridade, listar, listar por pacientes) e é registrado na raiz de composição. O MOD-07 agrega, filtra pela matriz de perfis e ordena; não importa nenhum módulo (DD-02) | Pendência nova não altera o MOD-07. Cada regra de pendência fica no módulo dono do dado, testada ali |
| DD-55 | **Matriz de pendências única, em código, espelho da ERS §3.2.13.** Um teste compara a matriz do código com a tabela da ERS | A matriz é requisito assinado; divergência entre código e ERS vira falha de teste, não surpresa na homologação |
| DD-56 | **Sem descarte manual de pendência.** Pendência some quando a causa é resolvida. As decisões que encerram pendência sem mudar o dado — duplicidade descartada, ciência da enfermagem, aviso de integridade encerrado — são fatos gravados no módulo dono, com autor | Lista confiável (modelo §7.4): o que está nela é o que falta fazer |
| DD-57 | **Atualização automática sem renovar a sessão.** A tela inicial atualiza as contagens a cada 60 segundos, com a marca de requisição automática (DD-19), que não conta como atividade | Pendência nova aparece sem recarregar a página, e a estação desatendida continua encerrando a sessão por inatividade |
| DD-58 | **Um usuário de banco por processo, com privilégio por tabela e por coluna.** Uma operação precisa de uma só conexão, para que o dado de negócio e a auditoria fiquem na mesma transação; por isso o isolamento é por processo (`sar_web`, `sar_worker`, `sar_expurgo`, `sar_migracao`), não por módulo. Em cada tabela, só o privilégio necessário: auditoria só com inserção e leitura; `documento` sem exclusão e com atualização restrita às colunas de vínculo, descarte e bloqueio | SEG-14 e RNF-609 garantidos pelo próprio banco. Mesmo com falha na aplicação, o arquivo e o hash de um documento não mudam, e a trilha não é alterada |
| DD-59 | **Isolamento de transação READ COMMITTED e repetição em impasse.** A unidade de trabalho repete a operação inteira, até três vezes, em impasse ou tempo de trava esgotado. Por isso, nenhuma operação produz efeito fora do banco antes do commit, exceto a gravação em duas fases do documento (DD-37) | Menos travas de intervalo que o padrão do MySQL; a serialização que importa já é explícita (DD-03, travas de agregado) |
| DD-60 | **Migrações só para frente depois da implantação.** Alembic com geração revisada à mão; convenção de nomes de restrições; cargas de tabelas fixas como migrações de dados; migração executada por contêiner próprio, antes de web e worker subirem. Reversão só até o go-live | AD-10. Em produção, voltar atrás é restaurar backup, nunca desfazer migração |
| DD-61 | **Jobs com trava exclusiva e registro de execução.** Cada job obtém trava nomeada no banco antes de rodar; uma segunda instância do worker não executa o mesmo job em paralelo. Toda execução grava início, fim, resultado e quantidade de itens em `job_execucao`, sem dado pessoal. Cada job declara o intervalo máximo entre sucessos; passar dele gera a pendência 17 | R-38 e §7.5 do DAS |
| DD-62 | **Backup fora do worker, registrado como job.** Dump e restic rodam por agendamento do sistema operacional do servidor, que alcança os volumes, o disco local e o pen drive. Ao terminar, o script registra a execução em `job_execucao` pela linha de comando do SAR; backup atrasado vira pendência do TI como qualquer job | O worker não precisa de acesso ao Docker nem aos discos. A falha silenciosa mais cara, a do backup, fica visível |
| DD-63 | **Consumidor da fila de ingestão contínuo, fora do agendador.** Laço próprio no worker, consultando a fila a cada 2 segundos, uma ingestão por vez | RNF-208: até 30 s da captura à conferência. O agendador fica para as rotinas de horário |
| DD-64 | **Rotinas pesadas escalonadas e em série, com limite de horário (P-26).** Início às 02:00, com 10 minutos entre uma chamada e a seguinte. As rotinas pesadas do worker compartilham uma trava: se a anterior ainda estiver rodando, a seguinte espera. Rescan e conferência de hash trabalham com cursor e param às 04:30; a execução seguinte continua de onde parou, até percorrer o acervo inteiro | Evita sobrecarga no servidor e garante que nada pesado alcance a janela de operação das 05:00 (DEC-68), mesmo com o acervo crescendo ao longo de 20 anos |
| DD-65 | **Carga executada pelo TI sem ver dado de paciente.** O TI coloca as planilhas numa pasta protegida do servidor e roda o comando de carga. O terminal mostra só contagens. O relatório de exceções e a conferência amostral ficam dentro da aplicação, para a recepção e a administração | UC-17 tem o TI como ator, e o RF-1004 impede o TI de ver dado de paciente. Os dois se conciliam separando quem executa de quem confere |
| DD-66 | **Simulação antes da efetivação.** A carga roda quantas vezes for preciso em modo de simulação, que faz tudo numa transação e desfaz no fim, deixando só o relatório de exceções. A efetivação é única, em uma transação, e o sistema recusa uma segunda | As exceções são corrigidas nas planilhas e a simulação é repetida até o relatório ficar aceitável, sem sujar o banco |
| DD-67 | **Carga pelas mesmas regras da tela.** Pacientes são criados pelo contrato do MOD-02, com as mesmas validações: mínimo da P-03, CPF e CNS (DEC-58, DEC-59), tríade como pendência. Nenhum atalho de gravação direta | O paciente migrado é indistinguível do cadastrado pela tela; regra nova vale para os dois |
| DD-68 | **CEP da carga classificado localmente, sem consulta em massa.** Formato conferido; CEP ausente ou malformado vai às exceções; todo CEP importado entra como não verificado e vira pendência. A verificação é feita depois, um a um, pela recepção | A §3.1 da ERS proíbe validação em massa no serviço de CEP. RF-1105 atendido pela classificação e pela pendência |
| DD-69 | **Área de trabalho da carga descartada no aceite.** As linhas lidas das planilhas ficam cifradas numa área de trabalho, só enquanto duram a revisão das exceções e a conferência amostral. O aceite da administração encerra a carga e apaga a área de trabalho | O lado a lado da conferência precisa da linha original; depois do aceite, ela é só uma cópia a mais de dado pessoal |
| DD-70 | **Cobertura só com data de início.** Como na alocação (DD-27), o fim de uma cobertura é o início da seguinte. A INV-09 (sem sobreposição) passa a valer por construção, com unicidade de período e início | Uma regra a menos para o serviço garantir; revisa a DD-14, que previa vigência com fim |
| DD-71 | **Id da auditoria atribuído pela aplicação.** O próximo id vem da cabeça da cadeia, lida sob trava (DD-03), porque o próprio id entra no hash (§3.10). A coluna não é autoincremento | Com autoincremento, o id só existiria depois da inserção, e o hash teria de ser gravado numa segunda escrita, que o usuário de banco não pode fazer |
| DD-72 | **"No máximo um ativo" por coluna gerada.** Sessão ativa por usuário (P-02), período aberto por paciente (INV-02), troca e extra não canceladas, modelo ativo por documento e efetivação da carga usam a mesma técnica: coluna gerada que vale 1 quando a linha está ativa e nulo quando não, com índice único | O banco garante a regra mesmo sob concorrência, sem gatilho |
| DD-73 | **Parâmetros declarados e lidos pelo núcleo.** A declaração dos parâmetros (DD-48) e a porta `LeitorParametros` ficam no núcleo; o MOD-06 só guarda e altera os valores. Nenhum módulo importa o MOD-06 para ler parâmetro | O MOD-01 precisa dos parâmetros de sessão e de bloqueio, e o MOD-06 precisa do MOD-01 para auditar e autorizar; ler pelo MOD-06 criaria ciclo |
| DD-74 | **Evento só com consumidor; ordem explícita por porta.** Ficam quatro eventos (§3.11). Encerramento de período e anulação, cujos efeitos precisam de ordem e de resposta (impedimentos, impacto), usam portas chamadas diretamente | Evento sem consumidor é código morto; efeito por evento não devolve resposta a quem publica |
| DD-75 | **Na interface, primeiro, segundo e terceiro turno.** A recepção vê os turnos pelo nome do dia a dia. Os códigos de escala (1-seg, 1-ter…) aparecem só nas telas de escala da enfermagem (alocação, trocas e extras). Banco, código e contratos não mudam: é só o rótulo exibido | Linguagem de quem usa a tela o dia inteiro; o código de escala continua sendo a definição da enfermagem |
| DD-76 | **Sessão de turno integrada à tela inicial.** Não há tela separada de turno. A tela inicial mostra as sessões que pedem ação, no ciclo em preparação → aberta → confirmação liberada → confirmada; confirmada uma sessão, a seguinte assume a tela. Sessão terminada sem confirmação aparece em urgência, ao lado da próxima em preparação. Presentes e faltantes em dois quadros de cartões; o paciente troca de quadro por clique, pelo botão do cartão ou arrastando. Antes do início, faltante é ausência avisada (P-13) | Um só lugar e um só gesto para o turno inteiro. Mantém RF-922 (preparação com pendências) e a confirmação da DD-32 |
| DD-77 | **O agente converte a página para PNG antes de enviar.** O driver do scanner entrega sempre BMP sem compressão, qualquer que seja o formato pedido (8,7 MB por página em cinza). O agente converte em memória para PNG, sem perda, e envia página por página, enquanto digitaliza a seguinte | A lista de tipos aceitos pelo servidor continua PDF, JPEG, PNG e TIFF (SEG-02). PNG fica 2 a 12 vezes menor que o BMP e evita perda antes da reconstrução |
| DD-78 | **Documento só em tons de cinza.** A captura de documento não oferece cor; a foto da webcam é colorida | DC-07. Página colorida tem três vezes o tamanho e é mais lenta no scanner (teste do R-34) |
| DD-79 | **Scanner escolhido pelo nome configurado.** O agente procura o scanner pelo nome no arquivo de configuração, nunca pela posição na lista do WIA | A estação tem outro equipamento de imagem instalado (Epson L365); ligar ou desligar outro aparelho não pode trocar o scanner usado |
| DD-80 | **Página do SAR sempre em HTTPS, com origem exata.** A câmera só funciona em contexto seguro, e a proteção do agente é a origem exata configurada | Teste do R-34: webcam bloqueada na página em HTTP; Chrome 154 não pediu permissão de rede local |
| DD-81 | **Logs técnicos estruturados, minimizados e correlacionados.** Uma linha JSON por evento, só com campos de uma lista permitida: instante, nível, processo, módulo, código do evento, id da requisição, id interno do usuário, perfil, duração, resultado, tipo do erro e nome da restrição — o que não está na lista não é escrito. Exceção registrada pelo tipo (campo `erro`, nome da classe), módulo e nome da restrição violada (campo `restricao`, só em erro de banco), nunca pela mensagem nem pelos argumentos. *Emenda de 2026-10-06: campos `erro` e `restricao` acrescentados à lista, para que o registro da exceção exigido acima tenha campo próprio.* Acesso HTTP registrado sem parâmetros de URL; **toda busca com termo de paciente é POST**; o Caddy descarta a query. MySQL de produção sem log geral e sem log de consultas lentas; diagnóstico pelo `performance_schema`, que agrupa sem valores. Saída padrão dos contêineres com rotação do Docker; guarda de 90 dias, fora do backup; acesso só do TI. Firewall registra conexões recusadas (QAS-12); o agente guarda só metadados. A auditoria ganha a sessão e o id da requisição (migração 0003), que entram no hash | RNF-624. O comportamento padrão de servidor web, banco e Python grava URL com busca, valor de chave duplicada e instruções com literais — todos com dado de paciente. A correlação por requisição e por sessão completa a rastreabilidade: da ação auditada às linhas técnicas da mesma requisição, e de um registro à linha do tempo da sessão |
| DD-82 | **Log binário do MySQL desligado.** O banco do SAR roda com `--disable-log-bin`; log geral e log de consultas lentas também desligados. `verificar_esquema.sh` confere as três configurações | Não há réplica, e o RPO é atendido pelo dump diário (QAS-04: 24 h) e pela cópia semanal (QAS-15: 7 dias); recuperação a um ponto no tempo não é requisito. A recuperação após queda do InnoDB usa o redo log, não o binlog. Ligado, o binlog guardaria cópia das linhas alteradas, com dado de paciente, inclusive de cadastro anulado (DEC-61), sem a proteção e o horizonte já definidos para o backup (DD-04). Se um dia houver réplica ou exigência de ponto no tempo, religar com cifragem do binlog e guarda curta, por nova decisão |

### 2.2 Alterações incorporadas ao DAS

Todas as linhas abaixo foram incorporadas na DAS_recepcao v1.1, de 06/10/2026.

| **Item do DAS** | **Alteração** | **Origem** |
|---|---|---|
| §4.1, §4.4 | Novo MOD-11 Atendimento ao titular; TitularService sai do MOD-01; pacote `sar/nucleo/` e `sar/composicao.py` | DD-02, DD-15, DD-20 |
| §4.1 | UsuarioService explícito no MOD-01 (UC-15) | §5 |
| §4.2 | Regra: módulo só importa o `contrato` de outro; dependências invertidas por portas | DD-02, DD-16 |
| §6.2 `documento` | Remove `reter_ate`; acrescenta metadados do Decreto 10.278 | DD-01, DD-11 |
| §6.2 `sessao_usuario` | Token só como hash; sem `expira_em` | DD-05, DD-19 |
| §6.2 `auditoria` | `antes`/`depois` substituídos por `alteracoes` em texto canônico; `origem`, `versao_formato`; novas tabelas `auditoria_cabeca` e `auditoria_corte` | DD-03, DD-10 |
| §6.2 `telefone` | Duas chaves estrangeiras com verificação | DD-06 |
| §6.2 `evento`, `periodo_tratamento` | Evento embutido no período; cobertura em tabela própria | DD-13, DD-14 |
| §6.2 `requisicao_titular` | Remove `prazo`; passa ao MOD-11 | DD-18, DD-20 |
| §6.2 `rascunho_cadastro` | Remove `expira_em` (derivado) | DD-01 aplicado |
| §6.2 `paciente` | Acrescenta `anulado_em`, `versao`; nova tabela `duplicidade_descartada` | §6 |
| — (ERS) | Incorporado antes da assinatura: RF-102, RF-103, RF-109, RF-1008, RF-1106, §3.2.13, RN-02, INV-01, INV-15 e RNF-601 (DEC-57 a DEC-63) | DD-21, DD-22, P-01 a P-06 |
| §4.1, §5.1, AD-12 | Sessão de turno derivada; sem job de abertura e sem job de lembrete. O worker continua necessário para os demais jobs | DD-23 |
| §6.2 `sessao_turno` | Sem `aberta_em`; linha criada na primeira marcação ou na confirmação; acrescenta `versao` | DD-23 |
| §6.2 `presenca` | Sem `incluida_pela_recepcao` (derivado da lista esperada); `situacao` presente/ausente | DD-24 |
| §6.2 `compensacao` | Substituída por `ligacao_manual`; sem `automatica` e sem `revertida_em` | DD-25 |
| §6.2 `mes_frequencia` | Substituída por `mes_alterado`, que registra cada alteração após o fechamento | DD-26 |
| §6.2 `alocacao` | Sem `vigencia_fim`; `escala_id` anulável; ligada ao período | DD-27 |
| §6.2 `troca_turno` | Substituída por `troca_pontual` e `extra_planejada`; nova `termo_extra` e `ciencia_enfermagem` | DD-28, RF-921 |
| R-38 | Reduzido: a falha de job deixa de afetar a sessão de turno; continua valendo para a verificação da cadeia e os demais jobs | DD-23 |
| §7 (implantação, operação) | Janela de disponibilidade 05:00–20:00; jobs e manutenção entre 20:00 e 05:00 | DD-32 |
| §6.2 `documento` | Acrescenta `nonce`, `local_digitalizacao`, `descartado_em`, `bloqueado_em`, `bloqueio_motivo`; id aleatório mantido | DD-11, DD-04, DD-38 |
| §6.2 `ingestao` | Acrescenta `vinculo`, `token_hash`, `hash_reconstruido`, `paginas`, `substitui_id`, `origem`, `campos_candidatos_cifrados`; estados da §8.4 | DD-05, DD-33, DD-36 |
| §4.5, AD-17 | Agente com servidor fixo na configuração, verificação de origem e acesso à rede local do navegador | DD-39 |
| §4.1, §4.2 | MOD-05 passa a depender também do MOD-04, para a foto do crachá | §9 |
| §4.1, §4.2 | MOD-07 deixa de depender de MOD-01 a MOD-04; recebe as fontes pela raiz de composição | DD-54 |
| §4.1 MOD-09, §7.4, §7.5 | Catálogo de jobs da §13.1; backup por agendamento do sistema operacional, registrado em `job_execucao`; trava exclusiva por job | DD-61, DD-62, DD-63 |
| §6.2 `job_execucao` | Acrescenta `itens`; `sucesso` vira `resultado` | DD-61 |
| SEG-14 (leitura), §6.3 | Usuários de banco por processo, com privilégio por tabela e coluna | DD-58 |
| §4.1 MOD-10 | Depende de MOD-02, MOD-06 e MOD-08; deixa de depender do MOD-03, porque a carga não aloca | §14 |
| §6.2 | Novas tabelas `carga_lote`, `carga_linha`, `carga_conferencia` | DD-66, DD-69 |
| §6 inteira | Substituída pela referência ao esquema implementado (§12.4 do DDS) | DD-70 a DD-72 |
| §4.1 coluna "Depende de", §4.2 | Substituídas pelo grafo da §3.12 do DDS e pelos contratos do `.importlinter` | DD-16, DD-73 |
| §4.1 MOD-01 | Pedidos de titular saem para o MOD-11 | DD-20 |
| AD-21, AD-24 | Documentos por modelo .docx preenchido (docxtpl) e convertido em PDF por serviço com LibreOffice em contêiner próprio, sem rede; WeasyPrint permanece para os relatórios | DD-42 |
| §6.2 | Nova tabela `modelo_documento` | DD-42 |
| §6.2 `emissao_documento` | Acrescenta `referencia` (troca ou competência); sem texto livre | DD-43 |
| §6.2 `estabelecimento`, `periodo_tratamento` | Tabela `estabelecimento` e coluna `estabelecimento_id` removidas; RF-303 retirado da ERS | DEC-73 |
| AD-17, R-34 | Agente validado no equipamento real (Brother DCP-1610NW, WIA, vidro e alimentador); conversão para PNG no agente; envio por página; R-34 mitigado | DD-77 a DD-80 |
| §6.3 | Exclusão física proibida antes do prazo; descarte após o prazo por destruição da chave | DD-04 |
| §7.4 | Horizonte de retenção do restic | DD-04 |

---

## 3. Convenções transversais

### 3.1 Estrutura interna de cada módulo

| **Arquivo** | **Conteúdo** | **Quem pode importar** |
|---|---|---|
| `contrato.py` | Serviços públicos, objetos de transferência (dataclasses imutáveis), erros, portas | Qualquer módulo autorizado pelo DAS §4.2 |
| `servicos.py` | Implementação dos serviços | Só o próprio módulo e a raiz de composição |
| `regras.py` | Funções puras de domínio | Só o próprio módulo |
| `executores.py` | Implementações de portas de outros módulos | Só a raiz de composição |

Rotas web (`sar/web/`) chamam apenas `contrato`. Modelos ORM ficam em
`sar/modulo_08_dados/modelos/<modulo>.py`.

### 3.2 Contexto da requisição

Todo serviço público recebe como primeiro argumento um `Contexto` imutável: `usuario_id`, `perfil`,
`sessao_id`, `origem` (endereço da estação) e `instante`. O worker usa o contexto `SISTEMA`, com
permissões próprias na matriz. Nenhum serviço lê estado global do Flask.

### 3.3 Unidade de trabalho e transação

- A unidade de trabalho (MOD-08) é aberta pelo serviço público e fechada por ele: uma operação de
  negócio, uma transação.
- O AuditService acumula os registros durante a operação e os grava no fechamento, na mesma transação
  (DD-03). Falha na auditoria desfaz a operação.
- Eventos de domínio são despachados antes do commit, dentro da mesma transação (DD-15).
- Leituras auditadas também abrem transação, para gravar o registro de leitura.

### 3.4 Portas e registros

Assinaturas completas em `sar/nucleo/portas.py`, `sar/nucleo/parametros.py` e `sar/nucleo/uow.py`.

| **Porta** | **Definida em** | **Implementada por** | **Uso** |
|---|---|---|---|
| `UnidadeDeTrabalho` | Núcleo | MOD-08 | Transação por operação, eventos, auditoria, ações depois do commit (§3.3) |
| `Relogio` | Núcleo | MOD-08 (real) e testes (controlado) | Instante UTC e data local (§3.7) |
| `Cifra` | Núcleo | MOD-08 | AES-256-GCM por finalidade (DD-07) |
| `LeitorParametros` | Núcleo | MOD-06 | Valor vigente de cada parâmetro declarado (DD-48, DD-73) |
| `ExecutorAutorizavel` | Núcleo, usada pelo MOD-01 | MOD-02, MOD-03, MOD-04 | Executa a operação aprovada (DEC-42) |
| `VerificadorImpedimento` | Núcleo, usada pelo MOD-02 | MOD-03, MOD-04 | Impedimentos e efeitos automáticos do encerramento de período (§7.8, DD-31) |
| `ParticipanteAnulacao` | Núcleo, usada pelo MOD-02 | MOD-03, MOD-04 | Impacto e descarte na anulação (§6.9) |
| `FonteMarcoRetencao` | Núcleo, usada pelo MOD-04 | MOD-02 | Marco da retenção (DD-01) |
| `ProvedorCep` | Núcleo, usada pelo MOD-02 | Adaptadores ViaCEP e alternativo | Strategy (AD-23) |
| `FontePendencia` | Núcleo, usada pelo MOD-07 | MOD-01 a MOD-04, MOD-09, MOD-11 | Pendências por perfil (DD-54) |

As portas ficam no núcleo, e não no módulo consumidor, para que o provedor não precise importar o
consumidor: o MOD-04 implementa `ParticipanteAnulacao` sem depender do MOD-02.

### 3.5 Erros

Hierarquia única no núcleo, documentada em cada contrato:

| **Erro** | **Significado** | **Resposta na tela** |
|---|---|---|
| `AcessoNegado` | Perfil ou recurso sem permissão | Mensagem genérica; registrado |
| `NaoEncontrado` | Identificador inexistente ou anulado | Mensagem genérica |
| `RegraViolada(codigo, detalhe)` | Invariante de bloqueio (INV-xx) | Mensagem de negócio específica |
| `ConfirmacaoNecessaria(codigo, dados)` | Alerta que exige decisão explícita (tríade) | Tela de confirmação |
| `ConflitoDeVersao(quem, quando)` | Concorrência otimista (DD-17) | Pede recarga |
| `RequerAutorizacao(tipo)` | Operação sujeita à DEC-42 | Oferece abrir solicitação |
| `IntegridadeViolada` | Hash do documento não confere na leitura (DD-38) | Mensagem de documento indisponível; aviso de integridade aberto |
| `IndisponivelExterno` | CEP ou outro serviço externo | Segue sem o recurso (RNF-507) |

### 3.6 Identificadores

Chave primária inteira sequencial nas tabelas internas. Identificador aleatório onde o id aparece em
URL de recurso sensível: documento (já no DAS) e solicitação de autorização. Identificador aleatório
nunca substitui a verificação de permissão (RNF-623).

### 3.7 Tempo

- Relógio injetável (`Relogio`) no núcleo; os testes controlam o tempo.
- Instantes em UTC, `DATETIME(6)`; datas de calendário em data local da clínica.
- Conversões só na borda: rotas e emissão de documentos.

### 3.8 Validação

Validação de formato na borda (formulário); validação de regra no serviço; invariantes estruturais
no banco. As três camadas são deliberadas: a tela ajuda, o serviço decide, o banco garante.

### 3.9 Cifragem

Ver DD-07. A chave mestra é lida de segredo montado no contêiner, nunca de variável de ambiente
registrada em log nem do banco.

### 3.10 Formato canônico da cadeia de auditoria

1. Campos, na ordem lógica: `id`, `instante`, `usuario_id`, `autorizador_id`, `operacao`,
   `entidade`, `entidade_id`, `alteracoes`, `motivo`, `origem`, `sessao_id`, `requisicao_id`,
   `versao_formato` (os dois antes da versão foram acrescentados pela DD-81, antes de qualquer registro em
   produção; o formato continua sendo a versão 1).
2. Serialização JSON com chaves ordenadas, separadores `,` e `:` sem espaço, UTF-8 sem escape de
   caracteres não ASCII.
3. Instante em ISO 8601 UTC com microssegundos e sufixo `Z`; truncado a microssegundos antes do hash
   e gravado em `DATETIME(6)`.
4. Datas como `AAAA-MM-DD`; decimais como texto; nulo como `null`; bytes proibidos.
5. `hash_registro = SHA-256(hash_anterior + "\n" + json)`, em hexadecimal. O primeiro elo usa 64
   zeros; o primeiro elo após um expurgo usa o hash registrado no ponto de corte (RNF-628).
6. `alteracoes` é gravado como **texto**, exatamente como serializado. Coluna JSON do MySQL
   normaliza o conteúdo e impediria recalcular o mesmo hash.
7. `versao_formato = 1`. Mudança de formato cria nova versão; a verificação conhece todas.

### 3.11 Eventos de domínio

Definidos em `sar/nucleo/eventos.py`. Só existe evento com consumidor, e evento carrega só
identificadores, datas e códigos, nunca dado pessoal (DD-74).

| **Evento** | **Publicado por** | **Consumido por** |
|---|---|---|
| `UsuarioInativado` | MOD-01 | MOD-01: encerra as sessões do usuário |
| `CadeiaDivergente` | MOD-01 | MOD-01: abre o aviso de integridade (DEC-43) |
| `DocumentoIncorporado` | MOD-04 | MOD-02: liga o comprovante ao evento (§6.5); MOD-03: liga o termo à troca ou à competência (RF-809) |
| `DocumentoRevinculado` | MOD-04 | MOD-02 e MOD-03: desfazem vínculos que não pertencem mais ao paciente |

### 3.12 Grafo de dependências

| **Módulo** | **Depende de** | **Mudança em relação ao DAS §4.1** |
|---|---|---|
| Núcleo | — | Novo (DD-02, DD-15, DD-73) |
| MOD-01 | MOD-08 | Parâmetros pelo núcleo |
| MOD-02 | MOD-01, MOD-06, MOD-08 | — |
| MOD-03 | MOD-01, MOD-02, MOD-08 | — (parâmetros de preparação e confirmação pelo núcleo, DD-73) |
| MOD-04 | MOD-01, MOD-06, MOD-08 | — |
| MOD-05 | MOD-01, MOD-02, MOD-03, MOD-04, MOD-06, MOD-08 | Acrescenta MOD-04 (foto) e MOD-08 |
| MOD-06 | MOD-01, MOD-08 | — |
| MOD-07 | MOD-01, MOD-08 | Fontes pela raiz de composição (DD-54) |
| MOD-08 | Núcleo e MySQL | — |
| MOD-09 | MOD-01, MOD-02, MOD-04, MOD-08 | — |
| MOD-10 | MOD-01, MOD-02, MOD-06, MOD-08 | Sem MOD-03 (a carga não aloca) |
| MOD-11 | MOD-01, MOD-02, MOD-04, MOD-05, MOD-08 | Novo (DD-20) |
| Web | `contrato` de qualquer módulo | Nunca MOD-08 |
| Raiz de composição | Todos | Nova (DD-02) |

Todo módulo depende do núcleo. As regras são verificadas pelo `import-linter` no pipeline, com 25
contratos no arquivo `.importlinter` (DD-16): o grafo acima; fora de cada módulo, só o seu `contrato`
pode ser importado; só o MOD-08 importa o driver do banco; só o cliente de CEP importa a biblioteca de
HTTP. Testado num esqueleto do pacote: com o grafo respeitado, os 25 contratos se mantêm; com quatro
violações inseridas de propósito, cinco contratos quebram.

---

## 4. Catálogo de operações e matriz de permissões

Cada operação é um identificador único usado pelo PermissionGuard (AD-20). Perfis: **R**ecepção,
**A**dministração, **V**isualizador, **T**I, **E**nfermagem; **S** = contexto de sistema (worker).
"Aut." indica operação executada só por autorização da administração (DEC-42): o perfil marcado
solicita; a administração aprova. Quando quem solicita é a própria administração, a aprovação é
automática (§5.3).

### 4.1 MOD-01 Acesso e auditoria

| **Operação** | **R** | **A** | **V** | **T** | **E** | **S** | **Auditada** |
|---|---|---|---|---|---|---|---|
| `acesso.sessao.entrar` / `sair` | ✓ | ✓ | ✓ | ✓ | ✓ | — | Sim, inclusive falhas |
| `acesso.senha.trocar_propria` | ✓ | ✓ | ✓ | ✓ | ✓ | — | Sim, sem valores |
| `acesso.usuario.consultar` | — | — | — | ✓ | — | — | Não |
| `acesso.usuario.criar` / `alterar_perfil` / `inativar` / `reativar` | — | — | — | ✓ | — | — | Sim |
| `acesso.usuario.redefinir_senha` | — | — | — | ✓ | — | — | Sim; senha provisória, troca obrigatória |
| `acesso.usuario.registrar_termo_ciencia` | — | — | — | ✓ | — | — | Sim (DEC-47) |
| `acesso.auditoria.consultar` | — | ✓ | — | ✓ pseudonimizado | — | — | Sim (RNF-625) |
| `acesso.cadeia.verificar` | — | — | — | ✓ | — | ✓ | Sim |
| `acesso.aviso_integridade.ver` | — | ✓ simples | — | ✓ diagnóstico | — | — | Sim |
| `acesso.aviso_integridade.encerrar` | — | ✓ | — | — | — | — | Sim (DEC-43) |
| `acesso.ancora.registrar_anotacao` | — | ✓ | — | — | — | — | Sim |
| `acesso.autorizacao.solicitar` | ✓ | ✓ | — | — | ✓ | — | Sim |
| `acesso.autorizacao.decidir` | — | ✓ | — | — | — | — | Sim, com as duas identidades |
| `acesso.autorizacao.cancelar_propria` | ✓ | ✓ | — | — | ✓ | — | Sim |

### 4.2 MOD-02 Cadastro

| **Operação** | **R** | **A** | **V** | **T** | **E** | **S** | **Auditada** |
|---|---|---|---|---|---|---|---|
| `cadastro.paciente.buscar` | ✓ | ✓ | ✓ | — | ✓ | — | Sim, só a quantidade (DD-10) |
| `cadastro.paciente.ver_identificacao` | ✓ | ✓ | ✓ | — | ✓ | — | Sim |
| `cadastro.paciente.ver_ficha` | ✓ | ✓ | ✓ | — | — | — | Sim (DEC-55) |
| `cadastro.paciente.criar` | ✓ | ✓ | — | — | — | — | Sim |
| `cadastro.paciente.atualizar` | ✓ | ✓ | — | — | — | — | Sim |
| `cadastro.paciente.descartar_duplicidade` | ✓ | ✓ | — | — | — | — | Sim (INV-08) |
| `cadastro.paciente.anular` | Aut. | Aut. | — | — | — | — | Sim (RF-1008) |
| `cadastro.contato.gerir` / `cadastro.telefone.gerir` | ✓ | ✓ | — | — | — | — | Sim |
| `cadastro.periodo.abrir` (retorno) | ✓ | ✓ | — | — | — | — | Sim (RF-605) |
| `cadastro.cobertura.registrar` | ✓ | ✓ | — | — | — | — | Sim |
| `cadastro.evento.registrar` | ✓ | ✓ | — | — | — | — | Sim |
| `cadastro.evento.corrigir` / `remover` | Aut. | Aut. | — | — | — | — | Sim (RF-606) |
| `cadastro.rascunho.salvar` / `retomar` / `descartar` | ✓ próprio | ✓ próprio | — | — | — | — | Sim, sem conteúdo |
| `cadastro.rascunho.descartar_expirados` | — | — | — | — | — | ✓ | Sim |
| `cadastro.cep.consultar` | ✓ | ✓ | — | — | — | — | Não (só o CEP sai) |

Regras de recurso, além do perfil: o perfil TI nunca recebe dado de paciente (RF-1004); rascunho só
pelo próprio autor; paciente anulado não aparece em nenhuma operação de consulta.

### 4.3 MOD-03 Operação

Alocação, trocas e extras são da enfermagem (RF-406, DEC-48); lançamento e confirmação de frequência
são da recepção. A administração tem "tudo da recepção" (§1.5 da ERS), não as operações da
enfermagem.

| **Operação** | **R** | **A** | **V** | **T** | **E** | **S** | **Auditada** |
|---|---|---|---|---|---|---|---|
| `operacao.escala.consultar` (ocupação, RF-404) | ✓ | ✓ | ✓ | — | ✓ | — | Não |
| `operacao.alocacao.registrar` / `registrar_em_lote` (RF-402, RF-405) | — | — | — | — | ✓ | — | Sim |
| `operacao.alocacao.registrar_retroativa` (alcança sessão confirmada) | — | — | — | — | Aut. | — | Sim (§7.13 do modelo) |
| `operacao.troca.registrar` / `cancelar` | — | — | — | — | ✓ | — | Sim |
| `operacao.troca.cancelar_realizada` (alcança sessão confirmada) | — | — | — | — | Aut. | — | Sim |
| `operacao.extra.registrar` / `cancelar` | — | — | — | — | ✓ | — | Sim |
| `operacao.sessao.ver` | ✓ | ✓ | ✓ | — | ✓ | — | Não |
| `operacao.sessao.preparar` — próximo turno com pendências (RF-922) | ✓ | ✓ | — | — | ✓ | — | Não; as pendências seguem o perfil |
| `operacao.frequencia.marcar_ausencia` / `acrescentar_paciente` | ✓ | ✓ | — | — | — | — | Sim |
| `operacao.sessao.confirmar` | ✓ | ✓ | — | — | — | — | Sim |
| `operacao.sessao.registrar_nao_realizada` (P-12) | — | ✓ | — | — | — | — | Sim, com motivo |
| `operacao.sessao.reabrir` | Aut. | Aut. | — | — | — | — | Sim (RF-1008) |
| `operacao.presenca.alterar_confirmada` | Aut. | Aut. | — | — | — | — | Sim (RF-1008) |
| `operacao.pareamento.refazer` — mês aberto | ✓ | ✓ | — | — | — | — | Sim |
| `operacao.pareamento.refazer` — mês fechado | Aut. | Aut. | — | — | — | — | Sim, com marca (RF-915) |
| `operacao.presenca.dar_ciencia` (RF-921) | — | — | — | — | ✓ | — | Sim |
| `operacao.balanco.consultar` (RF-916) | ✓ | ✓ | ✓ | — | ✓ | — | Sim |

### 4.4 MOD-04 Documentos

Enfermagem não acessa documentos (DEC-55); TI nunca vê conteúdo nem metadado de documento de paciente
(RF-1004, RNF-625).

| **Operação** | **R** | **A** | **V** | **T** | **E** | **S** | **Auditada** |
|---|---|---|---|---|---|---|---|
| `documento.ingestao.abrir` / `conferir` / `incorporar` / `rejeitar` (scanner e webcam) | ✓ | ✓ | — | — | — | — | Sim |
| `documento.nova_versao` (RF-708) | ✓ | ✓ | — | — | — | — | Sim, com motivo |
| `documento.listar` (metadados, RNF-626) | ✓ | ✓ | ✓ | — | — | — | Sim |
| `documento.ver` (na aplicação, SEG-19) | ✓ | ✓ | ✓ | — | — | — | Sim (RNF-606) |
| `documento.baixar` (P-17, resolvido) | — | ✓ | — | — | — | — | Sim |
| `documento.revincular` (RF-713) | ✓ | ✓ | — | — | — | — | Sim, com motivo |
| `documento.descartar_fim_retencao` (DD-04) | — | Aut. | — | — | — | — | Sim |
| `documento.desbloquear` (após rescan, P-19) | — | Aut. | — | — | — | — | Sim |
| `documento.integridade.verificar` / `rescan` | — | — | — | ✓ | — | ✓ | Sim, só identificadores |
| `documento.ingestao.processar` / `expirar` / `varrer_orfaos` | — | — | — | — | — | ✓ | Sim |

### 4.5 MOD-05 Emissão e relatórios

Relatórios por perfil conforme P-20 (resolvido). Exportação é da administração (§1.5 da ERS).

| **Operação** | **R** | **A** | **V** | **T** | **E** | **S** | **Auditada** |
|---|---|---|---|---|---|---|---|
| `emissao.documento.emitir` (DOC-01 a DOC-07) | ✓ | ✓ | — | — | — | — | Sim |
| `emissao.cracha.emitir` | ✓ | ✓ | — | — | — | — | Sim |
| `emissao.modelo.enviar` / `ativar` / `reverter` (P-22) | — | ✓ | — | — | — | — | Sim, com hash do modelo |
| `relatorio.operacional.ver` (RF-906, 908, 916; prévia) | ✓ | ✓ | ✓ | — | ✓ | — | Sim |
| `relatorio.gerencial.ver` (RF-902 a 905, 910, 911) | — | ✓ | ✓ | — | — | — | Sim |
| `relatorio.aniversariantes.ver` (RF-909) | ✓ | ✓ | — | — | — | — | Não |
| `relatorio.exportar` (PDF e XLSX) | — | ✓ | — | — | — | — | Sim, com filtros (RNF-607) |

### 4.6 MOD-06 Configuração

| **Operação** | **R** | **A** | **V** | **T** | **E** | **S** | **Auditada** |
|---|---|---|---|---|---|---|---|
| `config.parametro.alterar` — operacionais (§10.1) | — | ✓ | — | — | — | — | Sim, antes e depois |
| `config.parametro.alterar` — técnicos (§10.1) | — | — | — | ✓ | — | — | Sim, antes e depois |
| `config.institucional.alterar` / `logotipo.enviar` (RF-1201, RF-1202) | — | ✓ | — | — | — | — | Sim |
| `config.convenio.gerir` (RF-1204) | — | ✓ | — | — | — | — | Sim |
| `config.consultar` (listas de referência) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | Não |
| `config.municipio.incluir` (RF-1205) | — | — | — | ✓ | — | — | Sim |
| Faixas etárias, tipos de documento, escalas | — | — | — | — | — | — | Só por migração, em nova versão |

### 4.7 MOD-07 Pendências

| **Operação** | **R** | **A** | **V** | **T** | **E** | **S** | **Auditada** |
|---|---|---|---|---|---|---|---|
| `pendencia.ver` — cada perfil vê só as linhas dele (§11.1) | ✓ | ✓ | ✓ | ✓ | ✓ | — | Não; o detalhe de cada item segue a auditoria do módulo dono |

### 4.8 MOD-08 Dados e MOD-09 Agendamento

| **Operação** | **R** | **A** | **V** | **T** | **E** | **S** | **Auditada** |
|---|---|---|---|---|---|---|---|
| `agendamento.execucoes.ver` | — | — | — | ✓ | — | — | Não |
| `agendamento.job.executar_agora` — só jobs marcados como seguros na §13.1 | — | — | — | ✓ | — | — | Sim |
| `agendamento.backup.registrar` (linha de comando do servidor) | — | — | — | — | — | ✓ | Sim |

O MOD-08 não tem operação de usuário: é infraestrutura usada pelos demais módulos.

### 4.9 MOD-10 Carga inicial

| **Operação** | **R** | **A** | **V** | **T** | **E** | **S** | **Auditada** |
|---|---|---|---|---|---|---|---|
| `carga.simular` / `carga.efetivar` (linha de comando, só contagens) | — | — | — | ✓ | — | — | Sim |
| `carga.excecoes.ver` (RF-1106) | ✓ | ✓ | — | — | — | — | Sim |
| `carga.conferencia.registrar` (conferência amostral) | ✓ | ✓ | — | — | — | — | Sim |
| `carga.aceitar` | — | ✓ | — | — | — | — | Sim |

### 4.10 MOD-11 Atendimento ao titular

| **Operação** | **R** | **A** | **V** | **T** | **E** | **S** | **Auditada** |
|---|---|---|---|---|---|---|---|
| `titular.requisicao.registrar` | ✓ | ✓ | — | — | — | — | Sim |
| `titular.requisicao.consultar` | ✓ | ✓ | ✓ | — | — | — | Sim |
| `titular.requisicao.atender` / `negar` | — | ✓ | — | — | — | — | Sim |
| `titular.copia.gerar` | — | ✓ | — | — | — | — | Sim, com registro da entrega |

---

## 5. MOD-01 — Acesso e auditoria

### 5.1 Agregados

| **Agregado** | **Raiz e partes** | **Invariantes e regras** |
|---|---|---|
| Usuário | Usuário | Login único. Nunca excluído (RF-1005). Inativo não autentica. Sem termo de ciência, não acessa (DEC-47). Senha provisória obriga troca no primeiro acesso |
| Sessão de usuário | Sessão | Token só como hash (DD-05). Uma sessão ativa por usuário (P-02): novo login encerra a anterior, e a estação que perdeu a sessão exibe o aviso de que houve entrada em outro lugar. Encerrada também por saída, inatividade, limite absoluto ou inativação do usuário |
| Trilha de auditoria | Registro, cabeça da cadeia, âncora, ponto de corte | Só inserção pela aplicação. Um elo por registro, em ordem (DD-03) |
| Aviso de integridade | Aviso | Encerrado só pela administração, com explicação (DEC-43) |
| Solicitação de autorização | Solicitação | Máquina de estados abaixo. Autor e autorizador em campos distintos (QAS-10) |

### 5.2 Autenticação e bloqueio progressivo

1. Login inexistente executa a verificação contra um hash fictício, para que o tempo de resposta não
   revele quais logins existem.
2. A mensagem de falha é sempre a mesma; o motivo real vai só para a auditoria.
3. Após N falhas consecutivas, bloqueio por um prazo que dobra a cada nova falha, até um teto.
   Parâmetros no MOD-06, com padrão de 5 tentativas, 5 minutos e teto de 60 minutos.
4. Senha: mínimo de 10 e máximo de 64 caracteres, sem regra de composição, recusada se constar de
   lista local de senhas comuns. O máximo respeita o limite de 72 bytes do bcrypt.
5. Login bem-sucedido zera o contador, cria sessão com identificador novo e registra a auditoria.

### 5.3 Máquina de estados da solicitação de autorização

| **Estado** | **Transição** | **Próximo** |
|---|---|---|
| Pendente | Administração aprova e a versão do alvo não mudou → executa | Executada |
| Pendente | Administração aprova, mas o alvo mudou desde o pedido | Invalidada |
| Pendente | Administração recusa, com motivo | Recusada |
| Pendente | Solicitante cancela | Cancelada |

Executada, Invalidada, Recusada e Cancelada são finais. A aprovação executa pela porta
`ExecutorAutorizavel` (DD-02), na mesma transação da mudança de estado e da auditoria.

**Confirmação automática (P-01).** Quando o solicitante tem perfil de administração, a solicitação
nasce e é aprovada na mesma operação: não entra na fila nem gera pendência. O motivo continua
obrigatório, a verificação de versão do alvo é dispensada, porque não há intervalo entre pedido e
execução, e a auditoria registra o mesmo usuário como autor e autorizador. A solicitação é gravada no
estado Executada, para que toda operação sujeita à DEC-42 tenha registro na mesma tabela,
independentemente de quem a pediu.

### 5.4 Contratos públicos

| **Serviço.método** | **Entrada** | **Saída** | **Erros** |
|---|---|---|---|
| `AuthService.entrar` | login, senha, origem | token da sessão e Contexto | `CredencialInvalida` (genérico), `TermoPendente`, `TrocaDeSenhaExigida` |
| `AuthService.sair` | Contexto | — | — |
| `SessionManager.validar` | token, automática: bool | Contexto | `SessaoEncerrada` |
| `PermissionGuard.pode` | Contexto, operação, recurso opcional | bool | — |
| `PermissionGuard.exigir` | Contexto, operação, recurso opcional | — | `AcessoNegado` |
| `AuditService.registrar` | unidade de trabalho, Contexto, operação, entidade, id, alterações, motivo, autorizador opcional | — | Propaga falha: a operação é desfeita |
| `AuditService.verificar_cadeia` | Contexto (T ou S) | resultado com primeiro divergente, se houver | — |
| `AutorizacaoService.solicitar` | Contexto, tipo, entidade_id, parâmetros, motivo | id da solicitação | `AcessoNegado`, `RegraViolada` |
| `AutorizacaoService.aprovar` / `recusar` | Contexto (A), id, motivo | estado final | `AcessoNegado`, `RegraViolada` |
| `AutorizacaoService.registrar_executor` | executor | — | Uso só na raiz de composição |
| `UsuarioService.criar` / `alterar_perfil` / `inativar` / `reativar` / `redefinir_senha` / `registrar_termo` | Contexto (T), dados | — | `AcessoNegado`, `RegraViolada`, `ConflitoDeVersao` |

### 5.5 Eventos de domínio publicados

`UsuarioInativado` (encerra as sessões dele), `CadeiaDivergente` (cria o aviso de integridade).

### 5.6 Permissões no banco

| **Usuário do banco** | **Tabelas de auditoria** |
|---|---|
| Aplicação | `INSERT` e `SELECT` em `auditoria`; `SELECT` e `UPDATE` em `auditoria_cabeca`; `INSERT` e `SELECT` em `auditoria_ancora` |
| Expurgo | `DELETE` em `auditoria`; `INSERT` em `auditoria_corte`; `SELECT` nas três |
| Migração | Estrutura, usado só na implantação |

---

## 6. MOD-02 — Cadastro

### 6.1 Agregados

| **Agregado** | **Raiz e partes** | **Por que juntos** |
|---|---|---|
| Paciente | Paciente; contatos e seus telefones; telefones do paciente; períodos de tratamento, cada um com coberturas e evento | INV-02, INV-09 e INV-12 envolvem as partes; com o volume da clínica, carregar o agregado inteiro é trivial |
| Rascunho de cadastro | Rascunho | Ciclo de vida próprio; o paciente ainda não existe |
| Duplicidade descartada | Par de pacientes, quem decidiu e quando | Decisão que encerra a pendência de tríade |

### 6.2 Regras

| **Regra** | **Tipo** | **Onde** |
|---|---|---|
| Mínimo para criar o paciente: nome, data de início do tratamento e número de prontuário (P-03). Sem os três, o preenchimento só pode ser salvo como rascunho | Bloqueio | Serviço e tela |
| Com o mínimo, o paciente é criado com período aberto; todo outro campo faltante gera pendência nomeada (RF-102, UC-01 A1) | Sinalização | Regra pura |
| Sem nome, data de nascimento ou nome da mãe, a verificação da tríade não roda; ela roda quando os três estiverem preenchidos, inclusive numa atualização | Alerta adiado | Serviço |
| Prontuário único, quando informado (INV-07) | Bloqueio | Banco |
| CPF ou CNS com dígito verificador inválido não salva (DD-22). Campo ausente é permitido e vira pendência | Bloqueio | Regra pura, chamada pelo serviço; conferência imediata na tela |
| CPF e CNS únicos, quando informados (P-04). A recusa informa o paciente que já usa o número, como no prontuário | Bloqueio | Banco |
| Tríade coincidente, comparada sem acento, sem caixa e sem espaços repetidos (INV-08) | Alerta com confirmação | Serviço |
| Residência só em município de Goiás; naturalidade nacional | Bloqueio | Serviço, pelo contrato do MOD-06 |
| Um período aberto por vez (INV-02) | Bloqueio | Banco (§6.4) |
| Evento: período aberto, data não anterior ao início, não futura, paciente não falecido | Bloqueio | Serviço |
| Nenhum fato datado após o óbito (INV-01, alcance da DD-21) | Bloqueio | Serviço, e MOD-03 pelo contrato `data_obito` |
| Encerrar período com fatos posteriores à data do evento em outros módulos | Bloqueio, com a lista de impedimentos | Porta `VerificadorImpedimento` |
| Coberturas de um período sem sobreposição (INV-09) | Bloqueio | Serviço, com trava do agregado |
| Anulação aprovada trata automaticamente tudo o que está vinculado ao cadastro (P-06, §6.9) | Cascata | Porta `ParticipanteAnulacao` |

Derivados, nunca gravados: idade, situação do paciente, pendências de cadastro,
pendência de evento sem comprovante e prazo de descarte do rascunho.

### 6.3 Situação do paciente (derivada)

| **Situação** | **Condição** |
|---|---|
| Em cadastro | Nenhum período. Não ocorre na criação pela tela, que exige a data de início (P-03); pode ocorrer na carga inicial |
| Sem alocação | Período aberto e nenhuma alocação vigente (consulta ao MOD-03) |
| Ativo | Período aberto e alocação vigente |
| Inativo | Último período encerrado por alta, transferência, transplante ou desistência |
| Falecido | Período encerrado por óbito |

### 6.4 Pontos do esquema físico decididos aqui

```sql
-- INV-02: no máximo um período aberto por paciente
aberto TINYINT GENERATED ALWAYS AS (IF(evento_tipo IS NULL, 1, NULL)) STORED,
UNIQUE KEY uq_periodo_aberto (paciente_id, aberto)

-- INV-12: exatamente um dono por telefone (DD-06, sem cláusulas ON DELETE/ON UPDATE)
CHECK ((paciente_id IS NULL) <> (contato_id IS NULL))
```

Índices únicos em `prontuario`, `cpf` e `cns`; todos admitem vários nulos. Busca por nome sem distinção
de acento e de caixa pela collation `utf8mb4_0900_ai_ci`. CPF, CNS e CEP
gravados só com dígitos.

### 6.5 Comprovante do evento

1. A recepcionista inicia a digitalização a partir do evento pendente. A ingestão é aberta com um
   vínculo opaco que o MOD-04 guarda sem interpretar.
2. Ao incorporar o documento, o MOD-04 publica `DocumentoIncorporado` com o paciente, o tipo e o
   vínculo.
3. O manipulador do MOD-02 confere se o tipo é o exigido para aquele evento (tabela fixa da DEC-53,
   no núcleo, junto aos tipos fixos da DEC-41) e grava o documento no evento. A pendência se encerra
   por derivação.

### 6.6 Rascunho

O rascunho é o único destino de um preenchimento sem o mínimo da P-03: a tela não oferece "salvar
paciente" enquanto faltar nome, data de início ou prontuário. Com o mínimo, a tela oferece as duas
ações, salvar paciente e salvar rascunho, e a escolha é do usuário. No rascunho não há verificação de
prontuário, CPF ou CNS repetidos, de dígito do CPF e do CNS nem de tríade; todas rodam quando o rascunho vira
paciente.

Um por usuário. Salvo automaticamente pelo htmx ao alterar campos, cifrado com a finalidade
`rascunhos` e o id do rascunho como dado associado (DD-07). Ao salvar o cadastro, o rascunho é
eliminado na mesma transação. O job diário avisa e depois elimina os que passaram do prazo (RF-920).

### 6.7 Contratos públicos

**Para a interface**

| **Serviço.método** | **Entrada** | **Saída** | **Erros** |
|---|---|---|---|
| `PacienteService.criar` | Contexto, dados, confirmar_duplicidade: bool | id | `RegraViolada` (mínimo da P-03, INV-07, CPF ou CNS inválido ou repetido), `ConfirmacaoNecessaria(triade, candidatos)` |
| `PacienteService.atualizar` | Contexto, id, versão, dados | nova versão | `ConflitoDeVersao`, `RegraViolada` (INV-07, CPF ou CNS inválido ou repetido) |
| `PacienteService.buscar` | Contexto, termo | lista de identificações | `AcessoNegado` |
| `PacienteService.ver_ficha` | Contexto, id | ficha completa | `AcessoNegado`, `NaoEncontrado` |
| `PacienteService.abrir_periodo` | Contexto, id, início, cobertura | id do período | `RegraViolada` (INV-01, INV-02) |
| `PacienteService.registrar_cobertura` | Contexto, período, dados, início | — | `RegraViolada` (INV-09) |
| `EventoService.registrar` | Contexto, paciente, tipo, data, local | — | `RegraViolada` com impedimentos |
| `RascunhoService.salvar` / `retomar` / `descartar` | Contexto, conteúdo | — / conteúdo / — | `AcessoNegado` |

**Para outros módulos (somente leitura)**

| **Método** | **Saída** | **Usado por** |
|---|---|---|
| `identificacao(paciente_id)` | nome, prontuário, nascimento, nome da mãe | MOD-03, MOD-05, conferência da ingestão (via rota) |
| `periodo_aberto_em(paciente_id, data)` | referência do período ou nulo | MOD-03 (INV-03, INV-04) |
| `data_obito(paciente_id)` | data ou nulo | MOD-03 (INV-01, DD-21) |
| `pacientes_com_periodo_aberto_em(data)` | ids | MOD-03 (abertura de sessões) |
| `pendencias_cadastro()` | lista | MOD-07 |

**Executores registrados no MOD-01:** `cadastro.evento.corrigir`, `cadastro.evento.remover`,
`cadastro.paciente.anular`. Implementa `FonteMarcoRetencao` para o MOD-04.

### 6.8 Eventos de domínio

Consome `DocumentoIncorporado` e `DocumentoRevinculado` (§3.11). Os efeitos do encerramento de período e da
anulação em outros módulos passam pelas portas `VerificadorImpedimento` e `ParticipanteAnulacao` (DD-74).

### 6.9 Anulação de cadastro criado por engano (RF-1008)

A recepção ou a administração solicita a anulação, com motivo. Na aprovação — automática se o
solicitante for da administração (P-01) —, tudo o que está vinculado ao cadastro é descartado na
mesma transação, sem preparo manual:

| **Módulo** | **Tratamento** |
|---|---|
| MOD-04 Documentos | Descartados por destruição da chave (DD-04), com registro |
| MOD-03 Operação | Presenças, alocações e trocas removidas, com registro |
| MOD-02 Cadastro | Paciente anulado; deixa de aparecer em busca, escala, relatório e pendência |

Não há transferência para outro paciente. A duplicata é barrada na origem pelo prontuário obrigatório
e único (P-03, INV-07), pelo CPF único (P-04) e pelo alerta da tríade (INV-08).

A tela de decisão mostra à administração, antes da aprovação, quantos documentos, presenças e
alocações serão descartados, e se há sessão confirmada entre elas. Presença removida de sessão já
confirmada marca o mês como alterado após o fechamento, quando for o caso (RF-915). O descarte de
documento na anulação não fere a INV-13: a retenção de vinte anos protege o prontuário de um paciente,
e o papel continua sendo o registro de origem (DEC-04).

---

## 7. MOD-03 — Operação

### 7.1 Agregados

| **Agregado** | **Raiz e partes** | **Invariantes e regras** |
|---|---|---|
| Escala | Tabela fixa: código, turno, dias da semana, horário de início e de fim (DEC-52). Na interface da recepção, o turno aparece como primeiro, segundo ou terceiro (DD-75). Turno 1: 06:00–10:00; turno 2: 11:00–15:00; turno 3: 16:00–20:00 (P-14) | Carregada por migração; nunca alterada pela aplicação. O intervalo de uma hora entre turnos coincide com a preparação do turno seguinte (DD-30) |
| Alocação | Linha por vigência, ligada ao período de tratamento | INV-03; uma alocação por período e data de início; escala nula = sem alocação (DD-27) |
| Troca pontual | Paciente, data de origem, data e escala de destino, termo | Origem é dia da escala vigente do paciente; destino no mesmo mês da origem (P-11); ambos em período aberto |
| Extra planejada | Paciente, data, escala, situação | Data em período aberto; escala diferente da vigente |
| Sessão de turno | Sessão, presenças, ciências da enfermagem | Unicidade por data e escala; confirmada só a partir da última hora do turno (DD-32); após confirmada, alteração só por autorização |
| Ligação manual | Par ausência–presença escolhido pela recepção | Mesmo paciente e mesmo mês; cada lado em no máximo uma ligação |
| Mês alterado | Competência, instante, responsável, autorizador, motivo | Só inserção (RF-915) |

### 7.2 A lista esperada de uma sessão

Função pura `lista_esperada(data, escala)`, usada na tela do turno e na confirmação:

1. Pacientes cuja alocação vigente na data é essa escala, com período aberto na data e sem óbito
   anterior à data (INV-01, INV-04).
2. Mais os pacientes com troca pontual cujo destino é essa sessão.
3. Mais os pacientes com extra planejada para essa sessão.
4. Os pacientes cuja troca pontual tem origem nessa sessão aparecem pré-marcados como ausentes e
   identificados como troca (P-10). Se o paciente comparecer mesmo assim, a recepção desmarca; a troca
   deixa de compensar e a presença no destino, se houver, passa a ser extra (§7.4).
5. Os acrescentados pela recepção vêm das linhas de presença já gravadas (DD-24).

O paciente sem alocação não aparece em nenhuma lista; aparece na pendência "sem alocação" (RF-403).

### 7.3 Ciclo da sessão de turno

| **Momento** | **Estado** | **O que acontece** |
|---|---|---|
| Até uma hora antes do início (parâmetro) | Futura | Visível só para consulta; nada se marca, salvo trocas e extras da enfermagem |
| Da hora de preparação ao início do turno | Em preparação | Tela do próximo turno: lista esperada, com as pendências de cada paciente (DD-30). Permite marcar ausência já avisada pelo paciente (P-13), gravada como exceção; confirmar ainda não |
| Do início do turno em diante | Devida | A tela do turno mostra a lista esperada, todos presentes por padrão. Marcações gravam exceções |
| Última hora do turno (parâmetro) | Devida, com confirmação liberada | Pedido de confirmação em destaque (DD-32) |
| Após o fim do horário do turno, sem confirmação | Devida, em urgência | Pendência de urgência, a mais antiga primeiro, com a contagem (modelo §7.11) |
| Confirmação | Confirmada | Resolve a lista esperada, grava todas as presenças e o autor; tudo numa transação, com a sessão travada |
| Sessão que não aconteceu (P-12) | Não realizada | Só a administração registra, com motivo, em vez de confirmar. Nenhuma presença é gravada; a sessão sai das previstas e não gera ausências. Registrada só para sessão ainda não confirmada; sessão confirmada precisa ser reaberta antes, por autorização |
| Depois de confirmada | Confirmada | Alteração, reabertura ou mudança de alocação que a alcance só por autorização (RF-1008); se o mês já estiver fechado, gera a marca (DD-26) |

Não existe estado "aberta" gravado: "em preparação" e "devida" são derivados do calendário e do
relógio (DD-23). Na interface, o ciclo inteiro acontece na tela inicial (DD-76). No intervalo entre dois turnos, a tela inicial mostra os dois ao mesmo tempo: o turno
que acabou, pedindo confirmação, e o próximo, em preparação.

### 7.4 Classificação e pareamento — `CompensacaoEngine`

Função pura, por paciente e por mês. Entradas: vagas previstas (datas e escalas pela alocação
vigente, dentro do período, sem as sessões não realizadas), presenças (confirmadas, ou resolvidas pela lista esperada se a sessão
ainda não foi confirmada), trocas pontuais e ligações manuais. Saída: classificação de cada presença,
pares formados com sua origem, ausências não compensadas, balanço e a indicação de provisório.

1. **Regular:** presença em vaga prevista.
2. **Ausências:** vagas previstas marcadas como ausentes.
3. **Presenças fora da escala:** presenças que não ocupam vaga prevista.
4. **Pares, em ordem de prioridade:**
   - troca pontual, quando a origem é ausência e o destino foi presença;
   - ligação manual, quando os dois lados ainda são válidos;
   - automático: ausências livres e presenças livres, cada lista em ordem cronológica (data e turno),
     pareadas uma a uma — a mais antiga com a mais antiga (RF-918).
5. **Classificação da presença fora da escala:** troca pontual, reposição (par manual ou automático) ou
   extra (sem par).
6. Ligação manual que deixou de ser válida, por alteração posterior, é ignorada e informada na tela.

Não há "desligar" um par sem formar outro: dentro do mês, ausência e extra livres sempre se
compensam (modelo §7.14). Refazer o pareamento é escolher outras ligações.

### 7.5 Balanço mensal (RF-916)

| **Número** | **Cálculo** |
|---|---|
| Previstas | Vagas da escala vigente em cada data do mês, dentro do período de tratamento, a partir da implantação, incluindo o dia do evento de encerramento (P-09) e excluindo sessões não realizadas (P-12) |
| Realizadas | Presenças, de qualquer classificação |
| Ausências não compensadas | Ausências sem par |
| Reposições | Pares manuais e automáticos, mais trocas pontuais realizadas |
| Extras | Presenças fora da escala sem par — provisórias com o mês aberto, definitivas com o mês fechado |

O aviso de RF-506 aparece ao acrescentar um paciente que já tem quatro extras provisórias no mês; a
pendência "extra além do limite" existe a partir da quinta (RN-01). Nenhum dos dois bloqueia.

### 7.6 Propriedades verificadas por teste (DD-29)

- Cada ausência e cada presença participa de no máximo um par.
- Todo par liga ausência e presença do mesmo paciente e do mesmo mês.
- O número de pares automáticos é o menor entre ausências livres e presenças livres.
- A saída não depende da ordem em que as entradas são fornecidas.
- Previstas = regulares + ausências, para todo paciente e mês.

### 7.7 Regras

| **Regra** | **Tipo** | **Onde** |
|---|---|---|
| Alocação exige período aberto na data de início (INV-03) | Bloqueio | Serviço |
| Alocação, troca ou extra com data em que há sessão confirmada afetada | Requer autorização | Serviço (`RequerAutorizacao`) |
| Presença só em sessão cuja data esteja em período aberto do paciente (INV-04) | Bloqueio | Serviço e lista esperada |
| Nenhum fato datado após o óbito (INV-01, DD-21) | Bloqueio | Serviço, pelo contrato `data_obito` |
| Marcação de ausência só a partir da preparação (P-13); confirmação só a partir da última hora do turno (DD-32) | Bloqueio | Serviço |
| Troca pontual com origem e destino em meses diferentes (P-11). A tela orienta a registrar ausência num mês e extra planejada no outro | Bloqueio | Serviço |
| Sessão não confirmada não conta como frequência lançada (INV-14) | Estrutural | Presenças só materializadas na confirmação (DD-24) |
| Ocupação de escala não tem limite (RF-404) | Sinalização | Consulta |
| Quinta extra no mês | Sinalização | Engine e pendência |
| Presença acrescentada pela recepção sem troca nem extra planejada gera pendência de ciência para a enfermagem (RF-921) | Sinalização | Consulta |

### 7.8 Participação em operações de outros módulos

| **Porta** | **Comportamento do MOD-03** |
|---|---|
| `VerificadorImpedimento` — encerramento de período | Presença (confirmada ou marcada) em data posterior à do evento **impede**, com a lista. Só ocorre com evento de data retroativa; a tela oferece a solicitação de autorização para corrigir as presenças. Trocas e extras planejadas depois da data são **canceladas automaticamente** na mesma transação, com registro (P-08). Alocações não precisam de tratamento: terminam com o período (DD-27) |
| `ParticipanteAnulacao` | Descarta presenças, alocações, trocas, extras, ligações e ciências do cadastro anulado; informa antes quantas e se há sessão confirmada; gera a marca se alcançar mês fechado |
| `ExecutorAutorizavel` | `operacao.sessao.reabrir`, `operacao.presenca.alterar_confirmada`, `operacao.alocacao.registrar_retroativa`, `operacao.troca.cancelar_realizada`, `operacao.pareamento.refazer` em mês fechado. Cada executor verifica se alcança mês fechado e grava a marca (DD-26) |
| Consome `DocumentoIncorporado` | DOC-03 assinado liga-se à troca pontual; DOC-07 assinado liga-se ao paciente e à competência em `termo_extra` (RF-805: um termo por paciente por mês) |

### 7.9 Esquema físico decidido aqui

| **Tabela** | **Colunas principais** | **Restrições** |
|---|---|---|
| `escala` | código, turno, dias, hora_inicio, hora_fim | Carga por migração |
| `alocacao` | periodo_id, escala_id (anulável), vigencia_inicio | Único (periodo_id, vigencia_inicio) |
| `troca_pontual` | paciente_id, data_origem, data_destino, escala_destino_id, documento_id, cancelada_em, cancelada_motivo | Único (paciente_id, data_origem) entre as não canceladas |
| `extra_planejada` | paciente_id, data, escala_id, cancelada_em, cancelada_motivo | Único (paciente_id, data, escala_id) entre as não canceladas |
| `termo_extra` | paciente_id, competencia, documento_id | Único (paciente_id, competencia) |
| `sessao_turno` | data, escala_id, confirmada_em, confirmada_por, nao_realizada_motivo (P-12), versao | Único (data, escala_id) |
| `presenca` | sessao_id, paciente_id, situacao | Único (sessao_id, paciente_id) |
| `ligacao_manual` | ausencia_id, presenca_id | Únicos em cada coluna; mesmo paciente e mês verificados no serviço |
| `ciencia_enfermagem` | presenca_id, registrada_em, registrada_por | Chave primária em presenca_id |
| `mes_alterado` | competencia, instante, responsavel_id, autorizador_id, motivo, solicitacao_id | Só inserção |

A unicidade "entre as não canceladas" usa a mesma técnica da §6.4: coluna gerada nula quando
cancelada, com índice único.

### 7.10 Contratos públicos

**Para a interface**

| **Serviço.método** | **Entrada** | **Saída** | **Erros** |
|---|---|---|---|
| `EscalaService.alocar` / `alocar_em_lote` | Contexto, período ou lista, escala, início | — | `RegraViolada` (INV-01, INV-03), `RequerAutorizacao` |
| `EscalaService.registrar_troca` / `cancelar_troca` | Contexto, paciente, origem, destino | id | `RegraViolada`, `RequerAutorizacao` |
| `EscalaService.registrar_extra` / `cancelar_extra` | Contexto, paciente, data, escala | id | `RegraViolada`, `RequerAutorizacao` |
| `SessaoTurnoService.proximo_turno` | Contexto, instante | data, escala e lista esperada da sessão em preparação, ou nada | `AcessoNegado` |
| `SessaoTurnoService.tela_do_turno` | Contexto, data, escala | lista esperada com marcações, situação e contagem de extras de cada paciente | `AcessoNegado` |
| `SessaoTurnoService.marcar_ausencia` / `desmarcar` | Contexto, data, escala, paciente | — | `RegraViolada`, `RequerAutorizacao` |
| `SessaoTurnoService.acrescentar_paciente` | Contexto, data, escala, paciente, ausência a ligar (opcional) | ausências do mês e contagem de extras (RF-917, RF-506) | `RegraViolada` (INV-01, INV-04) |
| `SessaoTurnoService.confirmar` | Contexto, data, escala, versão | — | `ConflitoDeVersao`, `RegraViolada` |
| `SessaoTurnoService.registrar_nao_realizada` | Contexto (A), data, escala, motivo | — | `AcessoNegado`, `RegraViolada` (sessão futura ou já confirmada) |
| `SessaoTurnoService.devidas_nao_confirmadas` | Contexto | lista, da mais antiga, com a contagem | — |
| `FrequenciaService.pareamento_do_mes` / `refazer` | Contexto, paciente, competência, ligações | pares com a origem de cada um | `RequerAutorizacao` em mês fechado |
| `FrequenciaService.balanco` | Contexto, paciente, competência | balanço e provisório/definitivo | — |
| `FrequenciaService.dar_ciencia` | Contexto, presença | — | `AcessoNegado` |

**Para outros módulos (somente leitura)**

| **Método** | **Saída** | **Usado por** |
|---|---|---|
| `mes_fechado(competencia)` | bool e sessões pendentes | MOD-05 (RF-913) |
| `sessoes_nao_confirmadas(inicio, fim)` | lista | MOD-05 (RF-914), MOD-07 |
| `marcas_alteracao(competencia)` | lista | MOD-05 (RF-915) |
| `frequencia_do_mes(competencia)` | balanço e classificações de todos os pacientes | MOD-05 (relatório mensal) |
| `pendencias_operacao()` | sem alocação, ciência, extra além do limite, termo a emitir, sessões devidas | MOD-07 |

A tela de preparação usa, do MOD-07, `pendencias_dos_pacientes(contexto, ids)`, que devolve as
pendências de cada paciente já filtradas pela matriz §3.2.13 da ERS. O contrato é detalhado no design
do MOD-07.

### 7.11 Eventos de domínio

Consome `DocumentoIncorporado` e `DocumentoRevinculado` (§3.11). Não publica eventos: o encerramento de
período e a anulação chegam pelas portas da §7.8 (DD-74).

---

## 8. MOD-04 — Documentos

### 8.1 Agregados

| **Agregado** | **Raiz e partes** | **Invariantes e regras** |
|---|---|---|
| Tipo de documento | Tabela fixa no núcleo (DEC-41): código, família, anos de retenção, participação no checklist (com condição, como o cartão do convênio), evento que o exige, origem permitida (scanner ou webcam), campos candidatos da extração | Nunca configurável pela tela; sem tipo genérico (DC-02). Catálogo na §8.2 |
| Ingestão | Ingestão | Máquina de estados da §8.4. Uma ingestão gera no máximo um documento. Token de uso único, com prazo |
| Documento | Documento | Imutável: arquivo, hash e chave nunca mudam (INV-06). Paciente muda só por revinculação. Descartado só após o prazo (INV-13, DD-04) |

### 8.2 Catálogo de tipos de documento (P-16)

| **Tipo** | **Família** | **Checklist** | **Exigido por evento** | **Origem** |
|---|---|---|---|---|
| Comprovante de endereço | Cadastro | Sim | — | Scanner |
| Cartão do SUS | Cadastro | Sim | — | Scanner |
| Cartão do convênio | Cadastro | Sim, se o período tiver cobertura por convênio | — | Scanner |
| Documento de identidade | Cadastro | Não | — | Scanner |
| Foto do paciente | Cadastro | Não | — | Webcam |
| Certidão de óbito | Prontuário | Não | Óbito | Scanner |
| Documento de alta | Prontuário | Não | Alta | Scanner |
| Encaminhamento de transferência | Prontuário | Não | Transferência | Scanner |
| Documento do centro transplantador | Prontuário | Não | Transplante | Scanner |
| Termo de interrupção do tratamento assinado (DOC-06) | Prontuário | Não | Desistência | Scanner |
| Declaração de troca de turno assinada (DOC-03) | Prontuário | Não | — (termo da troca, RF-809) | Scanner |
| Termo de diálise extra assinado (DOC-07) | Prontuário | Não | — (termo do mês, RF-809) | Scanner |
| Termo de cateter assinado (DOC-02) | Prontuário | Não | — | Scanner |
| Termo de alimentos assinado (DOC-04) | Prontuário | Não | — | Scanner |
| Carta de recusa assinada (DOC-05) | Prontuário | Não | — | Scanner |

Retenção de 20 anos para as duas famílias, contada como na DD-01. Novo tipo exige nova versão do
sistema (DEC-41).

### 8.3 Pipeline de ingestão

| **Etapa** | **Onde** | **Controles** | **Rejeição** |
|---|---|---|---|
| 1. Abertura | Web | Paciente não anulado, tipo compatível com a origem; token de uso único (DD-05), válido por 10 minutos (SEG-01) | — |
| 2. Recebimento | Web | Token válido e não usado; limite de tamanho no servidor durante a leitura do fluxo (SEG-06); nome aleatório (SEG-07); gravação cifrada na quarentena (SEG-08, DD-34); hash de entrada | Token inválido ou excesso de tamanho |
| 3. Validação | Worker, subprocesso | Tipo real por assinatura binária, lista de permissão PDF, JPEG, PNG e TIFF (SEG-02 a 05); limites de pixels e páginas (SEG-30) | Tipo não permitido, limites excedidos |
| 4. Varredura | Worker | ClamAV pelo socket do serviço; idade das assinaturas conferida (SEG-09, SEG-21) | Detecção, ou assinaturas vencidas |
| 5. Reconstrução | Worker, subprocesso | Cada página rasterizada e reconstruída como imagem limpa; documento em PDF/A sem camada de texto, 300 dpi em tons de cinza; foto em JPEG colorido, reencodado e sem metadados (SEG-10, DC-07) | Falha ou tempo excedido |
| 6. Extração | Worker, subprocesso, se ligada | Tesseract sobre a imagem reconstruída; só os campos candidatos do tipo (DD-40, SEG-31) | Nunca rejeita: sem extração, a conferência segue manual (RNF-702) |
| 7. Conferência | Web | Imagem reconstruída, identificação do paciente de destino em destaque (RF-712), campos candidatos com baixa confiança destacados (RF-704) | Recepcionista rejeita com motivo: ilegível, paciente errado, tipo errado |
| 8. Incorporação | Web, CofreDocumentos | Chave aleatória por documento, cifrada pela chave mestra; AES-256-GCM com o id do documento como dado associado; gravação em duas fases (DD-37); hash no banco e na trilha (SEG-15); quarentena apagada | — |

Cada etapa confere o hash produzido pela anterior (SEG-27). Toda rejeição encerra a ingestão com o
motivo, informa o operador e nunca armazena o arquivo (SEG-12).

### 8.4 Estados da ingestão

| **Estado** | **Próximo** | **Gatilho** |
|---|---|---|
| Aberta | Recebida, Expirada, Cancelada | Arquivo recebido; prazo do token; operador cancela |
| Recebida | Em processamento | Worker toma da fila (DD-33) |
| Em processamento | Aguardando conferência, Rejeitada | Etapas 3 a 6 |
| Aguardando conferência | Incorporada, Rejeitada, Expirada | Recepcionista confirma ou rejeita; 24 h sem ação (DD-34) |

Incorporada, Rejeitada, Expirada e Cancelada são finais. Worker reiniciado no meio do processamento
retoma a ingestão do início da etapa 3, porque nenhuma etapa grava fora da quarentena.

### 8.5 Agente de captura — protocolo

Validado no teste do R-34 (05 e 06/10/2026), na estação da recepção: Windows 10, Chrome 154, scanner
Brother DCP-1610NW pelo WIA, vidro e alimentador automático.

**Fluxo**

1. A tela de digitalização abre a ingestão no servidor e recebe o id e o token (§8.3, etapa 1).
2. O navegador chama o agente em `http://127.0.0.1:<porta>/capturar`, com o id, o token e a origem do
   papel (vidro ou alimentador). Nada mais.
3. O agente confere o cabeçalho `Origin` contra a origem configurada; qualquer outra recebe 403. Uma
   captura por vez: chamada durante outra recebe 409.
4. O agente aciona o scanner configurado, em tons de cinza a 300 dpi (DC-07, DD-78).
5. **A cada página digitalizada**, o agente a converte em memória de BMP para PNG (DD-77) e a envia
   ao servidor por HTTPS, com o certificado raiz fixado, autenticada pelo token:
   `PUT /captura/ingestoes/<id>/paginas/<n>`. A página seguinte é digitalizada enquanto a anterior
   viaja.
6. Terminado o papel, o agente chama `POST /captura/ingestoes/<id>/concluir`, com o número de páginas.
   A ingestão passa a "recebida" e entra na fila (DD-33). O token deixa de valer.
7. O agente responde ao navegador com o resumo (páginas, tempo). A tela acompanha a ingestão pelo
   servidor até a conferência.

**Erros tratados pelo agente**

| **Situação** | **Resposta à tela** |
|---|---|
| Alimentador sem papel antes da primeira página | "Coloque as folhas no alimentador" |
| Scanner configurado não encontrado ou ocupado | "Scanner indisponível"; a ingestão continua aberta até expirar |
| Falha de rede ao enviar uma página | Nova tentativa da mesma página, até 3 vezes; depois, a captura é interrompida e a tela orienta recomeçar |
| Origem não permitida | 403, sem acionar o scanner |

**Configuração do agente**, num arquivo da estação editável só pelo TI e nunca pela requisição:
endereço HTTPS do servidor, certificado raiz da autoridade interna, origem permitida (a do próprio
servidor), **nome** do scanner (DD-79) e porta local. O agente roda na sessão do Windows da recepção,
iniciado no logon, porque o WIA precisa de sessão de usuário. Registra só metadados (data, páginas,
tempos, resultado), nunca imagem.

**Medidas do teste**

| **Medida** | **Observado** | **Uso** |
|---|---|---|
| Página A4 em cinza, 300 dpi, do driver | BMP de 8.741 KB, 2550×3507 | O driver ignora o formato pedido (DD-77) |
| Mesma página em PNG | 700 KB a 3.986 KB, conforme o conteúdo | Limite de tamanho por página (§10.1) |
| Conversão BMP → PNG na estação | 145 a 294 ms por página | Desprezível no RNF-208 |
| Captura pelo vidro | 11,5 a 11,8 s por página | RNF-208 |
| Alimentador, 3 folhas | 23,9 s no total; primeira página 10,3 s, seguintes 4,5 a 8,3 s | RNF-208; 3 de 3 folhas lidas |
| Página colorida | 26.207 KB em BMP; cerca de 13,6 s | Motivo da DD-78 |
| Foto da webcam | 1280×720, 128 KB em JPEG | Limites da foto (§10.1) |

**Orçamento do RNF-208 (30 s da captura à conferência, A4 a 300 dpi):** cerca de 12 s de captura,
menos de 1 s de conversão e envio na rede local, sobrando cerca de 17 s para validação, varredura,
reconstrução e leitura no servidor. O alvo de processamento no servidor fica em **15 s por página**,
medido no plano de testes (§6.3 do PT_recepcao).

**Chrome.** A página na rede local alcançou o agente sem pedido de permissão no Chrome 154, nas duas
fases do teste. A proteção do agente é, portanto, a lista de origens (DD-39), e não o navegador. O
agente continua respondendo à verificação de acesso à rede local, para quando o Chrome passar a
exigi-la. A webcam só abriu em contexto seguro, o que confirma o HTTPS obrigatório na página (DD-80).

A foto do paciente segue pelo módulo JavaScript de câmera (AD-18), direto ao servidor, sem agente.

### 8.6 Consulta, versões, revinculação e descarte

| **Operação** | **Comportamento** |
|---|---|
| Ver | Permissão por perfil, família e paciente; auditoria antes da entrega; decifra em memória; confere o hash (DD-38); página servida como imagem, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff` (SEG-19) |
| Baixar | Ação explícita, só pela administração (P-17), auditada |
| Nova versão | Nova ingestão com a versão anterior indicada e motivo; a anterior permanece consultável (RF-708) |
| Revincular | Motivo obrigatório; paciente de destino não anulado; publica `DocumentoRevinculado`, e MOD-02 e MOD-03 desfazem vínculos de comprovante e de termo que não pertençam mais ao paciente |
| Descartar ao fim do prazo | Pendência para a administração quando o prazo derivado vence (DD-01); operação autorizada; destrói a chave e o arquivo; a linha permanece como registro do descarte (DD-04) |
| Anulação de cadastro | Mesmo mecanismo do descarte, pela porta `ParticipanteAnulacao` (DEC-61) |
| Bloqueio (P-19) | Detecção no rescan ou hash divergente bloqueia a exibição e abre aviso para o TI, só com identificadores, e para a administração. **Detecção no rescan:** após revisão, a administração desbloqueia por autorização, se for falso positivo; se não for, o documento é substituído por nova versão digitalizada do papel. **Hash divergente:** o arquivo foi alterado ou corrompido, e desbloquear não o corrige. O TI restaura o arquivo do backup; se o hash voltar a conferir, o bloqueio cai sozinho. Sem cópia íntegra, nova versão digitalizada do papel, que é o registro de origem (DEC-04) |

### 8.7 Esquema físico decidido aqui

| **Tabela** | **Colunas principais** | **Restrições** |
|---|---|---|
| `tipo_documento` | código, família, anos_retencao, checklist, condicao_checklist, evento_exigente, origem, campos_extracao | Carga por migração (DEC-41) |
| `ingestao` | id aleatório, paciente_id, tipo, origem, vinculo, substitui_id, estado, motivo_rejeicao, token_hash, hash_entrada, hash_reconstruido, paginas, campos_candidatos_cifrados, criada_em, criada_por, atualizada_em | Índice por estado para a fila; `campos_candidatos_cifrados` anulado ao sair de "aguardando conferência" (P-18); nunca texto integral |
| `documento` | id aleatório, paciente_id, tipo, versao, substitui_id, arquivo, chave_cifrada, nonce, hash_sha256, prova_encadeamento, paginas, origem, capturado_em, capturado_por, local_digitalizacao, descartado_em, bloqueado_em, bloqueio_motivo | `hash_sha256` e `arquivo` únicos; `substitui_id` único (uma versão sucede outra só uma vez) |

Usuário de banco dedicado ao módulo, com acesso só às tabelas acima e de leitura aos identificadores de
paciente (SEG-14). Repositório com permissão só para a conta de serviço, sem execução (SEG-13,
RNF-620).

### 8.8 Contratos públicos

**Para a interface**

| **Serviço.método** | **Entrada** | **Saída** | **Erros** |
|---|---|---|---|
| `IngestaoService.abrir` | Contexto, paciente, tipo, origem, vínculo opcional, versão substituída opcional | id e token | `AcessoNegado`, `RegraViolada` |
| `IngestaoService.receber` | token, fluxo do arquivo | — | `AcessoNegado`, `RegraViolada` (tamanho) |
| `IngestaoService.situacao` | Contexto, id | estado, motivo, campos candidatos quando houver | `AcessoNegado` |
| `IngestaoService.incorporar` / `rejeitar` | Contexto, id, motivo | id do documento | `RegraViolada` (estado) |
| `DocumentoService.listar` | Contexto, paciente | metadados da versão vigente e histórico | `AcessoNegado` |
| `DocumentoService.pagina` | Contexto, documento, número | imagem em memória | `AcessoNegado`, `IntegridadeViolada` |
| `DocumentoService.baixar` | Contexto, documento | PDF em memória | `AcessoNegado` |
| `DocumentoService.revincular` | Contexto, documento, paciente, motivo | — | `AcessoNegado`, `RegraViolada` |

**Para outros módulos**

| **Método** | **Saída** | **Usado por** |
|---|---|---|
| `tipos_presentes(paciente_id)` | tipos com versão vigente | MOD-07 (checklist, RF-706) |
| `foto(contexto, paciente_id)` | imagem em memória | MOD-05 (crachá) |
| `copia_ao_titular(contexto, paciente_id)` | PDF único em memória, com a entrega auditada | MOD-11 (RF-1009) |
| `ultimo_documento_em(paciente_id)` | data | Cálculo do prazo (DD-01) |
| `elegiveis_descarte()` | documentos com prazo vencido | MOD-07 |

### 8.9 Eventos de domínio

Publica `DocumentoIncorporado` e `DocumentoRevinculado` (§3.11). A anulação chega pela porta
`ParticipanteAnulacao` (DD-74).

---

## 9. MOD-05 — Emissão e relatórios

### 9.1 Emissão de documentos

| **Documento** | **Fonte dos dados** | **Regra específica** |
|---|---|---|
| DOC-01 Ficha de cadastro | MOD-02, na ordem da ficha (RNF-401) | Campo faltante sai em branco, nunca com valor padrão |
| DOC-02 Termo de cateter | MOD-02 e MOD-06 | — |
| DOC-03 Declaração de troca de turno | MOD-03, a partir da troca pontual (RF-804) | Só para troca registrada e não cancelada |
| DOC-04 Termo de alimentos | MOD-02 e MOD-06 (endereço da clínica) | — |
| DOC-05 Carta de recusa | MOD-02 e texto livre digitado (RF-807) | Texto livre não é gravado (DD-43) |
| DOC-06 Termo de interrupção | MOD-02 e profissional digitado (RF-806) | Profissional não é gravado (DD-43) |
| DOC-07 Termo de diálise extra | MOD-02 e turno vigente do MOD-03 (RF-805) | Aviso, sem bloqueio, se já houve emissão no mês (`ConfirmacaoNecessaria`) |
| Crachá | MOD-02, foto do MOD-04, logotipo do MOD-06 (RF-808) | Sem foto, recusa com orientação de capturar a foto |

Todos: cabeçalho institucional único (RF-802), disponível como variáveis em todo modelo, e data por
extenso com o município (RF-803), por função própria, sem depender da localidade do sistema
operacional. Geração em memória, entrega do PDF com `Content-Disposition: inline` e
`Cache-Control: no-store`, para impressão pelo navegador (RNF-206, RNF-405).

### 9.2 Modelos .docx (DD-42)

**Ciclo de um modelo**

1. A administração baixa o modelo ativo, edita no Word e envia a nova versão.
2. O sistema valida o arquivo (tabela abaixo) e lista cada problema encontrado, em linguagem simples.
3. Aprovado na validação, o sistema gera uma **prévia em PDF com paciente fictício**. A administração
   confere.
4. A administração ativa. A partir daí, toda emissão usa a nova versão.
5. As versões anteriores ficam guardadas; reverter é ativar uma delas de novo.

**Validação no envio**

| **Verificação** | **Motivo** |
|---|---|
| Arquivo .docx real, conferido por assinatura binária e estrutura; .docm e outros formatos recusados | Sem macros; mesmo princípio do SEG-02 e SEG-03 |
| Tamanho e número de partes internas limitados; leitura do XML sem resolução de entidades externas | Arquivo compactado malicioso e XML hostil |
| Nenhuma referência externa (imagem ou vínculo com endereço de fora) | O conversor nunca busca recurso externo (DD-46) |
| Toda variável pertence à lista fechada daquele documento; nenhuma estrutura além de variável (sem laços, condições ou filtros) | Impede execução de código pelo modelo; erro de digitação numa variável aparece no envio, não na emissão |
| Variável partida pelo Word em trechos com formatação diferente é apontada | Problema comum ao editar `{{ nome }}` no Word; o aviso diz qual variável redigitar |
| Fontes usadas disponíveis no conversor, ou substituta métrica conhecida | Evita que o PDF saia com leiaute diferente do Word |

**Variáveis.** Cada documento tem a sua lista, exibida na tela de envio. Exemplos: DOC-01 recebe todos
os campos do cadastro; DOC-03, `{{ data_origem }}`, `{{ turno_origem }}`, `{{ data_destino }}`,
`{{ turno_destino }}`; DOC-05, `{{ texto_recusa }}`; DOC-06, `{{ profissional_nome }}` e
`{{ profissional_registro }}`; crachá, `{{ foto }}` e `{{ logotipo }}` como imagens. Campo vazio sai
em branco.

**Emissão.** Modelo ativo → preenchimento no ambiente isolado → .docx em memória → conversor → PDF em
memória → navegador. Nada é gravado em disco no servidor nem entregue em .docx à estação.

**Ponto de partida.** A construção entrega os oito modelos iniciais, criados do zero (RNF-903, DC-09).

### 9.3 Catálogo de relatórios

| **Relatório** | **Filtros** | **Colunas principais** | **Marcas** |
|---|---|---|---|
| Entradas por período (RF-902) | Período | Paciente, prontuário, início do período, se é retorno | Início da série (RF-907) |
| Pacientes por cidade (RF-903) | Data de referência | Município, quantidade | — |
| Eventos por período (RF-904) | Período, tipo de evento | Paciente, evento, data, comprovante anexado | Início da série |
| Pacientes por convênio (RF-905) | Modo: situação na data, ou cobertura vigente no período | Convênio ou SUS, quantidade | — |
| Frequência mensal (RF-906) | Competência | Paciente, previstas, realizadas, ausências, extras | Bloqueio se mês incompleto (RF-913); mês alterado (RF-915) |
| Balanço mensal (RF-916) | Competência, paciente opcional | Previstas, realizadas, ausências não compensadas, reposições, extras definitivas | Idem |
| Prévia do mês corrente (DD-47) | — | As do balanço | "PRÉVIA — mês em aberto" |
| Ocupação por escala (RF-908) | Data de referência | Escala, pacientes alocados | — |
| Pacientes por faixa etária (RF-910) | Data de referência | Faixa (RF-1206), quantidade | — |
| Pacientes por sexo (RF-911) | Data de referência | Sexo, quantidade, não informado | — |
| Frequência em recorte livre | Período | Paciente, sessões | Sessões não confirmadas no intervalo (RF-914) |
| Aniversariantes do dia (RF-909) | — | Nome | Só na tela inicial; não exportável |

Agregados não suprimem células (DEC-44) e seguem a mesma permissão e auditoria dos relatórios
nominais. Toda contagem de pacientes considera apenas cadastros não anulados.

### 9.4 Regras

| **Regra** | **Tipo** | **Onde** |
|---|---|---|
| Relatório mensal de frequência só com todas as sessões do mês confirmadas ou não realizadas (RF-913, DEC-66) | Bloqueio, informando quantas e quais faltam | Contrato `mes_fechado` do MOD-03 |
| Relatórios de frequência com sessão não confirmada no intervalo exibem a sinalização (RF-914) | Sinalização | Idem |
| Marca de mês alterado (RF-915) nos relatórios de frequência do período (P-21) | Sinalização | Contrato `marcas_alteracao` do MOD-03 |
| Faixa etária calculada na data de referência (RF-910) | Regra pura | Serviço |
| Série histórica informa o início na implantação (RF-907, RN-05) | Sinalização | Modelo tabular |
| Documento emitido sempre do cadastro selecionado, gerado de novo (RNF-903) | Estrutural | DD-43 |
| Emissão usa só modelo ativo e validado; a emissão registra a versão do modelo | Estrutural | DD-42 |

### 9.5 Esquema físico decidido aqui

| **Tabela** | **Colunas principais** | **Restrições** |
|---|---|---|
| `emissao_documento` | paciente_id, modelo, versao_modelo, referencia, emitido_em, emitido_por | Índice por paciente, modelo e competência, para o aviso do DOC-07 |
| `modelo_documento` | codigo, versao, arquivo, hash_sha256, enviado_em, enviado_por, ativado_em, ativado_por | Único (codigo, versao); uma versão ativa por código; sem dado de paciente |

Exportações não têm tabela própria: ficam na trilha de auditoria, com relatório, filtros e formato.

### 9.6 Contratos públicos

| **Serviço.método** | **Entrada** | **Saída** | **Erros** |
|---|---|---|---|
| `EmissaoService.emitir` | Contexto, modelo, paciente, parâmetros (troca, texto livre, profissional), confirmar_reemissao | PDF em memória | `AcessoNegado`, `RegraViolada`, `ConfirmacaoNecessaria` (DOC-07 no mês) |
| `EmissaoService.emitir_cracha` | Contexto, paciente | PDF em memória | `AcessoNegado`, `RegraViolada` (sem foto) |
| `ModeloService.enviar` | Contexto (A), código, arquivo | relatório de validação e prévia | `AcessoNegado`, `RegraViolada` (com a lista de problemas) |
| `ModeloService.ativar` / `reverter` | Contexto (A), código, versão | — | `AcessoNegado` |
| `RelatorioService.gerar` | Contexto, relatório, filtros | modelo tabular com marcas | `AcessoNegado`, `RegraViolada` (mês incompleto, com a lista) |
| `RelatorioService.exportar` | Contexto, relatório, filtros, formato | arquivo em memória | `AcessoNegado`, `RegraViolada` |
| `RelatorioService.aniversariantes` | Contexto, data | nomes | `AcessoNegado` |

**Para outros módulos:** `emissoes_do_mes(paciente_id, competencia, modelo)`, usado pelo MOD-07 na
pendência de termo (RF-809) e pelo aviso do DOC-07. O MOD-11 usa `EmissaoService` para a declaração
de atendimento ao titular.

---

## 10. MOD-06 — Configuração

### 10.1 Catálogo de parâmetros

Valores padrão decididos até aqui. **Operacional** é alterado pela administração; **técnico**, pelo TI.

| **Parâmetro** | **Padrão** | **Limites** | **Tipo** | **Origem** |
|---|---|---|---|---|
| Antecedência da preparação do turno | 60 min | 15–120 min | Operacional | DD-30, DEC-64 |
| Antecedência da liberação da confirmação | 60 min | 15–120 min | Operacional | DD-32, DEC-67 |
| Prazo do rascunho de cadastro / aviso antes do descarte | 3 dias / 1 dia | 1–30 / 1–7 dias | Operacional | RF-920 |
| Prazo de resposta ao titular | 15 dias | 1–15 dias | Operacional | DD-18, LGPD art. 19, II |
| Inatividade até encerrar a sessão | 10 min | 2–30 min | Técnico | DD-19 |
| Duração máxima da sessão de usuário | 12 h | 1–16 h | Técnico | DD-19 |
| Bloqueio de login: tentativas, bloqueio inicial, teto | 5, 5 min, 60 min | 3–10; 1–30; 15–240 min | Técnico | §5.2 |
| Validade do token de captura | 10 min | 2–30 min | Técnico | §8.3 |
| Prazo da quarentena e da ingestão pendente | 24 h | 1–72 h | Técnico | DD-34 |
| Tamanho máximo por página recebida (PNG) | 12 MB | 4–30 MB | Técnico | SEG-06; 3 vezes a maior página do teste do R-34 (3,9 MB) |
| Páginas por ingestão | 30 | 1–100 | Técnico | SEG-30 |
| Pixels por página | 12 milhões | Teto fixo de 20 milhões | Técnico | SEG-30; A4 a 300 dpi tem 8,9 milhões; ofício, 10,7 |
| Foto do paciente: tamanho e pixels | 2 MB; 4 milhões | Teto fixo | Técnico | Foto do teste: 128 KB, 0,9 milhão |
| Tempo máximo de processamento por página | 20 s | 10–60 s | Técnico | SEG-30; alvo de 15 s (§8.5) |
| Extração automática ligada | Sim | Sim/Não | Técnico | RNF-702, QAS-08 |
| Idade máxima das assinaturas do antimalware | 48 h | 24–168 h | Técnico | SEG-21 |
| Data de implantação | Definida na implantação | Imutável após a primeira confirmação | Técnico | DD-51 |

Limites de captura e processamento calibrados no teste do R-34 (§8.5). Prazos do rascunho definidos pela clínica: 3 dias de guarda, com aviso no dia anterior ao descarte. O prazo do titular
tem teto de 15 dias porque é o limite legal.

### 10.2 Dados de referência

| **Dado** | **Conteúdo** | **Manutenção** |
|---|---|---|
| Dados institucionais (RF-1201) | Nome, endereço, CEP, município, UF, telefone, CNPJ | Administração; uma linha só |
| Logotipo (RF-1202) | Imagem reencodada (DD-50) | Administração |
| Convênios (RF-1204) | Nome, situação | Administração; inativar em vez de excluir (DD-49) |
| Municípios (RF-1205) | Código IBGE de 7 dígitos, nome, UF | Carga inicial por migração, com a tabela do IBGE já em 7 dígitos. Códigos de 6 dígitos das planilhas convertidos por consulta à tabela (DD-53). O TI pode **incluir** município novo pela tela, com alerta se o dígito verificador não conferir; município existente não é alterado nem excluído, porque cadastros e a instituição apontam para ele (DD-52) |
| Faixas etárias (RF-1206) | Onze faixas, DEC-49 | Migração; alteração em nova versão |

### 10.3 Contratos públicos

| **Método** | **Saída** | **Usado por** |
|---|---|---|
| `parametro(nome)` | valor tipado, sempre dentro dos limites | Todos |
| `institucional()`, `logotipo()` | dados e imagem | MOD-05 |
| `convenios_ativos()` | lista | MOD-02 |
| `municipio(codigo)`, `buscar_municipio(termo, uf)` | município | MOD-02 (residência só GO), MOD-05, MOD-06 |
| `ConfiguracaoService.incluir_municipio` | — ou `RegraViolada` (código existente), `ConfirmacaoNecessaria` (dígito não confere) | Interface |
| `codigo_7_digitos(codigo_6)` | código de 7 dígitos ou nada (DD-53) | MOD-10 |
| `faixas_etarias()` | faixas | MOD-05 |
| `ConfiguracaoService.alterar_parametro` | — ou `RegraViolada` (fora dos limites, imutável) | Interface |

### 10.4 Esquema físico decidido aqui

| **Tabela** | **Colunas principais** | **Restrições** |
|---|---|---|
| `parametro` | nome, valor, alterado_em, alterado_por | Chave primária em nome; nome precisa existir no registro do código |
| `instituicao` | nome, endereco, cep, municipio_id, uf, telefone, cnpj, logotipo | Linha única |
| `convenio` | nome, ativo | Nome único |
| `municipio` | codigo_ibge, nome, uf, incluido_em, incluido_por | Código único; carga inicial por migração; inclusões auditadas (DD-52) |
| `faixa_etaria` | inicio, fim | Carga por migração |

---

## 11. MOD-07 — Pendências

### 11.1 Catálogo de pendências

Linhas 1 a 13 reproduzem a matriz da ERS §3.2.13; as linhas 14 a 19 foram incluídas na ERS por DEC-70 (P-24), e a linha 20, por DEC-72 (P-27).
Prioridade: **U** urgência, sempre no topo; **A** alta; **N** normal. Dentro da mesma prioridade, a mais
antiga primeiro, com a contagem por tipo (RNF-408, IU-04).

| # | **Pendência** | **Fonte** | **Perfis** | **Pri.** | **Encerra quando** |
|---|---|---|---|---|---|
| 1 | Cadastro incompleto ou CEP não verificado | MOD-02 | R, A | N | Campo preenchido; CEP verificado |
| 2 | Documento do checklist faltante | MOD-04, com a cobertura do MOD-02 | R, A | N | Documento incorporado |
| 3 | Evento sem documento comprobatório | MOD-02 | R, A | A | Comprovante ligado ao evento |
| 4 | Sessão de turno não confirmada | MOD-03 | R, A | U | Sessão confirmada ou não realizada |
| 5 | Termo a emitir e assinar — troca ou extra (RF-809), com a etapa: a emitir, ou emitido e aguardando digitalização | MOD-03, com a emissão do MOD-05 | R, A, E | A | Termo assinado incorporado |
| 6 | Paciente sem alocação (RF-403) | MOD-03 | R, A, E | A | Alocação registrada |
| 7 | Presença fora da escala sem registro prévio (RF-921) | MOD-03 | E | N | Ciência registrada |
| 8 | Sessão extra além do limite mensal | MOD-03 | R, A, E | N | Fim do mês ou extra compensada |
| 9 | Possível duplicidade pela tríade | MOD-02 | R, A | N | Duplicidade descartada ou cadastro anulado |
| 10 | Pedido de titular, com prazo visível | MOD-11 | R, A, V | A; U a 3 dias do prazo | Pedido atendido ou negado |
| 11 | Solicitação de autorização | MOD-01 | A | A | Decidida |
| 12 | Falha na verificação da cadeia de auditoria | MOD-01 | A (aviso simples), T (diagnóstico) | U | Aviso encerrado pela administração |
| 13 | Rascunho próximo do descarte — só para o autor | MOD-02 | R, A | N | Rascunho salvo, retomado ou descartado |
| 14 | Documento capturado aguardando conferência | MOD-04 | R, A | A | Incorporado, rejeitado ou expirado (24 h) |
| 15 | Documento bloqueado (P-19) | MOD-04 | A; T só com identificadores | U | Desbloqueado ou substituído |
| 16 | Documentos elegíveis para descarte ao fim da retenção (DD-04) | MOD-04 | A | N | Descartados por autorização |
| 17 | Job agendado que não rodou no horário (R-38) | MOD-09 | T | U | Execução bem-sucedida |
| 18 | Assinaturas do antimalware desatualizadas (SEG-21) | MOD-04 | T | U | Assinaturas atualizadas |
| 19 | Ocupação de disco acima do limite (RNF-621) | MOD-09 | T | A | Ocupação abaixo do limite |
| 20 | Âncora mensal da cadeia de auditoria para anotação (DAS, A.2) | MOD-01 | A | N | Administração registra a anotação |

### 11.2 Regras de alcance

| **Regra** | **Pendências** |
|---|---|
| Só pacientes não anulados | Todas as de paciente |
| Só pacientes em tratamento (período aberto) | 1, 2, 6 (P-25, DEC-71) |
| Pacientes em qualquer situação | 3, 9, 10 |
| Nenhum dado de paciente para o TI | 12, 15, 17, 18, 19 mostram só identificadores internos (RNF-625) |

### 11.3 Pendências por paciente

`dos_pacientes(contexto, ids)` devolve, para cada paciente, as pendências de paciente que o perfil pode
ver. É usada na preparação do turno (DD-30) e na ficha do paciente. Cada fonte responde ao conjunto de
ids numa consulta só, sem consulta por paciente.

### 11.4 A porta `FontePendencia`

| **Membro** | **Descrição** |
|---|---|
| `codigo` | Identificador da linha da matriz |
| `prioridade(item)` | U, A ou N; pode depender do item, como no prazo do titular |
| `listar(contexto)` | Itens com descrição, desde quando, paciente quando houver e destino para resolver |
| `listar_por_pacientes(contexto, ids)` | Mesmos itens, restritos aos pacientes informados; fontes sem paciente não implementam |
| `contar(contexto)` | Contagem, sem montar os itens, para a tela inicial |

### 11.5 Contratos públicos

| **Método** | **Saída** | **Usado por** |
|---|---|---|
| `PendenciaService.resumo(contexto)` | contagem por tipo, urgências primeiro | Tela inicial |
| `PendenciaService.listar(contexto, codigo)` | itens ordenados | Tela de pendências |
| `PendenciaService.dos_pacientes(contexto, ids)` | itens por paciente | Preparação do turno, ficha do paciente |

O MOD-07 não tem tabela: pendência é consulta (modelo §7.4).

---

## 12. MOD-08 — Dados

### 12.1 Componentes

| **Componente** | **Responsabilidade** |
|---|---|
| `modelos/<modulo>.py` | Modelos SQLAlchemy de cada módulo, com relacionamentos `lazy="raise"` (DD-12) |
| `UnidadeDeTrabalho` | Abre a transação por operação, fornece os repositórios, despacha eventos de domínio antes do commit (DD-15), grava a auditoria na fase de commit (DD-03), repete em impasse (DD-59) |
| Repositórios | Um por agregado, só com os métodos que os serviços usam; carregam explicitamente o necessário |
| `migracoes/` | Alembic (DD-60) |
| Linha de comando `sar` | Migrar, criar usuários, registrar execução externa (DD-62), verificar a cadeia sob demanda |

O contrato do MOD-08 com os demais módulos é a porta `UnidadeDeTrabalho` do núcleo (§3.3, §3.4): os
serviços abrem a unidade, pedem repositórios, publicam eventos e registram auditoria por ela, sem
importar SQLAlchemy.

### 12.2 Convenções do esquema físico

| **Item** | **Convenção** |
|---|---|
| Conjunto de caracteres | `utf8mb4`, collation `utf8mb4_0900_ai_ci` para texto buscável; `ascii_bin` para hashes, tokens e códigos |
| Instantes | `DATETIME(6)` em UTC; a conexão fixa o fuso em `+00:00` |
| Datas de calendário | `DATE`, na data local da clínica |
| Chaves | `BIGINT` sequencial interno; identificador aleatório UUIDv4 em `BINARY(16)` onde o id aparece em endereço (documento, ingestão, solicitação) |
| Hashes | SHA-256 em `CHAR(64)` hexadecimal |
| Nomes de restrições | Padrão fixo por tipo — `pk_`, `fk_`, `uq_`, `ix_`, `ck_` + tabela + colunas —, para que a geração de migração seja estável |
| Exclusão | Sem `ON DELETE CASCADE`; exclusão física só onde a regra permite, pelo usuário de banco que tem o privilégio |
| Concorrência otimista | Coluna `versao` nos agregados editáveis por tela (DD-17) |

### 12.3 Usuários de banco (DD-58)

| **Usuário** | **Processo** | **Privilégios principais** |
|---|---|---|
| `sar_web` | Web | Leitura e escrita nas tabelas de negócio; auditoria só `INSERT` e `SELECT`; `documento` sem `DELETE`, `UPDATE` só em `paciente_id`, `descartado_em`, `chave_cifrada`, `bloqueado_em` e `bloqueio_motivo`; `auditoria_cabeca` só `UPDATE` |
| `sar_worker` | Worker | O necessário para a fila de ingestão e para cada job; auditoria só `INSERT` e `SELECT`; `DELETE` só em `ingestao` e `rascunho_cadastro` |
| `sar_expurgo` | Job de expurgo da trilha | `DELETE` em `auditoria`, `INSERT` em `auditoria_corte` (§5.6) |
| `sar_migracao` | Contêiner de migração | Estrutura; usado só na implantação e nas atualizações |

Nenhum usuário do SAR existe na instância do SCE, nem o contrário (RNF-614). Senhas em segredo do
contêiner, fora do repositório.

### 12.4 Esquema físico implementado

O esquema está em código, pronto para o repositório:

| **Arquivo** | **Conteúdo** |
|---|---|
| `migracoes/versions/0001_esquema_inicial.py` | As 40 tabelas, com chaves, índices, restrições `CHECK` e colunas geradas |
| `migracoes/versions/0003_auditoria_correlacao.py` | Sessão e id da requisição na auditoria (DD-81); testada em ida, volta e ida |
| `migracoes/versions/0002_dados_fixos.py` | Escalas (P-14), tipos de documento (§8.2), faixas etárias (DEC-49), municípios do IBGE (arquivo oficial em CSV) e a cabeça da cadeia |
| `migracoes/env.py` | Ambiente do Alembic; conexão com fuso `+00:00`, usuário `sar_migracao` |
| `usuarios_banco.sql` | Usuários `sar_web`, `sar_worker` e `sar_expurgo`, com privilégios por tabela e coluna (§12.3) |
| `verificar_esquema.sh` | 27 verificações: invariantes estruturais, privilégios e configuração de logs do servidor (DD-82) |

Testado do zero em MySQL 8.0: migração, reversão e nova migração; criação dos usuários; as 24
verificações passaram. A produção usa MySQL 9.7 LTS (AD-09); os recursos usados — `CHECK`, colunas
geradas, `SKIP LOCKED` e privilégio por coluna — existem desde a série 8.0. Repetir a verificação na
imagem de produção faz parte do plano de testes.

Refinamentos em relação às tabelas das seções de cada módulo: `ingestao.documento_id` liga a ingestão
ao documento que ela gerou; `emissao_documento.competencia` apoia o aviso do DOC-07;
`auditoria_ancora` ganhou `anotada_em` e `anotada_por` (pendência 20); `aviso_integridade` trata só da
cadeia — o bloqueio de documento fica no próprio documento (P-19); `documento.prova_encadeamento`
aceita nulo só dentro da transação de incorporação (DD-37).

---

## 13. MOD-09 — Agendamento

### 13.1 Catálogo de jobs

Agendamento em `America/Sao_Paulo`. Todos são idempotentes. Rotinas leves rodam ao longo do dia ou no
início da noite. **Rotinas pesadas rodam de madrugada, a partir das 02:00, com 10 minutos entre uma e
outra (P-26, DD-64)**; as semanais e mensais, só aos domingos, quando a clínica não opera.

| **Job** | **Módulo** | **Quando** | **Intervalo máximo entre sucessos** | **Se perdeu o horário** | **Execução manual pelo TI** |
|---|---|---|---|---|---|
| Consumidor da fila de ingestão | MOD-04 | Contínuo, a cada 2 s (DD-63) | 5 min com fila não vazia | Retoma ao subir | — |
| Expiração de ingestões e limpeza da quarentena | MOD-04 | A cada 15 min | 1 h | Roda ao subir | Sim |
| Descarte de rascunhos vencidos | MOD-02 | Diário, 20:30 | 2 dias | Roda ao subir | Sim |
| Varredura de arquivos órfãos no repositório (pesada) | MOD-04 | Diário, 02:10 | 2 dias | Próximo horário | Sim |
| Verificação da cadeia de auditoria e registro da âncora (pesada) | MOD-01 | Diário, 02:00 | 2 dias | Roda ao subir, fora da janela de operação | Sim |
| Idade das assinaturas do antimalware | MOD-04 | A cada hora | 3 h | Roda ao subir | Sim |
| Ocupação de disco | MOD-09 | A cada hora | 3 h | Roda ao subir | Sim |
| Backup: dump e restic (pesada; sistema operacional, DD-62) | Servidor | Diário, 02:20, depois da âncora do dia | 2 dias | Próximo horário | — |
| Cópia para o pen drive (manual, com registro) | Servidor | Semanal | 8 dias | — | — |
| Rescan antimalware do acervo (pesada) | MOD-04 | Domingo, 02:30 | 8 dias | Próximo domingo | Sim |
| Conferência de hash de todo o acervo (pesada) | MOD-04 | Primeiro domingo do mês, 02:40 | 35 dias | Próximo domingo | Sim |
| Expurgo da trilha com mais de 5 anos (pesada) | MOD-01 | Primeiro domingo do mês, 02:50 | 35 dias | Próximo domingo | Não |

A ordem importa: a verificação da cadeia registra a âncora às 02:00, e o backup das 02:20 a leva
consigo, como pede o DAS (A.2).

Removidos em relação ao DAS: abertura de sessões e lembrete de confirmação, que passaram a ser
derivados (DD-23, DD-32).

### 13.2 Âncora mensal para a administração

A verificação diária registra a âncora. Uma vez por mês, a âncora mais recente aparece à administração
como pendência, para anotação fora do sistema (DAS, A.2). A pendência se encerra quando a
administração registra que anotou. É a pendência 20 do catálogo (§11.1, DEC-72).

### 13.3 Contrato de um job

Cada módulo declara seus jobs; a raiz de composição os registra no agendador. O job chama serviços,
nunca repositórios (DAS §4.2).

| **Campo** | **Descrição** |
|---|---|
| `nome` | Identificador único, usado na trava (DD-61) e em `job_execucao` |
| `modulo` | Módulo dono |
| `agenda` | Expressão de horário no fuso da clínica, ou intervalo |
| `pesado` | Entra na série da madrugada, com a trava compartilhada e o limite das 04:30 (DD-64) |
| `intervalo_maximo` | Acima dele sem sucesso, pendência 17 |
| `roda_ao_subir` | Executa na partida do worker se perdeu o horário (DD-08) |
| `manual_permitida` | O TI pode executar pela tela (§4.8) |
| `executar(contexto_sistema) -> ResultadoJob` | Itens processados, e se parou por limite de horário com cursor salvo |

### 13.4 Registro de execução

`job_execucao`: job, início, fim, resultado (sucesso, falha, sem trabalho), itens processados, resumo
do erro sem dado pessoal (RNF-624). A pendência 17 compara, para cada job, o último sucesso com o
intervalo máximo da §13.1.

---

## 14. MOD-10 — Carga inicial

### 14.1 Etapas

| # | **Etapa** | **Regra** | **Vai para exceções quando** |
|---|---|---|---|
| 1 | Leitura das planilhas pelo extrator já validado (AD-22) | Planilha de endereços e telefones é a base (RF-1101, RN-04) | Linha ilegível ou sem prontuário |
| 2 | Complemento pela planilha de entradas, pelo prontuário (RF-1102) | Traz a data de início do tratamento | Prontuário da base sem entrada, ou entrada sem base |
| 3 | Conferência com a planilha de eventos (RF-1103) | Paciente da base com evento de saída registrado é cadastro desatualizado | Sempre: a recepção decide se importa ou não; a carga não registra evento por conta própria |
| 4 | Conversão do IBGE de 6 para 7 dígitos (RF-1104) | Por consulta à tabela (DD-53) | Código sem correspondência; campo fica vazio |
| 5 | Validação dos campos | CPF e CNS pelo dígito (DEC-58); CEP pelo formato (DD-68) | Valor inválido; campo fica vazio e vira pendência |
| 6 | Mínimo do cadastro (P-03) | Nome, data de início e prontuário | Faltando qualquer um: o paciente não é importado; a recepção o cadastra pela tela (P-28) |
| 7 | Unicidade | Prontuário, CPF e CNS únicos (INV-07, INV-15) | Repetição: o segundo registro vai às exceções |
| 8 | Criação pelo contrato do MOD-02 (DD-67) | Paciente, período aberto com início da entrada, cobertura, contatos e telefones | — |

Não fazem parte da carga, por decisão já tomada:
- **Histórico de frequência:** o histórico do sistema começa na implantação (RN-05).
- **Alocação:** todo paciente entra "sem alocação", e a enfermagem distribui pela tela de distribuição
  em lote (RF-405, DEC-48).
- **Documentos:** todos entram com o checklist pendente (RF-1107).
- **Sexo e naturalidade:** ausentes nas planilhas; entram como pendência (RF-1108).

### 14.2 Fechamento da contagem (RNF-103)

O comando termina com a conta: **linhas na origem = pacientes importados + linhas em exceção**, por
planilha. Se a conta não fechar, a simulação falha. Zero exceções não prova carga correta; por isso a
conferência amostral é obrigatória (§3.2.11 da ERS).

### 14.3 Conferência amostral e aceite

1. Depois da efetivação, o sistema sorteia 15 pacientes importados, cerca de 10% da base (P-29). Se a
   conferência encontrar divergência que não seja caso isolado, sorteia mais 15.
2. A recepção abre cada paciente sorteado numa tela lado a lado: à esquerda, a linha original da
   planilha; à direita, o cadastro como ficou. Marca cada campo como conferido ou divergente.
3. Divergência é corrigida no cadastro, pela tela normal, e registrada.
4. Com a amostra conferida e as exceções tratadas — importadas manualmente ou descartadas com motivo
   —, a administração aceita a carga.
5. O aceite apaga a área de trabalho (DD-69) e encerra o MOD-10. Não há segunda carga.

### 14.4 Esquema físico decidido aqui

| **Tabela** | **Colunas principais** | **Restrições** |
|---|---|---|
| `carga_lote` | modo (simulação, efetivação), situação, contagens por planilha, iniciado_em, concluido_em, aceito_em, aceito_por | Uma efetivação só |
| `carga_linha` | lote_id, planilha, numero_linha, conteudo_cifrado, paciente_id, excecao_codigo, excecao_tratada | Apagada no aceite (DD-69) |
| `carga_conferencia` | paciente_id, campo, resultado, conferido_por, conferido_em | Apagada no aceite; o resultado resumido fica na auditoria |

### 14.5 Contratos públicos

| **Serviço.método** | **Entrada** | **Saída** | **Erros** |
|---|---|---|---|
| `CargaService.simular` | Contexto (T), pasta das planilhas | contagens por planilha e código de exceção, sem dado pessoal | `AcessoNegado`, `RegraViolada` (contagem não fecha, RNF-103) |
| `CargaService.efetivar` | Contexto (T), pasta das planilhas | idem | `RegraViolada` (já efetivada; contagem não fecha) |
| `CargaService.excecoes` | Contexto (R ou A) | linhas em exceção, com o conteúdo original e o motivo | `AcessoNegado` |
| `CargaService.tratar_excecao` | Contexto (R ou A), linha, tratamento, motivo | — | `RegraViolada` |
| `CargaService.amostra` / `registrar_conferencia` | Contexto (R ou A), paciente, campo, resultado | pacientes sorteados; — | `AcessoNegado` |
| `CargaService.aceitar` | Contexto (A) | — | `RegraViolada` (amostra incompleta ou exceção sem tratamento) |

---

## 15. MOD-11 — Atendimento ao titular

**Agregado:** Requisição de titular — paciente, tipo, canal, data de recebimento, situação (aberta,
atendida, negada), desfecho, data de atendimento e atendente. Prazo derivado (DD-18).

**Tipos (LGPD, art. 18):** confirmação e acesso; correção; informação sobre uso e compartilhamento;
eliminação, anonimização ou bloqueio; outros. Pedido de eliminação de dado sob guarda obrigatória é
respondido com a negativa fundamentada no art. 16, I, e na Lei nº 13.787/2018.

**Atendimento de acesso (RF-1009):** ficha cadastral pelo MOD-02; cópia dos documentos pelo MOD-04;
declaração pelo MOD-05; registro da entrega. Tudo auditado.

**Contratos públicos**

| **Serviço.método** | **Entrada** | **Saída** | **Erros** |
|---|---|---|---|
| `TitularService.registrar` | Contexto (R ou A), paciente, tipo, canal, data de recebimento | id | `AcessoNegado`, `RegraViolada` |
| `TitularService.consultar` | Contexto (R, A ou V), situação | requisições com prazo derivado (DD-18) | `AcessoNegado` |
| `TitularService.atender_acesso` | Contexto (A), requisição | pacote em memória: ficha, cópia dos documentos e declaração | `AcessoNegado`, `RegraViolada` |
| `TitularService.concluir` / `negar` | Contexto (A), requisição, desfecho | — | `AcessoNegado`, `RegraViolada` (negativa sem fundamento) |

Implementa `FontePendencia` para a pendência 10, que vira urgência a 3 dias do prazo.

---

## 16. A elaborar

1. ~~Contratos restantes entre módulos~~ — feito (§3.4, §3.11, §3.12, §12.1, §13.3, §14.5, §15).
2. ~~Esquema físico completo~~ — feito (§12.4).
3. ~~Protótipos~~ — feitos (tela inicial com o ciclo das sessões, DD-76). O comportamento em JavaScript e os testes com jsdom do pacote do protótipo servem só à validação; na construção, o CSS é gerado pelo executável standalone do Tailwind, sem Node (AD-05), e o comportamento é testado pelo Playwright: início com preparação do turno, frequência e confirmação, novo cadastro e pendências, com dados fictícios, em validação com a recepcionista. Versão em HTML com Tailwind v4, sem código inline (DD-09), com os tokens de cor e tipografia em `src/sar.css` e 28 testes de comportamento — base do guia de componentes e dos modelos Jinja2.
4. ~~Guia de componentes~~ — feito: `componentes.html` no pacote do protótipo, com cores (contraste medido, todos os pares acima de 4,5:1), tipografia, medidas, componentes com seus estados e as regras de construção.
5. ~~Protocolo do agente de captura e limites de processamento~~ — feitos a partir do teste do R-34 (§8.5, §10.1, DD-77 a DD-80).
6. ~~Plano de testes~~ — feito: documento PT_recepcao, com estratégia por nível e técnica, casos por área de risco, corpus hostil, desempenho, recuperação, acessibilidade, homologação e rastreabilidade verificada por máquina (`verificar_rastreabilidade.py`).

---

## 17. Pontos a validar com a clínica

| **ID** | **Ponto** | **Proposta** |
|---|---|---|
| P-01 | A administração pode aprovar a própria solicitação? | **Resolvido: confirmação automática.** Quando o solicitante é da administração, a operação executa direto, sem passar pela fila, registrando o mesmo usuário como autor e autorizador (§5.3) — DEC-60 |
| P-02 | Uma sessão ativa por usuário? | **Resolvido: sim.** Novo login encerra a sessão anterior, com aviso. Dificulta o compartilhamento de senha (§5.1, DD-19) — DEC-63 |
| P-03 | Mínimo para salvar um cadastro | **Resolvido.** Nome, data de início do tratamento e número de prontuário. Com o mínimo, o usuário escolhe salvar o paciente, que entra em tratamento com pendências, ou salvar como rascunho. Sem o mínimo, só é possível salvar como rascunho (§6.2, §6.6) — DEC-57 |
| P-04 | CPF já cadastrado em outro paciente | **Resolvido:** CPF e CNS repetidos bloqueiam, informando o paciente que já usa o número, como no prontuário (§6.2, §6.4) — DEC-59 |
| P-05 | INV-01 e o comprovante do óbito | **Resolvido (DD-21).** A invariante vale para fatos datados — presença, alocação, troca, evento e período. A captura de documento após o óbito é permitida, pois a certidão chega depois por natureza (DEC-50). O critério do UC-07 que cita "documento" passa a ter essa leitura — DEC-62 |
| P-06 | Anulação de cadastro criado por engano | **Resolvido:** na aprovação da administração, tudo o que está vinculado é descartado automaticamente, sem preparo manual e sem transferência; a duplicata é barrada na origem por prontuário e CPF únicos (§6.9) — DEC-61 |
| P-07 | Telefone com duas chaves estrangeiras | **Resolvido:** DD-06 confirmada |
| P-08 | Trocas e extras planejadas depois da data de um evento de encerramento | **Resolvido (DD-31) — DEC-65.** Cancelamento automático na mesma transação do evento, com registro. O impedimento por presença só ocorre quando o evento é registrado com **data retroativa**: por exemplo, o óbito ocorrido na terça é informado na sexta, e na quarta o paciente constou como presente numa sessão confirmada (o padrão "todos presentes" não foi desmarcado). A tela lista essas presenças e já oferece a solicitação de autorização para corrigi-las (RF-1008); corrigidas, o evento é registrado |
| P-09 | O dia do evento de encerramento conta como sessão prevista? | **Resolvido: sim (§7.5).** A INV-01 proíbe registro **depois** da data, e o paciente pode ter dialisado no próprio dia da alta ou da transferência |
| P-10 | Na sessão de origem de uma troca pontual, o paciente aparece? | **Resolvido: sim (§7.2).** já marcado como ausente e identificado como troca. Se comparecer mesmo assim, a recepção desmarca |
| P-11 | Troca pontual pode cruzar a virada do mês? | **Resolvido: não (§7.1, §7.7).** origem e destino no mesmo mês, coerente com a fronteira real do mês (modelo §7.14). Troca entre meses é registrada como ausência num mês e extra planejada no outro |
| P-12 | Sessão que não aconteceu, por fechamento excepcional da clínica | **Resolvido (§7.3) — DEC-66.** Confirmação como "não realizada", só pela administração, com motivo. A sessão sai das previstas e não gera ausências |
| P-13 | Na preparação, a recepção pode marcar ausência já avisada pelo paciente? | **Resolvido: sim (§7.3, §7.7).** quando o paciente avisa antes. A marcação fica como exceção e só vale na confirmação, como qualquer outra (DD-24) |
| P-14 | Horário dos turnos e janela de disponibilidade | **Resolvido (§7.1).** Turno 1: 06:00–10:00; turno 2: 11:00–15:00; turno 3: 16:00–20:00. A janela do RNF-501 passa à P-15 |
| P-15 | Janela de disponibilidade do RNF-501 e momento da confirmação | **Resolvido (DD-32) — DEC-67 e DEC-68.** Confirmação liberada na última hora de cada turno; janela de 05:00 às 20:00, de segunda a sábado. Às 05:00 o sistema já mostra a preparação do turno 1, sem precisar de alguém olhando |
| P-16 | Catálogo fechado de tipos de documento (DEC-41) | **Resolvido:** catálogo da §8.2, famílias cadastro e prontuário, 20 anos de retenção para as duas, contados como na DD-01 |
| P-17 | Quem pode baixar documento | **Resolvido (§4.4, §8.6).** Só a administração. Recepção e visualizador veem dentro da aplicação; o download só é necessário para a cópia ao titular e para demanda legal |
| P-18 | Guarda dos campos candidatos da extração até a conferência | **Resolvido (DD-40, §8.7).** Web e worker são processos distintos, então os campos lidos precisam esperar a conferência em algum lugar. Proposta: gravados cifrados na própria ingestão e apagados ao concluir, rejeitar ou expirar (no máximo 24 h). Só os campos do tipo, nunca o texto integral (SEG-31) |
| P-19 | Documento com detecção no rescan ou hash divergente | **Resolvido (§8.6).** Bloqueado para exibição até revisão; aviso ao TI (só identificadores) e à administração; desbloqueio por autorização da administração |
| P-20 | Quais relatórios a recepção vê | **Resolvido (§4.5).** A ERS dá à administração "relatórios completos" e à enfermagem os operacionais (DEC-55). Proposta: recepção vê os operacionais (frequência, balanço, prévia, ocupação) e os aniversariantes; os gerenciais (entradas, cidade, eventos, convênio, faixa etária, sexo) ficam com administração e visualizador |
| P-21 | Onde aparece a marca de mês alterado (RF-915) | **Resolvido (§9.4) — DEC-69.** O RF-915 diz "em todo relatório daquele período". A alteração só muda números de frequência; a marca em "pacientes por sexo" confundiria. Proposta: nos relatórios de frequência (mensal, balanço, recorte livre) que incluam o mês |
| P-22 | Quem edita os modelos dos documentos (RNF-703) | **Resolvido (§4.5, §9.2).** A administração, enviando o modelo .docx, que é dona do conteúdo, com auditoria de cada alteração. O TI não edita texto de documento |
| P-23 | Quem cadastra estabelecimento referenciador (CNES) | **Superado — DEC-73:** a clínica decidiu retirar do sistema o registro da instituição que encaminhou o paciente |
| P-24 | Novas linhas na matriz de pendências | **Resolvido — DEC-70.** As linhas 14 a 19 da §11.1 decorrem de requisitos e decisões já aprovados (SEG-12, SEG-15, SEG-21, RNF-621, R-38, DD-04), mas a matriz da ERS §3.2.13 é fechada. Proposta: incluí-las na ERS antes da assinatura, como DEC-70 |
| P-25 | Pendências de cadastro e de checklist para paciente que saiu do tratamento | **Resolvido — DEC-71.** Só para paciente em tratamento. Depois de alta, óbito ou transferência, completar cadastro não muda a operação e só gera ruído. A pendência do evento continua |
| P-26 | Rotinas pesadas aos domingos | **Resolvido (DD-64, §13.1):** de madrugada, a partir das 02:00, com 10 minutos entre as chamadas; semanais e mensais aos domingos. A clínica não opera aos domingos (RNF-501, segunda a sábado). Rescan, conferência de hash e expurgo rodam no domingo de madrugada, sem competir com nada |
| P-27 | Âncora mensal como pendência da administração | **Resolvido — DEC-72.** Já prevista no DAS (A.2), mas ausente da matriz da ERS. Proposta: incluí-la na matriz, como DEC-72 |
| P-28 | Linha sem o mínimo do cadastro (nome, início e prontuário) | **Resolvido (§14.1).** Não é importada; vai às exceções, e a recepção cadastra pela tela, onde o rascunho ajuda. Coerente com a P-03 |
| P-29 | Tamanho da amostra da conferência | **Resolvido (§14.3).** 15 pacientes sorteados, cerca de 10% da base, com todos os campos conferidos. Se a amostra tiver divergência que não seja caso isolado, sorteiam-se mais 15 |
