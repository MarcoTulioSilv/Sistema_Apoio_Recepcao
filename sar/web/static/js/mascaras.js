/* SAR — formato de telefone e CEP enquanto se digita. Sem script nem estilo inline (DD-09).
 * Só na tela: celular 99999-0001 (5-4), fixo 3631-0002 (4-4), CEP 75800-000 (5-3). O servidor aceita com ou sem
 * o hífen e guarda só os dígitos; sem este script, quem digita sem hífen também é atendido.
 */
(function () {
  "use strict";

  const FORMATOS = {
    telefone: (d) => {
      d = d.slice(0, 9);
      if (d.length > 8) return `${d.slice(0, 5)}-${d.slice(5)}`;
      if (d.length > 4) return `${d.slice(0, 4)}-${d.slice(4)}`;
      return d;
    },
    cep: (d) => {
      d = d.slice(0, 8);
      return d.length > 5 ? `${d.slice(0, 5)}-${d.slice(5)}` : d;
    },
  };

  function formatar(campo) {
    const formato = FORMATOS[campo.dataset.mascara];
    if (!formato) return;
    const antes = campo.value;
    const depois = formato(antes.replace(/\D/g, ""));
    if (antes !== depois) campo.value = depois;
  }

  // Delegação: vale também para as linhas acrescentadas depois (telefones e contatos) e para o que o htmx troca.
  document.addEventListener("input", (e) => {
    if (e.target instanceof HTMLInputElement && e.target.dataset.mascara) formatar(e.target);
  });
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("input[data-mascara]").forEach(formatar);
  });
})();
