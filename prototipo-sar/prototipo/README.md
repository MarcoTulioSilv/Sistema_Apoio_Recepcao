# SAR — protótipo das telas da recepção

Telas estáticas para validar com a recepcionista e servir de ponto de partida na construção.
Dados fictícios; cena de quarta-feira, 30/09/2026.

## Abrir no navegador

Basta abrir `index.html`. Se o navegador não carregar a fonte ao abrir direto do disco, sirva a pasta:

```bash
python -m http.server 8000
# e acesse http://localhost:8000
```

## Telas

| Arquivo | Tela | Interação |
|---|---|---|
| `inicio.html` | Início: as sessões do dia no ciclo em preparação → aberta → confirmada, com presentes e faltantes (DD-76) | Clicar ou arrastar o cartão; confirmar a sessão; simulador de horário (05:30, 09:15, 10:05), só no protótipo |
| `cadastro.html` | Novo cadastro, com telefones do paciente e contatos | Mínimo para salvar (P-03), conferência do CPF (DD-22), adicionar e remover telefones e contatos |
| `componentes.html` | Guia de componentes: cores com contraste medido, tipografia, medidas, componentes com seus estados e as regras de construção | Exemplos vivos com o código de cada um |
| `pendencias.html` | Pendências por prioridade (§11 do DDS) | — |

## Estrutura

```
src/sar.css          Fonte do CSS: tokens (@theme) e componentes da casa (@utility)
static/css/sar.css   CSS gerado pelo Tailwind — não editar à mão
static/fonts/        Atkinson Hyperlegible, servida localmente (licença OFL)
static/js/sar.js     Comportamento, sem nenhum código inline
testes/              Testes de comportamento com jsdom
```

## Comandos

```bash
npm install          # Tailwind e jsdom
npm run css          # gera static/css/sar.css a partir de src/sar.css
npm run css:watch    # regenera a cada alteração
npm test             # 28 verificações de comportamento
```

## Nomes dos turnos

Na interface, os turnos são **primeiro, segundo e terceiro** (DD-75). Os códigos de escala (1-seg, 1-ter…)
aparecem só nas telas de escala da enfermagem; no banco e no código, nada muda.

## Regras que já seguem a produção

- **CSP estrita (DD-09):** nenhum `style=`, nenhum `<script>` inline, nenhum `onclick=`, nenhum recurso
  externo. Fonte e CSS servidos pelo próprio servidor.
- **Estado visual só por atributo:** `aria-pressed`, `aria-invalid` e `disabled` mudam a aparência
  pelo CSS; o JavaScript só troca atributos.
- **Acessibilidade:** botões e campos reais, rótulos ligados aos campos, alvos de pelo menos 44 px,
  foco visível, cores que diferem também em luminosidade e sempre com texto.

## Na construção (Macroentrega IV)

- O cabeçalho e o menu viram `base.html` do Jinja2; cada tela vira um modelo que herda dele.
- `src/sar.css` e a pasta `static/` vão para o pacote `sar/web/` como estão.
- O comportamento de `sar.js` passa para o servidor (htmx) e para componentes Alpine no build CSP.
  As regras continuam valendo no servidor, que é quem decide: o JavaScript só adianta o aviso.
