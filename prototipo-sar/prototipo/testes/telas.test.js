// Testes de comportamento das telas do protótipo (jsdom). Rodar com: npm test
const { JSDOM } = require("jsdom");
const path = require("path");
async function abrir(arq) {
  const dom = await JSDOM.fromFile(path.join(__dirname, "..", arq), { runScripts: "dangerously", resources: "usable" });
  await new Promise(r => dom.window.addEventListener("load", r));
  return dom.window.document;
}
function ok(desc, cond) { console.log((cond ? "OK    " : "FALHA ") + desc); if (!cond) process.exitCode = 1; }
(async () => {
  let d;
  d = await abrir("cadastro.html");
  const salvar = d.querySelector('[data-acao="salvar-paciente"]');
  ok("cadastro: começa bloqueado (2 de 3 e CPF inválido)", salvar.disabled && d.querySelector('[data-contagem="minimo"]').textContent === "2");
  ok("cadastro: CPF inválido marcado", d.querySelector("#cpf").getAttribute("aria-invalid") === "true");
  const digitar = (id, v) => { const e = d.querySelector(id); e.value = v; e.dispatchEvent(new d.defaultView.Event("input", { bubbles: true })); };
  digitar("#inicio", "2026-09-30");
  ok("cadastro: com o mínimo mas CPF inválido, continua bloqueado", salvar.disabled);
  digitar("#cpf", "123.456.789-09");
  ok("cadastro: CPF válido libera o botão", !salvar.disabled && !d.querySelector("#cpf").hasAttribute("aria-invalid"));
  digitar("#cpf", "");
  ok("cadastro: CPF em branco é permitido", !salvar.disabled);
  digitar("#prontuario", "");
  ok("cadastro: sem prontuário, bloqueia de novo", salvar.disabled);
  const tels = (sel) => d.querySelectorAll(`${sel} [data-telefone]`).length;
  const listaPac = 'fieldset:not(:has([data-lista-contatos])) > [data-lista-telefones]';
  ok("cadastro: sem campo de instituição que encaminhou", !/encaminhou|CNES/i.test(d.body.textContent));
  ok("cadastro: começa com um telefone do paciente e um contato", tels(listaPac) === 1 && d.querySelectorAll("[data-lista-contatos] > [data-contato]").length === 1);
  d.querySelector('fieldset:not(:has([data-lista-contatos])) > [data-acao="adicionar-telefone"]').click();
  ok("cadastro: adicionar telefone do paciente", tels(listaPac) === 2);
  d.querySelector(`${listaPac} [data-telefone] [data-acao="remover-telefone"]`).click();
  ok("cadastro: remover telefone do paciente", tels(listaPac) === 1);
  d.querySelector('[data-acao="adicionar-contato"]').click();
  const contatos = d.querySelectorAll("[data-lista-contatos] > [data-contato]");
  ok("cadastro: adicionar contato já traz um telefone", contatos.length === 2 && contatos[1].querySelectorAll("[data-telefone]").length === 1);
  contatos[1].querySelector('[data-acao="adicionar-telefone"]').click();
  ok("cadastro: telefone do contato fica no contato, não no paciente", contatos[1].querySelectorAll("[data-telefone]").length === 2 && tels(listaPac) === 1);
  contatos[1].querySelector('[data-acao="remover-contato"]').click();
  ok("cadastro: remover contato", d.querySelectorAll("[data-lista-contatos] > [data-contato]").length === 1);

  d = await abrir("inicio.html");
  const S = (n) => d.querySelector(`[data-sessao="${n}"]`);
  const qtd = (n, z) => S(n).querySelector(`.quadro [data-contagem="${z}"]`).textContent;
  const momento = (v) => { const r = d.querySelector(`input[name="momento"][value="${v}"]`); r.checked = true;
    r.dispatchEvent(new d.defaultView.Event("change", { bubbles: true })); };
  const ev = (alvo, tipo) => alvo.dispatchEvent(new d.defaultView.Event(tipo, { bubbles: true, cancelable: true }));

  // 10:05 — primeiro turno terminou sem confirmação; segundo em preparação
  ok("10:05: primeiro turno aguardando confirmação", !S(1).hidden && S(1).dataset.estado === "vencida");
  ok("10:05: segundo turno em preparação, visível ao mesmo tempo", !S(2).hidden && S(2).dataset.estado === "preparacao");
  ok("10:05: nomes dos turnos em português, sem código de escala", /Primeiro turno/.test(S(1).querySelector("h2").textContent) &&
     !/1-seg|2-seg/.test(d.body.textContent));
  S(1).querySelector('[data-paciente="1"] [data-acao="mover"]').click();
  ok("10:05: marcar falta no primeiro turno pelo botão", qtd(1, "faltantes") === "3" && qtd(2, "faltantes") === "0");
  ok("10:05: resumo da sessão acompanha", S(1).querySelector('p [data-contagem="faltantes"]').textContent === "3");
  ev(S(2).querySelector('[data-paciente="101"]'), "dragstart");
  ev(S(2).querySelector('[data-zona="faltantes"]'), "dragover");
  ev(S(2).querySelector('[data-zona="faltantes"]'), "drop");
  ev(S(2).querySelector('[data-paciente="101"]'), "dragend");
  ok("10:05: arrastar no segundo turno registra ausência avisada", qtd(2, "faltantes") === "1");
  ok("10:05: confirmação do segundo turno ainda não aparece", S(2).querySelector('[data-acao="confirmar"]').hidden);
  S(1).querySelector('[data-acao="confirmar"]').click();
  ok("10:05: ao confirmar, o primeiro sai e o segundo assume", S(1).hidden && !S(2).hidden);
  ok("10:05: aviso de sessão confirmada", /Primeiro turno confirmado às 10:05/.test(d.querySelector("[data-aviso-confirmada]").textContent));

  // 09:15 — primeiro turno aberto com confirmação liberada
  momento("09:15");
  ok("09:15: primeiro turno com confirmação liberada", !S(1).hidden && S(1).dataset.estado === "liberada" &&
     !S(1).querySelector('[data-acao="confirmar"]').disabled);
  ok("09:15: segundo turno ainda não aparece", S(2).hidden);
  S(1).querySelector('[data-acao="confirmar"]').click();
  ok("09:15: confirmado, a tela mostra o segundo turno só para consulta", !S(2).hidden && S(2).dataset.estado === "futura");
  S(2).querySelector('[data-paciente="102"] [data-nome]').click();
  ok("09:15: sessão futura não permite mover cartões", qtd(2, "faltantes") === "1");

  // 05:30 — primeiro turno em preparação
  momento("05:30");
  ok("05:30: primeiro turno em preparação, sem botão de confirmar", S(1).dataset.estado === "preparacao" &&
     S(1).querySelector('[data-acao="confirmar"]').hidden);
  ok("05:30: etapa atual marcada", S(1).querySelector('[data-passo="preparacao"]').getAttribute("aria-current") === "step");
})();
