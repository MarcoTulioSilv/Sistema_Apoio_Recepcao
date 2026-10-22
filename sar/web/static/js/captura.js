/* SAR — digitalização pelo agente da estação (DDS §8.5, DD-98). Sem script nem estilo inline (DD-09).
 * 1. Abre a ingestão no servidor (id e token de uso único).
 * 2. Chama o agente no loopback com o id, o token e onde está o papel; o agente digitaliza e envia as páginas direto ao
 *    servidor, autenticado pelo token, e conclui a ingestão.
 * 3. Acompanha a ingestão pelo servidor, a cada 2 s, até a conferência ou a recusa.
 * As funções de abrir e acompanhar ficam em window.SARCaptura, para o módulo da câmera (camera.js).
 */
(function () {
  "use strict";

  const INTERVALO = 2000;
  const SEM_AGENTE =
    "O programa de digitalização não respondeu nesta estação. Confira se ele está aberto (ícone perto do relógio) " +
    "ou chame o TI.";

  async function abrir(form, extra) {
    const dados = new FormData(form);
    Object.entries(extra || {}).forEach(([chave, valor]) => dados.set(chave, valor));
    const resposta = await fetch(form.action, { method: "POST", body: dados, credentials: "same-origin" });
    const corpo = await resposta.json().catch(() => ({}));
    if (!resposta.ok) throw new Error(corpo.erro || "Não foi possível começar a digitalização.");
    return corpo;
  }

  function acompanhar(regiao, url) {
    let parado = false;
    async function atualizar() {
      if (parado) return;
      const resposta = await fetch(url, { headers: { "X-SAR-Automatica": "1" }, credentials: "same-origin" });
      if (resposta.ok) {
        regiao.innerHTML = await resposta.text();
        ligarCancelar(regiao);
        if (regiao.querySelector("[data-final]")) {
          parado = true;
          return;
        }
      }
      setTimeout(atualizar, INTERVALO);
    }
    atualizar();
    return () => {
      parado = true;
    };
  }

  function ligarCancelar(regiao) {
    const form = regiao.querySelector("form[data-cancelar]");
    if (!form || form.dataset.ligado) return;
    form.dataset.ligado = "1";
    form.addEventListener("submit", async (evento) => {
      evento.preventDefault();
      const resposta = await fetch(form.action, { method: "POST", credentials: "same-origin" });
      if (resposta.ok) regiao.innerHTML = await resposta.text();
    });
  }

  async function chamarAgente(agente, ingestao, papel) {
    let resposta;
    try {
      resposta = await fetch(`${agente}/capturar`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ingestao: ingestao.id, token: ingestao.token, papel }),
      });
    } catch {
      throw new Error(SEM_AGENTE);
    }
    const corpo = await resposta.json().catch(() => ({}));
    if (!resposta.ok) throw new Error(corpo.mensagem || SEM_AGENTE);
    return corpo;
  }

  window.SARCaptura = { abrir, acompanhar };

  const form = document.getElementById("captura");
  if (!form || !form.dataset.agente) return;
  const mensagem = form.querySelector("[data-mensagem]");
  const botao = form.querySelector("[data-digitalizar]");
  const regiao = document.getElementById("situacao");
  let parar = null;

  form.addEventListener("submit", async (evento) => {
    evento.preventDefault();
    if (!form.reportValidity()) return;
    mensagem.textContent = "";
    botao.disabled = true;
    if (parar) parar();
    try {
      const ingestao = await abrir(form);
      parar = acompanhar(regiao, ingestao.situacao);
      await chamarAgente(form.dataset.agente, ingestao, form.elements.papel.value);
    } catch (erro) {
      mensagem.textContent = erro.message;
    } finally {
      botao.disabled = false;
    }
  });
})();
