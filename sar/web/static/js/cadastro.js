/* SAR — tela de novo cadastro. Sem script nem estilo inline (DD-09).
 * Só o que não precisa do servidor: contar o mínimo da P-03 e acrescentar ou remover linhas de telefone e de
 * contato (RF-201, RF-202). Quem valida e grava é o servidor; sem este script a tela continua funcionando,
 * com uma linha de telefone e um contato.
 */
(function () {
  "use strict";

  function proximoIndice(lista, padrao) {
    let maior = -1;
    lista.querySelectorAll("[name]").forEach((campo) => {
      const achado = campo.name.match(padrao);
      if (achado) maior = Math.max(maior, Number(achado[1]));
    });
    return maior + 1;
  }

  function clonar(form, id, prefixo) {
    const modelo = form.querySelector(`#${id}`).content.firstElementChild.cloneNode(true);
    modelo.querySelectorAll("[name]").forEach((campo) => { campo.name = campo.name.replace("__P__", prefixo); });
    modelo.querySelectorAll("[data-prefixo]").forEach((el) => { el.dataset.prefixo = el.dataset.prefixo.replace("__P__", prefixo); });
    if (modelo.dataset.prefixo) modelo.dataset.prefixo = modelo.dataset.prefixo.replace("__P__", prefixo);
    return modelo;
  }

  // Remover uma linha não dispara "change": avisa o formulário, para o rascunho acompanhar (RF-919).
  function avisarMudanca(form) { form.dispatchEvent(new Event("change", { bubbles: true })); }

  function iniciar(form) {
    // Enviado o cadastro, o salvamento automático ainda agendado (800 ms depois da última mudança) não sai mais:
    // chegaria depois e recriaria o rascunho que o cadastro acabou de eliminar (§6.6).
    form.addEventListener("submit", () => { form.dataset.enviado = "true"; });
    form.addEventListener("htmx:before:request", (e) => {
      if (e.target === form && form.dataset.enviado) e.preventDefault();
    });
    const minimos = form.querySelectorAll("[data-minimo]");
    const contagem = form.querySelector('[data-contagem="minimo"]');
    const salvar = form.querySelector('[data-acao="salvar-paciente"]');
    const atualizar = () => {
      const preenchidos = Array.from(minimos).filter((c) => c.value.trim() !== "").length;
      contagem.textContent = preenchidos;
      salvar.disabled = preenchidos < minimos.length;
    };
    form.addEventListener("input", atualizar);
    atualizar();

    // Cobertura (RF-301): convênio e carteirinha só no convênio; no SUS, o cartão é o CNS da identificação.
    const cobertura = form.querySelector("#cobertura");
    const cns = form.querySelector("#cns");
    const resumo = form.querySelector("[data-cns-resumo]");
    const mostrarCobertura = () => {
      form.querySelectorAll("[data-cobertura]").forEach((bloco) => {
        const visivel = bloco.dataset.cobertura === cobertura.value;
        bloco.hidden = !visivel;
        bloco.querySelectorAll("input, select").forEach((campo) => { campo.disabled = !visivel; });
      });
      const numero = cns.value.trim();
      resumo.textContent = numero
        ? "CNS já informado na identificação: "
        : "CNS ainda não informado: preencha o campo Cartão do SUS (CNS), na identificação.";
      if (numero) {
        const valor = document.createElement("span");
        valor.className = "numero";
        valor.textContent = numero;
        resumo.appendChild(valor);
      }
    };
    // O pop-up do rascunho salvo some sozinho depois de alguns segundos; o próximo salvamento o mostra de novo.
    const estado = form.querySelector("#rascunho-estado");
    let some;
    new MutationObserver(() => {
      if (!estado.textContent.trim()) return;
      window.clearTimeout(some);
      some = window.setTimeout(() => { estado.textContent = ""; }, 4000);
    }).observe(estado, { childList: true, characterData: true, subtree: true });

    cobertura.addEventListener("change", mostrarCobertura);
    cns.addEventListener("input", mostrarCobertura);
    mostrarCobertura();

    form.addEventListener("click", (e) => {
      const botao = e.target.closest("button[data-acao]");
      if (!botao || botao.type === "submit") return;
      const acao = botao.dataset.acao;
      if (acao === "adicionar-telefone") {
        const contato = botao.closest("[data-contato]");
        const lista = (contato || botao.closest("fieldset")).querySelector("[data-lista-telefones]");
        const base = contato ? `${contato.dataset.prefixo}-tel-` : "tel-";
        const padrao = new RegExp(`^${base}(\\d+)-`);
        const linha = clonar(form, "modelo-telefone", `${base}${proximoIndice(lista, padrao)}`);
        lista.appendChild(linha);
        linha.querySelector("input").focus();
      } else if (acao === "remover-telefone") {
        const proximo = botao.closest("[data-lista-telefones]").parentElement.querySelector('[data-acao="adicionar-telefone"]');
        botao.closest("[data-telefone]").remove();
        proximo.focus();
        avisarMudanca(form);
      } else if (acao === "adicionar-contato") {
        const lista = form.querySelector("[data-lista-contatos]");
        const bloco = clonar(form, "modelo-contato", `contato-${proximoIndice(lista, /^contato-(\d+)-/)}`);
        lista.appendChild(bloco);
        bloco.querySelector("input").focus();
      } else if (acao === "remover-contato") {
        botao.closest("[data-contato]").remove();
        form.querySelector('[data-acao="adicionar-contato"]').focus();
        avisarMudanca(form);
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector('[data-tela="cadastro"]');
    if (form) iniciar(form);
  });
})();
