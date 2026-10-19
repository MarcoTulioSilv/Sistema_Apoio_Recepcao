/* SAR — distribuição dos pacientes nas escalas (enfermagem, RF-405). Sem script nem estilo inline (DD-09).
 * O seletor "Turno" de cada paciente é o campo do formulário; o servidor grava só ao clicar em "Salvar alocações".
 * Este script só põe a peça onde o seletor diz (linha na lista "Sem alocação", cartão no quadro do turno), leva o
 * arraste e o autocompletar até o mesmo seletor, marca o que ainda não foi salvo e avisa antes de sair da página.
 */
(function () {
  "use strict";

  const form = document.getElementById("distribuicao");
  if (!form || form.dataset.travado) return;
  const anuncio = form.querySelector("[data-anuncio]");
  const pendentes = form.querySelector("[data-pendentes]");
  let arrastado = null;
  let enviando = false;

  const zonaDe = (valor) => form.querySelector(valor ? `[data-lista="${valor}"]` : '[data-zona="sem"]');
  const nomeDe = (peca) => peca.querySelector("[data-nome]").textContent;
  const seletorDe = (peca) => peca.querySelector("select[data-turno]");
  const rotuloDe = (peca) => seletorDe(peca).selectedOptions[0].textContent;

  function atualizarContagens() {
    form.querySelectorAll("[data-contagem]").forEach((contador) => {
      const chave = contador.dataset.contagem;
      const lista = zonaDe(chave === "sem" ? "" : chave);
      const quantos = lista.querySelectorAll(".cartao-escala").length;
      contador.textContent = quantos;
      const vazio = form.querySelector(`[data-vazio="${chave}"]`);
      if (vazio) vazio.hidden = quantos > 0;
    });
    const mudados = form.querySelectorAll(".cartao-escala[data-mudou]").length;
    if (pendentes) pendentes.textContent = mudados ? `${mudados} ${mudados === 1 ? "mudança não salva" : "mudanças não salvas"}` : "";
  }

  // Põe a peça onde o seletor diz e marca se difere do que está gravado.
  function posicionar(peca, anunciar) {
    const valor = seletorDe(peca).value;
    zonaDe(valor).appendChild(peca);
    if (valor !== peca.dataset.atual) peca.dataset.mudou = ""; else delete peca.dataset.mudou;
    atualizarContagens();
    if (anunciar && anuncio) anuncio.textContent = `${nomeDe(peca)}: ${rotuloDe(peca)}, ainda não salvo.`;
  }

  function mover(peca, valor) {
    const seletor = seletorDe(peca);
    if (seletor.value === valor) return;
    seletor.value = valor;
    posicionar(peca, true);
  }

  form.addEventListener("change", (e) => {
    if (e.target.matches("select[data-turno]")) {
      const peca = e.target.closest(".cartao-escala");
      posicionar(peca, true);
      e.target.focus();
    }
  });

  // Autocompletar de cada turno: a lista de nomes da própria página, sem ir ao servidor.
  form.addEventListener("input", (e) => {
    const campo = e.target;
    if (!campo.matches("[data-acrescentar]")) return;
    const opcao = Array.from(document.querySelectorAll("#pacientes-escalas option")).find((o) => o.value === campo.value);
    if (!opcao) return;
    const peca = form.querySelector(`.cartao-escala[data-paciente="${opcao.dataset.paciente}"]`);
    campo.value = "";
    if (peca) mover(peca, campo.dataset.acrescentar);
  });
  // Enter no campo de busca não envia o formulário: só "Salvar alocações" envia.
  form.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.matches("[data-acrescentar]")) e.preventDefault();
  });

  form.addEventListener("dragstart", (e) => {
    const peca = e.target.closest && e.target.closest(".cartao-escala");
    if (!peca) return;
    arrastado = peca;
    peca.dataset.arrastando = "true";
    if (e.dataTransfer) {
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", peca.dataset.paciente);
    }
  });
  form.addEventListener("dragend", () => {
    if (arrastado) delete arrastado.dataset.arrastando;
    form.querySelectorAll("[data-sobre]").forEach((z) => delete z.dataset.sobre);
    arrastado = null;
  });
  const alvoDe = (e) => (arrastado && e.target.closest ? e.target.closest("[data-zona]") : null);
  form.addEventListener("dragover", (e) => {
    const zona = alvoDe(e);
    if (!zona) return;
    e.preventDefault();
    zona.dataset.sobre = "true";
  });
  form.addEventListener("dragleave", (e) => {
    const zona = e.target.closest && e.target.closest("[data-zona]");
    if (zona && !zona.contains(e.relatedTarget)) delete zona.dataset.sobre;
  });
  form.addEventListener("drop", (e) => {
    const zona = alvoDe(e);
    if (!zona) return;
    e.preventDefault();
    delete zona.dataset.sobre;
    mover(arrastado, zona.dataset.zona === "sem" ? "" : zona.dataset.zona);
  });

  form.addEventListener("submit", () => { enviando = true; });
  window.addEventListener("beforeunload", (e) => {
    if (!enviando && form.querySelector(".cartao-escala[data-mudou]")) e.preventDefault();
  });

  atualizarContagens();
})();
