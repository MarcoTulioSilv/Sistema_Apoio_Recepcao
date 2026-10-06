# Fase 2 — Casos de Uso e Critérios de Aceitação

**Versão:** 1.0
**Data:** 14/09/2026
**Base:** requisitos funcionais v1.1 e modelo de domínio v1.0
**KA SWEBOK:** Software Requirements → Requirements Analysis

---

## 1. Como este documento está organizado

Dezoito casos de uso. Sete estão detalhados por completo — são os que têm fluxo alternativo real,
regra de negócio embutida ou risco de implementação. Os demais estão em forma resumida, porque
descrevê-los em detalhe produziria páginas sem decisão nenhuma dentro.

Cada critério de aceitação está escrito de modo a virar teste diretamente. Quando um critério não
puder ser verificado, ele não é critério — é intenção.

---

## 2. Atores

| Ator | Quem é |
|---|---|
| **Recepcionista** | Usuário principal. Cadastro, frequência, emissão de documentos |
| **Administração** | Tudo da recepção, mais relatórios completos e autorizações |
| **Visualizador** | Apenas consulta |
| **TI** | Usuários, configuração e backup. Sem acesso a dado de paciente |
| **Tempo** | Ator não humano: a passagem do horário abre a sessão de turno |

### 2.1 Um ator que não tem perfil

A enfermagem decide a escala (DEC-25), mas não está entre os quatro perfis (DEC-23). Na prática,
alguém da recepção ou da administração registra a decisão dela.

Isso funciona, e o modelo já prevê guardar que a origem da decisão é da enfermagem (RF-406). Mas
vale ser dito em voz alta: **quem digita não é quem decide**. Se um dia a enfermagem quiser alocar
direto, é um quinto perfil, não um ajuste de permissão.

---

## 3. Casos de uso detalhados

### UC-01 — Cadastrar paciente

**Ator:** recepcionista · **Prioridade:** essencial · **Requisitos:** RF-101 a 110, 201, 202, 301 a 303

**Pré-condição:** entrevista já realizada, ficha de papel preenchida em mãos.

**Fluxo principal**

1. A recepcionista abre o cadastro novo.
2. Transcreve os campos na ordem da ficha de papel.
3. O sistema valida CPF e CNS pelo dígito verificador e consulta o CEP em serviço externo, com cache local — ver §3.1.
4. A recepcionista acrescenta contatos, com nome e parentesco, e os telefones de cada um.
5. Informa a cobertura: SUS ou convênio nomeado.
6. Informa a escala, **se a enfermagem já a tiver definido**. O campo é opcional.
7. Salva.
8. O sistema cria o paciente e abre o período de tratamento. Havendo escala informada, cria a alocação com vigência a partir do início do tratamento; não havendo, o paciente fica em **sem alocação**.

**Fluxos alternativos**

| # | Situação | Comportamento |
|---|---|---|
| A1 | Falta algum dado | Salva assim mesmo. O paciente entra na lista de pendências com os campos faltantes nomeados |
| A2 | Nome, data de nascimento e nome da mãe coincidem com paciente existente | Alerta, mostra o cadastro existente e pede decisão. Não bloqueia. Registra a decisão em auditoria |
| A3 | Número de prontuário já em uso | Bloqueia. É invariante (INV-07) |
| A4 | CPF ou CNS com dígito inválido | Sinaliza e permite salvar, marcando o campo como pendente |
| A5 | Escala ainda não definida pela enfermagem | Paciente salvo em "sem alocação", visível na tela de pendências até ser alocado (UC-04) |
| A6 | A recepcionista precisa interromper o preenchimento | O que já foi digitado é guardado como **rascunho**. Ao voltar, ela retoma de onde parou |

**Pós-condição:** paciente existe, com período aberto, alocado ou em "sem alocação", e com
documentação pendente.

**Rascunho não é cadastro incompleto.** São dois estados diferentes e confundi-los seria erro de
projeto:

