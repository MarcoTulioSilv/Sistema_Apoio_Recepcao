# Roteiro da cronometragem do cadastro e da localização de paciente

**Objetivo.** Medir, com uma pessoa e um cronômetro, o tempo de um cadastro completo (RNF-403: menos de
5 minutos, contra 15 hoje) e o de localizar um paciente (RNF-404: menos de 15 segundos, contra 3 minutos
hoje). A medição oficial é com a recepcionista, na homologação (PT §6.5); este roteiro serve para ensaiar
antes, no ambiente de desenvolvimento, e é o mesmo que será usado lá.

**Duração estimada:** 20 minutos.

**Regra do ensaio:** só dados fictícios — a ficha abaixo foi inventada. Nunca use a ficha de um paciente real.

---

## 1. Preparação

1. Suba o SAR no ambiente de desenvolvimento, com o banco migrado (`docs\comandos.md`, seções 3 e 4).
2. Entre com um usuário da **administração** e inclua o convênio **Ipasgo** em **Convênios**, se ainda
   não existir. Saia.
3. Entre com um usuário da **recepção**. Deixe a tela **Início** aberta.
4. Imprima ou deixe ao lado a ficha fictícia da seção 2. Quem cronometra é outra pessoa, ou o cronômetro
   do celular.

## 2. Ficha fictícia

| Campo | Valor |
|---|---|
| Nome completo | Maria Aparecida Fontes Fictício |
| Prontuário | E-1015 (no segundo ensaio, E-1016; o prontuário não pode repetir) |
| Início do tratamento | 01/10/2026 |
| Data de nascimento | 12/03/1958 |
| Sexo | Feminino |
| Nome da mãe | Joana Fontes Fictício |
| CPF | 529.982.247-25 (no segundo ensaio, deixe em branco: CPF também não repete) |
| Cartão do SUS (CNS) | em branco |
| RG e órgão | 1234567, SSP/GO |
| Naturalidade | GO, Rio Verde |
| CEP | 75800-000 (se a consulta estiver fora do ar, digite o endereço abaixo) |
| Logradouro, número, complemento | Rua Fictícia, 120, Casa 2 |
| Bairro, município | Centro, Jataí |
| Cobertura | Convênio Ipasgo, carteirinha 0012345678 |
| Telefones do paciente | (64) 99999-0001 celular; (64) 3631-0002 recado |
| Contato | José Fontes Fictício, filho ou filha, (64) 98888-0003 celular |

## 3. Cadastro completo (RNF-403)

1. **Dispare o cronômetro** ao clicar em **Novo cadastro**.
2. Preencha a ficha inteira, na ordem da tela, lendo da ficha em papel.
3. Clique em **Salvar paciente**. **Pare o cronômetro** quando a ficha do paciente abrir com o aviso
   "Paciente cadastrado".
4. Anote o tempo e qualquer hesitação: campo que não achou, mensagem que não entendeu, clique a mais.

## 4. Localizar paciente (RNF-404)

1. Volte à tela **Início**.
2. **Dispare o cronômetro** ao clicar em **Pacientes**.
3. Digite o começo do nome ("Maria Apa") até o paciente aparecer na lista e clique em **Abrir ficha**.
4. **Pare o cronômetro** quando a ficha abrir.
5. Repita buscando pelo prontuário e pelo começo do CPF.

## 5. Registro

| Ensaio | Data | Quem digitou | Cadastro completo | Localizar (nome) | Localizar (prontuário) | Observações |
|---|---|---|---|---|---|---|
| 1 | 16/10/2026 | Ensaio em desenvolvimento | 4 min 32 s | | | CEP geral 75800-000 não trouxe Jataí; município só por rolagem na lista |
| 2 | | | | | | |

**Aprovado quando:** cadastro completo abaixo de 5 minutos e localização abaixo de 15 segundos, nos dois
ensaios. Hesitações anotadas viram ajuste de tela antes da homologação, mesmo com o tempo dentro da meta.

## 6. Depois do ensaio

Os pacientes fictícios ficam no banco de desenvolvimento. Para tirá-los, peça a anulação na ficha de cada
um (a administração aprova na hora): os dados pessoais são apagados e o prontuário fica livre (DD-89).
