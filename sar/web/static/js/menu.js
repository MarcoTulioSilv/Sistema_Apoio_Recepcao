/* SAR — recolher e abrir o menu lateral. Sem script nem estilo inline (DD-09).
 * Aberto, o botão fica no topo do menu; recolhido, o menu some por inteiro e o botão de abrir aparece no
 * cabeçalho, ao lado do nome da tela. O foco passa para o botão que fica visível. A escolha fica guardada só
 * nesta estação (localStorage), como conveniência: se o navegador não deixar guardar, o menu volta aberto.
 */
(function () {
  "use strict";

  const CHAVE = "sar.menu.recolhido";

  function lerPreferencia() {
    try { return window.localStorage.getItem(CHAVE) === "1"; } catch (e) { return false; }
  }

  function guardarPreferencia(recolhido) {
    try { window.localStorage.setItem(CHAVE, recolhido ? "1" : "0"); } catch (e) { /* sem armazenamento: tudo bem */ }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const layout = document.getElementById("layout");
    const recolher = layout && layout.querySelector("[data-recolher-menu]");
    const abrir = layout && layout.querySelector("[data-abrir-menu]");
    if (!recolher || !abrir) return;

    const aplicar = (recolhido) => {
      if (recolhido) layout.dataset.recolhido = ""; else delete layout.dataset.recolhido;
      recolher.setAttribute("aria-expanded", recolhido ? "false" : "true");
      abrir.setAttribute("aria-expanded", recolhido ? "false" : "true");
    };

    aplicar(lerPreferencia());
    recolher.addEventListener("click", () => { aplicar(true); guardarPreferencia(true); abrir.focus(); });
    abrir.addEventListener("click", () => { aplicar(false); guardarPreferencia(false); recolher.focus(); });
  });
})();