| | Rascunho | Cadastro incompleto |
|---|---|---|
| O paciente existe? | **Não.** É um formulário em andamento | **Sim** |
| Aparece na busca, nas escalas, nos relatórios? | Não | Sim |
| Gera pendência? | Não | Sim, com os campos faltantes nomeados |
| Como termina | A recepcionista salva, e vira paciente; ou descarta | Preenchendo o que falta |

O rascunho existe para a interrupção — o telefone tocou, um paciente chegou no balcão — e não para
o cadastro que ficou pela metade por falta de documento. Este segundo é o A1.

**Onde o rascunho fica.** No servidor, vinculado ao usuário, e não no navegador da estação. Duas
razões: a recepcionista pode retomar de outra máquina, e a sessão é bloqueada por inatividade
(RF-1003), o que descartaria um rascunho guardado só no cliente.

**E ele é dado sensível.** Um rascunho de cadastro contém nome e vínculo com a clínica — é dado de
saúde como qualquer outro (achado L-01). Fica sob o mesmo controle de acesso e a mesma auditoria do
cadastro, nunca num arquivo temporário solto. E precisa de prazo: rascunho abandonado indefinidamente
é dado pessoal guardado sem finalidade. Descarte automático com aviso prévio, conforme os artigos 15
e 16 da LGPD.

| # | Requisito |
|---|---|
| **RF-919** | Guardar automaticamente o preenchimento em andamento como rascunho, vinculado ao usuário, e retomá-lo quando ele voltar ao cadastro |
| **RF-920** | Descartar rascunhos automaticamente após prazo configurável, avisando antes, e permitir descarte manual |

**Nota.** Alocar no cadastro não transfere a decisão para a recepção. A enfermagem continua
definindo a escala (DEC-25); o que muda é o momento em que a recepção a registra — junto com o
cadastro, quando já souber, em vez de numa segunda operação. O registro continua guardando que a
origem da decisão é da enfermagem.

**Critérios de aceitação**

- Dado um CPF com dígito verificador inválido, quando salvar, então o cadastro é criado e o CPF aparece na lista de pendências.
- Dado um número de prontuário já existente, quando salvar, então o sistema recusa e informa qual paciente o utiliza.
- Dada a coincidência da tríade com paciente existente, quando salvar, então o sistema exibe o cadastro coincidente e exige confirmação explícita antes de prosseguir.
- Dado um cadastro salvo sem escala informada, então o paciente aparece com situação "sem alocação" e figura na tela de pendências.
- Dado um cadastro salvo com escala informada, então a alocação é criada com vigência a partir da data de início do tratamento, e o paciente já aparece nas sessões daquela escala.
- Dado um cadastro recém-criado, então os três documentos de cadastro constam como pendentes.
- Dado um preenchimento interrompido, quando a recepcionista reabre o cadastro novo, então o rascunho é oferecido para retomada com os campos já digitados.
- Dado um rascunho em andamento, então o paciente não aparece em buscas, escalas, relatórios nem na lista de pendências.
- Dado um rascunho criado numa estação, quando a recepcionista entra em outra, então o rascunho está disponível.
- Dado um rascunho que atingiu o prazo de descarte, então ele é eliminado e o usuário é avisado antes.
- Dada a ordem de campos da tela, então ela corresponde à ordem da ficha de papel revisada.

---

### UC-05 — Lançar e confirmar a frequência do turno

**Ator:** recepcionista · **Prioridade:** essencial · **Requisitos:** RF-501, 502, 913

**Pré-condição:** chegou o dia e o horário de uma escala. A sessão foi aberta pelo sistema.

**Fluxo principal**

1. A tela inicial exibe o card do turno vigente, com os pacientes alocados naquela escala.
2. Todos aparecem como presentes.
3. Ao fim do turno, com a ficha assinada em mãos, a recepcionista marca as ausências.
4. Confirma a sessão.
5. O sistema registra quem confirmou e quando, e a sessão sai da lista de pendências.

**Fluxos alternativos**

