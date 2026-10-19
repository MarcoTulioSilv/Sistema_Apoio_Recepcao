/* SAR — quadros de presentes e faltantes da tela inicial (DD-76). Sem script nem estilo inline (DD-09).
 * Quem decide é o servidor: cada cartão tem um formulário com o botão "Mover", que o htmx envia e que devolve o
 * painel atualizado. Este script só leva o arraste e o clique no cartão até esse mesmo botão, devolve o foco ao
 * cartão movido e copia a mensagem para a região que o leitor de tela anuncia. Sem ele, o botão continua valendo.
 */
(function () {
  "use strict";

  let arrastado = null;

  function botaoDo(cartao) {
    return cartao.querySelector('[data-acao="mover"]');
  }

  function mover(cartao, destino) {
    if (!cartao || cartao.closest("[data-travado]")) return;
    const atual = cartao.dataset.situacao === "faltante" ? "faltantes" : "presentes";
    const botao = botaoDo(cartao);
    if (atual === destino || !botao) return;
    botao.click();
  }

  // Com o mouse, clicar em qualquer parte do cartão move; os botões e links dentro dele seguem o próprio caminho.
  document.addEventListener("click", (e) => {
    if (e.target.closest("button, a, input, label, summary")) return;
    const cartao = e.target.closest(".cartao-paciente[data-paciente]");
    if (!cartao) return;
    mover(cartao, cartao.dataset.situacao === "faltante" ? "presentes" : "faltantes");
  });

  document.addEventListener("dragstart", (e) => {
    const cartao = e.target.closest && e.target.closest(".cartao-paciente[data-paciente]");
    if (!cartao || cartao.closest("[data-travado]")) {
      if (cartao) e.preventDefault();
      return;
    }
    arrastado = cartao;
    cartao.dataset.arrastando = "true";
    if (e.dataTransfer) {
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", cartao.dataset.paciente);
    }
  });

  document.addEventListener("dragend", () => {
    if (arrastado) delete arrastado.dataset.arrastando;
    document.querySelectorAll("[data-zona][data-sobre]").forEach((z) => delete z.dataset.sobre);
    arrastado = null;
  });

  function zonaDa(e) {
    const zona = e.target.closest && e.target.closest("[data-zona]");
    // Só vale soltar na mesma sessão de onde o cartão saiu.
    return zona && arrastado && zona.closest("[data-sessao]") === arrastado.closest("[data-sessao]") ? zona : null;
  }

  document.addEventListener("dragover", (e) => {
    const zona = zonaDa(e);
    if (!zona) return;
    e.preventDefault();
    zona.dataset.sobre = "true";
  });

  document.addEventListener("dragleave", (e) => {
    const zona = e.target.closest && e.target.closest("[data-zona]");
    if (zona && !zona.contains(e.relatedTarget)) delete zona.dataset.sobre;
  });

  document.addEventListener("drop", (e) => {
    const zona = zonaDa(e);
    if (!zona) return;
    e.preventDefault();
    delete zona.dataset.sobre;
    mover(arrastado, zona.dataset.zona);
  });

  // A atualização de cada minuto troca o painel inteiro: enquanto alguém digita na busca, escolhe uma ausência ou
  // escreve o motivo, ela espera o minuto seguinte, para não apagar o que está sendo feito.
  function emUso(painel) {
    const ativo = document.activeElement;
    const digitando = ativo && painel.contains(ativo) && ativo.matches("input, select, textarea");
    return digitando || painel.querySelector("details[open]") !== null;
  }

  document.addEventListener("htmx:before:request", (e) => {
    const painel = document.getElementById("turnos");
    if (e.target === painel && emUso(painel)) e.preventDefault();
  });

  // Depois de cada troca do painel: foco no cartão movido e a mensagem para o leitor de tela.
  document.addEventListener("htmx:after:swap", () => {
    const alvo = document.querySelector("[data-focar]");
    if (alvo) {
      const botao = document.getElementById(alvo.dataset.focar);
      if (botao) botao.focus();
    }
    const anuncio = document.getElementById("anuncio-turnos");
    const mensagem = document.querySelector("#turnos [data-mensagem]");
    if (anuncio) anuncio.textContent = mensagem ? mensagem.textContent : "";
  });
})();
