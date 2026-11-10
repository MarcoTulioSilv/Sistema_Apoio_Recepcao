/* SAR — lista de relatórios: "Marcar todos" e "Desmarcar todos" na caixa de seleção dos dados de cadastro (DD-109).
 * Sem script nem estilo inline (DD-09). Sem este script, os atalhos ficam escondidos e cada caixa se marca à mão.
 */
(function () {
  "use strict";

  document.querySelectorAll("[data-cadastrais]").forEach((form) => {
    const atalhos = form.querySelector("[data-atalhos-selecao]");
    if (!atalhos) return;
    atalhos.hidden = false;
    atalhos.addEventListener("click", (evento) => {
      const botao = evento.target.closest("[data-marcar]");
      if (!botao) return;
      const marcar = botao.dataset.marcar === "todos";
      form.querySelectorAll('input[name="incluir"]').forEach((caixa) => { caixa.checked = marcar; });
    });
  });
})();