| # | Situação | Comportamento |
|---|---|---|
| A1 | Paciente de fora da escala comparece | Ver UC-06 |
| A2 | A sessão não é confirmada no dia | Permanece aberta e passa a figurar em destaque na tela inicial, como pendência de urgência, sem prazo |
| A3 | Vários turnos pendentes | Listados do mais antigo para o mais recente, com a quantidade visível |
| A4 | Confirmação de turno de data anterior | Operação idêntica à do dia corrente. Não há limite de dias |

**Pós-condição:** sessão confirmada; presenças e ausências registradas.

**Critérios de aceitação**

- Dada uma sessão aberta e não confirmada, então ela aparece em destaque na tela inicial e não é contabilizada como frequência lançada.
- Dada uma sessão aberta sem nenhuma interação, quando o turno termina, então nenhuma presença é considerada registrada.
- Dada a confirmação da sessão, então o sistema grava o usuário e o instante da confirmação.
- Dados três turnos pendentes, então são exibidos do mais antigo para o mais recente, com a contagem.
- Dada uma sessão de quatro dias atrás, quando confirmada, então o sistema aceita sem exigir autorização adicional.

---

### UC-06 — Acrescentar paciente adicional à sessão

**Ator:** recepcionista · **Prioridade:** essencial · **Requisitos:** RF-503 a 506, 916 a 918

**Pré-condição:** sessão de turno aberta.

**Fluxo principal**

1. A recepcionista escolhe acrescentar um adicional à sessão.
2. Busca o paciente por nome, CPF ou CNS.
3. Ao selecionar, o sistema exibe **as ausências desse paciente no mês em curso**.
4. A recepcionista relaciona a presença a uma das ausências.
5. O sistema forma a compensação. A presença é classificada como reposição.

**Fluxos alternativos**

| # | Situação | Comportamento |
|---|---|---|
| A1 | O paciente não tem ausências no mês | A presença é registrada como extra provisória |
| A2 | O paciente com extra provisória falta depois, no mesmo mês | A extra é consumida pela ausência e passa a reposição, automaticamente |
| A3 | Mais de uma ausência e mais de uma presença pendente | Pareamento cronológico automático, exibido e reversível |
| A4 | A extra faz o paciente passar de quatro no mês | Sinaliza e registra. **Não bloqueia** |
| A5 | Troca planejada, com declaração assinada | A compensação é criada antes, e a declaração é emitida a partir dela |

**Pós-condição:** presença registrada e classificada, provisoriamente, até o fechamento do mês.

**Critérios de aceitação**

- Dado um paciente com uma ausência no mês, quando acrescentado a outra sessão e relacionado a ela, então a presença é reposição e a ausência deixa de contar como não compensada.
- Dado um paciente sem ausências, quando acrescentado, então a presença é extra.
- Dada uma extra registrada e uma ausência posterior no mesmo mês, então a extra passa a reposição sem intervenção do operador.
- Dada a compensação automática, então o sistema exibe qual ausência foi ligada a qual presença e permite desfazer a ligação.
- Dada uma presença fora da escala em 31 de um mês e uma ausência em 1º do seguinte, então **não** há compensação.
- Dada a quinta extra do mês, quando registrada, então o sistema registra a presença e exibe o aviso de excesso.

---

### UC-07 — Registrar evento do paciente

**Ator:** recepcionista · **Prioridade:** essencial · **Requisitos:** RF-601 a 607

**Fluxo principal**

1. A recepcionista escolhe o paciente e o tipo de evento.
2. Informa a data e, quando aplicável, o local.
3. Salva.
4. O sistema encerra o período de tratamento e passa o paciente a inativo ou falecido.
5. O evento fica pendente de documento comprobatório.

**Fluxos alternativos**

| # | Situação | Comportamento |
|---|---|---|
| A1 | Documento comprobatório ainda não disponível | Situação normal. O evento permanece pendente até o anexo |
| A2 | Data do evento anterior ao início do período | Recusa. Incoerência cronológica |
| A3 | Paciente já falecido | Recusa. INV-01 |
| A4 | Desistência | O comprovante esperado é o termo de consentimento de interrupção, que o próprio sistema emite (UC-09) |

**Pós-condição:** período encerrado; paciente fora das escalas; evento pendente de documento.

