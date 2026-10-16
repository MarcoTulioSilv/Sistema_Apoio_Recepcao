/* SAR — decisão de autorização em dois passos. Sem script nem estilo inline (DD-09).
 * "Confirmar decisão" não decide: abre o diálogo com a escolha feita no seletor, o motivo e o botão final na cor
 * da escolha (verde para aprovar, vermelho para negar). Sem este script, o servidor devolve a tela com o diálogo
 * aberto, e quem decide continua sendo o servidor, que exige o motivo para negar (§5.3).
 */
(function () {
  "use strict";

  const TEXTOS = {
    aprovar: { titulo: "Aprovar este pedido?", rotulo: "Motivo (opcional)", botao: "Aprovar", classe: "btn-aprovar" },
    negar: { titulo: "Negar este pedido?", rotulo: "Motivo (obrigatório para negar)", botao: "Negar", classe: "btn-urgente" },
  };

  function iniciar(form) {
    const dialogo = form.querySelector("#confirmar-decisao");
    const aviso = form.querySelector("[data-aviso-decisao]");
    const motivo = dialogo.querySelector('textarea[name="motivo"]');
    const confirmar = dialogo.querySelector("[data-confirmar]");
    const abrir = form.querySelector('button[type="submit"]:not([data-confirmar])');

    const escolha = () => form.querySelector('input[name="decisao"]:checked');

    const preparar = (decisao) => {
      const textos = TEXTOS[decisao];
      dialogo.querySelector("[data-titulo]").textContent = textos.titulo;
      dialogo.querySelector("[data-rotulo-motivo]").textContent = textos.rotulo;
      confirmar.textContent = textos.botao;
      confirmar.className = textos.classe;
      motivo.required = decisao === "negar";
    };

    const abrirDialogo = () => {
      if (dialogo.open) dialogo.close();
      preparar(escolha().value);
      dialogo.showModal();
      motivo.focus();
    };

    form.addEventListener("change", () => { aviso.textContent = ""; });

    form.addEventListener("submit", (e) => {
      if (e.submitter === confirmar) {
        if (motivo.required && motivo.value.trim() === "") {
          e.preventDefault();
          motivo.setAttribute("aria-invalid", "true");
          motivo.focus();
        }
        return;  // segue para o servidor
      }
      e.preventDefault();
      if (!escolha()) {
        aviso.textContent = "Escolha aprovar ou negar antes de confirmar.";
        form.querySelector('input[name="decisao"]').focus();
        return;
      }
      abrirDialogo();
    });

    dialogo.querySelector("[data-voltar]").addEventListener("click", (e) => {
      e.preventDefault();
      dialogo.close();
    });
    dialogo.addEventListener("close", () => { motivo.removeAttribute("aria-invalid"); abrir.focus(); });

    // O servidor reabriu o diálogo (sem script ou depois de um erro): vira modal, com o foco no motivo.
    if (dialogo.open && escolha()) abrirDialogo();
  }

  document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("[data-decisao]");
    if (form) iniciar(form);
  });
})();