**Critérios de aceitação**

- Dado um evento registrado, então o período de tratamento fica encerrado na data informada.
- Dado um óbito registrado, então nenhuma presença, evento ou documento pode ser criado com data posterior.
- Dado um evento sem documento anexado, então ele aparece como pendente, e a pendência é do evento, não do cadastro do paciente.
- Dado um paciente com evento registrado, então ele deixa de aparecer nas sessões de turno seguintes.
- Dada a anexação do comprovante, então a pendência do evento se encerra.

---

### UC-08 — Digitalizar e anexar documento

**Ator:** recepcionista · **Prioridade:** essencial (a extração automática é desejável, ver §5) · **Requisitos:** RF-701 a 711

**Fluxo principal**

1. A recepcionista posiciona o documento no scanner e inicia a captura.
2. O sistema valida tipo e tamanho do arquivo.
3. Grava em quarentena.
4. Executa a varredura antimalware.
5. Reconstrói o arquivo por re-renderização.
6. Extrai os dados legíveis.
7. Apresenta os dados para conferência, destacando os de baixa confiança.
8. A recepcionista confere, corrige e confirma.
9. O sistema armazena o documento reconstruído e grava apenas os campos confirmados.

**Fluxos alternativos**

| # | Situação | Comportamento |
|---|---|---|
| A1 | Tipo de arquivo fora da lista permitida | Recusa antes da quarentena |
| A2 | Varredura reprova | Bloqueia, registra em log e informa. O arquivo não é armazenado |
| A3 | Campo com dígito verificador reprovado | Apresentado em branco para preenchimento manual, nunca como confirmado |
| A4 | Extração indisponível ou de baixa qualidade | O sistema sinaliza e oferece **re-escanear**. A recepcionista reposiciona o documento e repete a captura |
| A5 | Re-escaneamento | A captura pendente é descartada e o fluxo recomeça do passo 1. Não gera versão, porque nada foi armazenado ainda |
| A6 | A recepcionista opta por seguir sem re-escanear | O documento é armazenado como está e os campos ficam para digitação manual |

**Pós-condição:** documento armazenado, íntegro, classificado, imutável e auditável.

**Nota sobre o re-escaneamento.** Leitura ruim quase sempre vem de captura ruim — documento torto,
contraste baixo, página deslocada. Oferecer o re-escaneamento no momento da conferência resolve a
causa em vez de empurrar o problema para a digitação manual, e custa menos que corrigir campo por
campo.

A imutabilidade do documento (INV-06) **não se aplica aqui**: ela vale a partir do armazenamento
definitivo. Antes disso a captura está em quarentena, ainda não é documento, e descartá-la é
descarte de arquivo temporário, não alteração de registro. Confundir os dois criaria versões
inúteis de documentos que nunca chegaram a existir.

O descarte precisa ser efetivo: a captura rejeitada sai da quarentena. Caso contrário a área de
quarentena acumula imagens de documentos sensíveis que ninguém rastreia.

**Critérios de aceitação**

- Dado um arquivo com extensão permitida mas conteúdo de outro tipo, quando enviado, então é recusado pela verificação de assinatura binária.
- Dado um arquivo reprovado na varredura, então ele não existe no armazenamento definitivo, e o bloqueio consta no log.
- Dado o arquivo de teste EICAR em homologação, então a varredura o detecta e recusa.
- Dado um CNS lido com dígito verificador inválido, então o campo é apresentado vazio e sinalizado.
- Dada uma extração de baixa qualidade, então o sistema sinaliza e oferece re-escanear antes de concluir.
- Dado um re-escaneamento, então a captura anterior é removida da quarentena e nenhuma versão é criada.
- Dada a opção de seguir sem re-escanear, então o documento é armazenado e os campos ficam pendentes de digitação.
- Dado um documento já armazenado, quando alterado, então o sistema cria nova versão e preserva a anterior com o motivo.
- Dada a consulta a um documento, então a leitura é registrada na trilha de auditoria.
- Dado um documento com menos de vinte anos, quando solicitada a exclusão, então o sistema recusa.

---

### UC-11 — Emitir o relatório mensal de frequência

**Ator:** administração · **Prioridade:** essencial · **Requisitos:** RF-906, 913, 916

**Pré-condição:** o mês terminou.

**Fluxo principal**

1. A administração escolhe o mês.
2. O sistema verifica se todas as sessões daquele mês estão confirmadas.
3. Estando, calcula por paciente: sessões previstas, realizadas, ausências não compensadas, reposições e extras definitivas.
4. Apresenta o balanço.

**Fluxos alternativos**

| # | Situação | Comportamento |
|---|---|---|
| A1 | Há sessão não confirmada no mês | **Não emite.** Informa quantas faltam e quais |
| A2 | Mês em curso | Não existe relatório mensal. Há consulta de prévia, rotulada como tal |
| A3 | O mês foi alterado após o fechamento | Emite com a marca de alteração, data, responsável e motivo |

**Critérios de aceitação**

- Dada uma sessão não confirmada dentro do mês, quando solicitado o relatório, então ele não é emitido e o sistema informa a data e a escala das sessões pendentes.
- Dado um mês com todas as sessões confirmadas, então o relatório é emitido.
- Dado um paciente admitido no dia 10, então as sessões previstas contam apenas a partir dessa data.
- Dado um paciente que mudou de escala no meio do mês, então as previstas usam a alocação vigente em cada data.
- Dado que a clínica opera em feriados, então nenhum dia do calendário é descontado.
- Dado um mês alterado após o fechamento, então todo relatório daquele período exibe a marca de alteração.

---

### UC-14 — Corrigir registro após a confirmação

**Ator:** administração · **Prioridade:** essencial · **Requisitos:** RF-606, 915, e §7.13 do modelo

**Fluxo principal**

1. A administração localiza o registro a corrigir.
2. Solicita a alteração.
3. O sistema exige senha da administração.
4. A administração informa o motivo.
5. O sistema aplica a alteração e registra em auditoria o antes, o depois, **o autor da operação, quem autorizou**, o instante e o motivo.

**Autor e autorizador são papéis distintos.** Na prática, a recepcionista está logada e o
administrador digita a senha dele para liberar — são duas pessoas na mesma operação. Registrar só
uma perde metade da informação: ou não se sabe quem mexeu, ou não se sabe quem permitiu.

Uma recomendação que decorre disso: a autorização deve ser feita **pelo próprio administrador
digitando a senha**, não pela senha ditada a quem está operando. Senha compartilhada transforma o
registro de autorização em ficção — o nome no log passa a ser o de alguém que pode nem estar na
clínica naquele momento.

**Alcance:** reabrir sessão confirmada, alterar presença de sessão confirmada, alterar alocação cuja
vigência alcance sessões confirmadas, corrigir ou remover evento.

**Fluxos alternativos**

| # | Situação | Comportamento |
|---|---|---|
| A1 | A alteração afeta um mês já fechado | O mês recebe a marca de alterado após o fechamento |
| A2 | A correção remove um óbito | O período reabre e o paciente volta a ativo, por derivação, sem rotina de reversão |
| A3 | A alteração de alocação reclassifica presenças | Ocorre automaticamente. A marca de alteração torna o efeito visível |

**Critérios de aceitação**

- Dada uma sessão confirmada, quando solicitada alteração, então o sistema exige senha da administração e motivo antes de aplicar.
- Dada qualquer alteração aplicada, então a auditoria contém o valor anterior, o novo, o autor da operação, **quem autorizou**, o instante e o motivo.
- Dado que o autor e o autorizador são pessoas diferentes, então ambos constam do registro, identificados separadamente.
- Dada a remoção de um evento de óbito, então o paciente volta a aparecer como ativo sem qualquer outra intervenção.
- Dada a alteração de uma alocação passada, então as presenças alcançadas são reclassificadas e o mês é marcado como alterado.


### 3.1 Consulta de CEP — estratégia

A validação de CEP muda de base local para **consulta em serviço externo com cache local**. Três
razões, sendo a segunda inesperada.

**A base local envelhece e ninguém a atualiza.** Manter uma cópia do diretório de endereços exige
uma rotina de atualização que, num sistema de clínica, não vai acontecer. Serviço consultado está
sempre corrente.

**O serviço devolve o código IBGE de sete dígitos.** É o mesmo campo que o legado guarda com seis,
sem o dígito verificador (ND-46). A consulta que valida o CEP entrega junto a conversão que
precisaríamos fazer de outro jeito — logradouro, bairro, município, UF, código IBGE e DDD numa
resposta só.

**O endereço vem estruturado.** Logradouro e bairro preenchidos pela consulta reduzem digitação e
eliminam a divergência de grafia que o perfilamento encontrou no legado.

**Opções.** Há serviços gratuitos e sem cadastro para essa consulta. <cite index="3-1">O ViaCEP mantém base declarada de mais de 1,6 milhão de CEPs, atualizada em setembro de 2026</cite>, e a BrasilAPI agrega múltiplas fontes. <cite index="6-1">A prática recomendada em 2026 é combinar duas fontes com fallback, porque depender de uma única API em produção é aceitar que ela vai cair em algum momento</cite>.

**Não há limite numérico publicado.** A documentação do ViaCEP não divulga teto de requisições por
minuto, não documenta retorno 429 nem cabeçalhos de controle de uso. O que existe é uma advertência:
(cite index="22-1">uso massivo para validação de bases de dados locais poderá bloquear o acesso automaticamente por tempo indeterminado</cite>. (cite index="7-1">A BrasilAPI, no mesmo sentido, pede que não se use crawling ou varredura completa e que o volume tenha a natureza de uma pessoa real requisitando um dado</cite>.

Isso é mais restritivo do que um limite numérico, não menos. Com um teto publicado, dá para
engenhar em torno dele. Sem teto, o único critério é parecer com uso humano — e a penalidade
anunciada é bloqueio por tempo indeterminado do endereço de onde partem as consultas, que aqui é o
da clínica inteira.

**E a validação em massa é exatamente o caso advertido.** Rodar os 146 CEPs da carga contra o
serviço é, literalmente, "validação de base de dados local". Mesmo espaçado, é o padrão que a
advertência descreve.

### 3.2 Decisão: nada de validação em massa

A alternativa que você propôs é a correta, e não é um consolo — é melhor que a validação em lote.

| Momento | O que acontece |
|---|---|
| **Carga inicial** | Os CEPs entram como estão na planilha, classificados por qualidade: válido específico, válido genérico do município, inválido ou ausente. **Nenhuma consulta externa** |
| **Cadastros novos** | Consulta ao serviço no momento do preenchimento. Uma consulta por semana |
| **Pacientes migrados** | A lista de pendências mostra quem está com CEP não verificado. Quando o paciente comparece e a recepção abre o cadastro, o sistema consulta **aquele** CEP |

O terceiro ponto é o que resolve a migração sem nenhum lote: os pacientes vêm três vezes por semana.
Em duas ou três semanas de operação normal, os 146 CEPs terão sido consultados — alguns por dia,
disparados por uma pessoa abrindo uma tela. É indistinguível de uso humano porque **é** uso humano.

O mecanismo de remediação progressiva, criado para outra coisa, faz a validação da base de graça e
sem risco de bloqueio.

### 3.3 Desenho recomendado

| Elemento | Definição |
|---|---|
| Fonte | Primária com fallback para uma segunda, porque depender de uma só é aceitar que ela vai cair |
| Cache | Local e persistente. CEP muda pouco; consulta repetida do mesmo CEP não sai para a rede |
| Validação prévia | Conferir os 8 dígitos antes de chamar. (cite index="22-1">CEP com formato inválido retorna 400, e CEP inexistente retorna erro igual a true</cite> — a checagem local evita a chamada inútil |
| Indisponibilidade | O cadastro **nunca é bloqueado**. Sem resposta, digita-se à mão e o CEP fica como não verificado, na lista de pendências |
| Dado enviado | **Apenas o CEP.** Nunca nome, CPF ou CNS. Um CEP isolado não identifica ninguém, e assim a consulta não conflita com DEC-11 |

A regra da indisponibilidade segue o princípio do §7.9 do modelo: o sistema informa, não impede. Um
cadastro que não pode ser salvo porque um serviço externo caiu seria o pior resultado possível para
uma recepção que hoje resolve isso com uma planilha.

### 3.4 Dois ganhos de brinde

**O código IBGE vem pronto.** (cite index="22-1">A resposta traz logradouro, complemento, unidade, bairro, localidade, UF, estado, região, código IBGE, DDD e SIAFI</cite> — o IBGE com os sete dígitos que o legado guarda com seis. A conversão que exigiria uma tabela oficial sai na mesma chamada.

**Busca por logradouro.** (cite index="22-1">O serviço também pesquisa CEPs a partir de UF, cidade e logradouro, com no mínimo três caracteres em cada e limite de 50 resultados</cite>. Resolve o caso do paciente que não sabe o próprio CEP, que hoje provavelmente termina em CEP genérico do município — a origem de parte do problema encontrado no legado.

**Nota sobre a alternativa local:** (cite index="22-1">o ViaCEP declara que não distribui nem comercializa bases de dados</cite>. Se um dia a base local voltar a ser necessária, ela terá de vir de outra origem.

---

---

## 4. Casos de uso resumidos

| ID | Caso de uso | Ator | Essência | Prioridade |
|---|---|---|---|---|
| UC-02 | Localizar paciente | Recepcionista | Busca por nome, com desempate pela tríade | Essencial |
| UC-03 | Atualizar cadastro | Recepcionista | Alteração de dados, com auditoria. Atende a atualização semestral e as espontâneas | Essencial |
| UC-04 | Alocar paciente em escala | Recepcionista | Registra a decisão da enfermagem, com vigência. Inclui distribuição em massa | Essencial |
| UC-09 | Emitir documento parametrizado | Recepcionista | Sete documentos, com cabeçalho da configuração e data por extenso | Essencial |
| UC-10 | Emitir crachá | Recepcionista | Foto, logotipo, nome do paciente e nome da mãe | Desejável |
| UC-12 | Gerar relatórios de cadastro | Administração | Cidade, convênio, faixa etária, sexo, eventos, entradas. Com período | Essencial |
| UC-13 | Exportar relatório | Administração | PDF e planilha, com registro da exportação em auditoria | Desejável |
| UC-15 | Administrar usuários | TI | Criação, perfil, inativação. Sem acesso a dado de paciente | Essencial |
| UC-16 | Atender requisição de titular | Administração | Registro do pedido, do prazo e do desfecho | Essencial |
| UC-17 | Executar a carga inicial | TI | Importação, conciliação, relatório de exceções, conferência amostral | Essencial |
| UC-18 | Consultar pendências | Todos os perfis | Lista única por perfil. Recepção: cadastro incompleto, documento faltante, evento sem comprovante, turno não confirmado, sessão extra além do limite, possível duplicidade, pedido de titular. Demais perfis conforme a §9.1 da modelagem de ameaças (ND-97) | Essencial |

**UC-18 merece nota.** As pendências nasceram espalhadas — cadastro, documento, evento, turno. Para
a recepção, é uma fila de trabalho só. Reuni-las numa tela é o que faz a estratégia de remediação
progressiva funcionar de fato; espalhadas por quatro telas, elas seriam ignoradas.

---

## 5. Escopo de entrega

**Decisão:** o sistema será construído por inteiro, conforme desenhado, testado e validado antes de
ir para produção. A coordenação não tem restrição de prazo, então não há faseamento de escopo.

Isso elimina os problemas de entrega parcial: nenhuma operação fica meio manual e meio no sistema,
não há treinamento em duas rodadas, e a documentação descreve um sistema só.

Três pontos continuam merecendo atenção, e nenhum deles é sobre prazo.

### 5.1 Validar cedo, entregar de uma vez

Entrega única não precisa significar validação única. O maior risco remanescente do projeto é de
uso, não de função: a tela de cadastro precisa espelhar a ficha de papel, e a de frequência precisa
ser lançável em poucos cliques. Isso só se descobre com a recepcionista mexendo.

Sem prazo apertado, dá para fazer o que normalmente não dá: mostrar as telas de cadastro e de
frequência à recepção **durante** a construção, ajustar, e só então seguir. O custo de mudar uma
tela em construção é uma fração do custo de mudá-la depois de treinada.

### 5.2 A extração de dados não deve travar a entrega

Com escopo integral, o item de maior risco técnico passa a estar dentro do pacote que precisa
funcionar para implantar. Isso muda a natureza do risco: antes ele podia ficar para depois, agora
ele gateia a entrega.

**Mitigação:** mantê-lo isolado e desativável. Se a leitura automática não atingir qualidade útil, o
sistema entra em produção com ela desligada e a recepcionista digita os campos, como faz hoje. A
digitalização segura não depende dela.

O que não pode acontecer é a extração virar pré-requisito de funcionamento do módulo de documentos.
Se a arquitetura deixar isso acontecer, um recurso acessório passa a poder adiar o projeto inteiro.

### 5.3 As dependências externas viram caminho crítico

Sem faseamento, webcam, logotipo e decisão sobre a impressora deixam de ser pendências do crachá e
passam a ser pendências da entrega. Elas custam pouco e demoram o que demorar — vale resolvê-las já,
para não descobrir na véspera da homologação que falta um equipamento.

### 5.4 Ordem de construção sugerida

Não é priorização de escopo, é sequência técnica. A ordem importa porque algumas coisas são caras de
acrescentar depois.

| # | Bloco | Por que nesta posição |
|---|---|---|
| 1 | Acesso, perfis, auditoria e configuração | Auditoria acrescentada depois é retrabalho em tudo que já foi escrito |
| 2 | Cadastro, contatos, cobertura | Base de todo o resto |
| 3 | Escala, alocação, frequência, compensação | Núcleo operacional e a parte com mais regra derivada |
| 4 | Documentos, com pipeline de segurança | Independente, e a extração entra isolada aqui |
| 5 | Emissão parametrizada e crachá | Depende do cadastro e da configuração |
| 6 | Relatórios e exportação | Depende de tudo acima existir com dado real |
| 7 | Carga inicial | **Por último.** Depende de todo o modelo estar estável. Migrar contra um modelo que ainda muda significa migrar duas vezes |
| 8 | Homologação completa e validação com a equipe | Antes da produção |

### 5.5 Fora deste ciclo

Nada foi adiado. O que está fora está fora por escopo (§14 do documento de requisitos).

---

## 6. Dependências externas

| Dependência | Bloqueia | Situação |
|---|---|---|
| Webcam | UC-10 | Ainda não adquirida |
| Impressora colorida, se a foto do crachá precisar de qualidade | UC-10 | A decidir |
| Ficha de papel revisada | UC-01, ordem dos campos | A revisar com a gestão |
| Logotipo em arquivo | UC-10 | A fornecer |
| Dados institucionais confirmados | UC-09 | A confirmar, sem o fax |
| Títulos próprios para os documentos | UC-09 | A definir |
| Saída de internet a partir do servidor | UC-01, consulta de CEP | **Confirmada** |
| Tabela de municípios do IBGE | UC-01, naturalidade | A obter — a consulta de CEP cobre a residência, mas não a naturalidade de outros estados |

---

## 7. Próximas saídas da Fase 2

| Ordem | Saída |
|---|---|
| 1 | Catálogo de requisitos não funcionais pela ISO/IEC 25010, com cenários de atributo de qualidade |
| 2 | Consolidação das bases legais por operação |
| 3 | Modelagem de ameaças (STRIDE) e de privacidade (LINDDUN) sobre o módulo de documentos |
| 4 | Análise de viabilidade e fechamento da Fase 2 |

---

*Rastreabilidade: os 18 casos de uso cobrem os requisitos RF-101 a RF-918. Nenhum requisito aprovado ficou sem caso de uso.*
