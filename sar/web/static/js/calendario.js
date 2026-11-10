/* SAR — calendário próprio, em português, para todo campo de data (DD-108). Sem script nem estilo inline (DD-09).
 * O calendário do navegador segue o idioma dele; este não. Três usos, sempre com o valor ISO indo ao servidor:
 *  - intervalo ([data-intervalo], macro _intervalo.html): os dois campos de data ficam escondidos e um botão abre
 *    um calendário só; o primeiro clique marca o início, o segundo o fim;
 *  - data avulsa (input[type=date]): o campo vira texto dd/mm/aaaa, que se digita ou se escolhe no calendário; um
 *    campo escondido com o mesmo nome leva a data ISO;
 *  - mês (input[type=month]): um botão abre o quadro com os doze meses.
 * Teclado: setas mudam o dia (ou o mês), Page Up e Page Down mudam o mês (ou o ano), Shift com eles muda o ano,
 * Home e End vão ao começo e ao fim da semana, Enter escolhe, Esc fecha. Estado visual só por atributo.
 * Sem script, ficam os campos do navegador, como antes.
 */
(function () {
  "use strict";

  const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
    "novembro", "dezembro"];
  const SEMANA = [["D", "domingo"], ["S", "segunda"], ["T", "terça"], ["Q", "quarta"], ["Q", "quinta"],
    ["S", "sexta"], ["S", "sábado"]];
  let sequencia = 0;

  const novoId = (prefixo) => { sequencia += 1; return `${prefixo}-${sequencia}`; };
  const dois = (n) => String(n).padStart(2, "0");
  const iso = (d) => `${d.getFullYear()}-${dois(d.getMonth() + 1)}-${dois(d.getDate())}`;
  const ler = (texto) => {
    const partes = /^(\d{4})-(\d{2})-(\d{2})$/.exec(texto || "");
    return partes ? new Date(Number(partes[1]), Number(partes[2]) - 1, Number(partes[3])) : null;
  };
  const lerCurta = (texto) => {
    const partes = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(texto || "");
    if (!partes) return null;
    const d = new Date(Number(partes[3]), Number(partes[2]) - 1, Number(partes[1]));
    return d.getDate() === Number(partes[1]) && d.getMonth() === Number(partes[2]) - 1 ? d : null;
  };
  const curta = (d) => `${dois(d.getDate())}/${dois(d.getMonth() + 1)}/${d.getFullYear()}`;
  const extenso = (d) => `${d.getDate()} de ${MESES[d.getMonth()]} de ${d.getFullYear()}`;
  const somarDias = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
  const somarMeses = (d, n) => {
    const alvo = new Date(d.getFullYear(), d.getMonth() + n, 1);
    const ultimo = new Date(alvo.getFullYear(), alvo.getMonth() + 1, 0).getDate();
    return new Date(alvo.getFullYear(), alvo.getMonth(), Math.min(d.getDate(), ultimo));
  };
  const mesmoDia = (a, b) => Boolean(a && b) && iso(a) === iso(b);
  const hoje = () => { const h = new Date(); return new Date(h.getFullYear(), h.getMonth(), h.getDate()); };

  function elemento(tag, atributos, texto) {
    const el = document.createElement(tag);
    Object.entries(atributos || {}).forEach(([nome, valor]) => el.setAttribute(nome, valor));
    if (texto !== undefined) el.textContent = texto;
    return el;
  }

  function avisar(campo) {
    campo.dispatchEvent(new Event("input", { bubbles: true }));
    campo.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function cabecalho(rotuloAnterior, rotuloSeguinte) {
    const topo = elemento("div", { class: "flex items-center justify-between gap-2" });
    const anterior = elemento("button", { type: "button", class: "btn-pequeno", "aria-label": rotuloAnterior }, "‹");
    const titulo = elemento("h2", { class: "m-0 text-base", "aria-live": "polite" });
    const seguinte = elemento("button", { type: "button", class: "btn-pequeno", "aria-label": rotuloSeguinte }, "›");
    topo.append(anterior, titulo, seguinte);
    return { topo, anterior, titulo, seguinte };
  }

  function caixa(rotulo) {
    return elemento("div", { class: "calendario", id: novoId("calendario"), role: "dialog",
      "aria-label": `Escolher ${rotulo.toLowerCase()}`, hidden: "" });
  }

  // Grade de dias, comum ao intervalo e à data avulsa. `intervalo` liga a escolha em dois cliques.
  function painelDias({ rotulo, intervalo, minimo, maximo, aoEscolher, aoFechar }) {
    const calendario = caixa(rotulo);
    const { topo, anterior, titulo, seguinte } = cabecalho("Mês anterior", "Mês seguinte");
    const instrucao = elemento("p", { class: "m-0 text-sm text-suave", "aria-live": "polite" });
    const tabela = elemento("table", { class: "tabela-calendario" });
    const linhaCabeca = elemento("tr");
    SEMANA.forEach(([letra, nome]) => linhaCabeca.append(elemento("th", { scope: "col", abbr: nome }, letra)));
    tabela.append(elemento("thead"), elemento("tbody"));
    tabela.tHead.append(linhaCabeca);
    const atalhos = elemento("div", { class: "flex flex-wrap gap-2" });
    calendario.append(topo);
    if (intervalo) calendario.append(instrucao);
    calendario.append(tabela, atalhos);

    let marcados = [null, null];
    let pendente = null;  // intervalo: primeiro clique feito, falta o fim
    let previa = null;    // dia sob o mouse ou o foco, para destacar o trecho antes do segundo clique
    let mes = hoje();
    let foco = hoje();
    let mesDesenhado = "";
    const indisponivel = (d) => Boolean((minimo && d < minimo) || (maximo && d > maximo));

    function desenhar() {
      // A grade só é montada de novo quando o mês muda: trocar o botão sob o cursor perderia o clique.
      const chave = `${mes.getFullYear()}-${mes.getMonth()}`;
      if (chave !== mesDesenhado) {
        mesDesenhado = chave;
        titulo.textContent = `${MESES[mes.getMonth()]} de ${mes.getFullYear()}`;
        const corpo = tabela.tBodies[0];
        corpo.replaceChildren();
        const primeiro = new Date(mes.getFullYear(), mes.getMonth(), 1);
        let dia = somarDias(primeiro, -primeiro.getDay());
        for (let semana = 0; semana < 6; semana += 1) {
          const linha = elemento("tr");
          for (let d = 0; d < 7; d += 1) {
            const celula = elemento("td");
            const b = elemento("button", { type: "button", class: "dia-calendario", "data-data": iso(dia),
              "aria-label": extenso(dia) }, String(dia.getDate()));
            if (dia.getMonth() !== mes.getMonth()) b.setAttribute("data-fora", "");
            if (mesmoDia(dia, hoje())) b.setAttribute("aria-current", "date");
            if (indisponivel(dia)) b.setAttribute("aria-disabled", "true");
            celula.append(b);
            linha.append(celula);
            dia = somarDias(dia, 1);
          }
          corpo.append(linha);
        }
      }
      pintar();
    }

    function pintar() {
      instrucao.textContent = pendente ? `Início em ${curta(pendente)}. Agora escolha o último dia.` : "Escolha o primeiro dia.";
      const de = pendente || marcados[0];
      const ate = pendente ? previa : marcados[1];
      const [menor, maior] = de && ate && ate < de ? [ate, de] : [de, ate];
      tabela.querySelectorAll("[data-data]").forEach((b) => {
        const dia = ler(b.dataset.data);
        b.setAttribute("tabindex", mesmoDia(dia, foco) ? "0" : "-1");
        b.setAttribute("aria-pressed", mesmoDia(dia, menor) || mesmoDia(dia, maior) ? "true" : "false");
        b.toggleAttribute("data-no-intervalo", Boolean(menor && maior && dia > menor && dia < maior));
      });
    }

    function focar(d, moverFoco = true) {
      foco = d;
      if (d.getMonth() !== mes.getMonth() || d.getFullYear() !== mes.getFullYear()) mes = d;
      if (pendente) previa = d;
      desenhar();
      if (moverFoco) tabela.querySelector(`[data-data="${iso(d)}"]`).focus();
    }

    function escolher(d) {
      if (indisponivel(d)) return;
      if (!intervalo) { aoEscolher(d); return; }
      if (!pendente) {
        pendente = d;
        previa = d;
        focar(d);
        return;
      }
      const [a, b] = d < pendente ? [d, pendente] : [pendente, d];
      pendente = null;
      aoEscolher(a, b);
    }

    function abrir(inicio, fim, moverFoco = true) {
      marcados = [inicio, intervalo ? fim : inicio];
      pendente = null;
      previa = null;
      mesDesenhado = "";
      mes = inicio || hoje();
      calendario.hidden = false;
      focar(inicio || hoje(), moverFoco);
    }

    function fechar() { pendente = null; calendario.hidden = true; }

    function atalho(texto, acao) {
      const b = elemento("button", { type: "button", class: "btn-pequeno" }, texto);
      b.addEventListener("click", acao);
      atalhos.append(b);
    }

    anterior.addEventListener("click", () => { mes = somarMeses(mes, -1); desenhar(); });
    seguinte.addEventListener("click", () => { mes = somarMeses(mes, 1); desenhar(); });
    tabela.addEventListener("click", (evento) => {
      const b = evento.target.closest("[data-data]");
      if (b) escolher(ler(b.dataset.data));
    });
    tabela.addEventListener("mouseover", (evento) => {
      const b = evento.target.closest("[data-data]");
      if (b && pendente) { previa = ler(b.dataset.data); pintar(); }
    });
    tabela.addEventListener("keydown", (evento) => {
      const passos = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
      const meses = evento.shiftKey ? 12 : 1;
      if (evento.key in passos) focar(somarDias(foco, passos[evento.key]));
      else if (evento.key === "PageUp") focar(somarMeses(foco, -meses));
      else if (evento.key === "PageDown") focar(somarMeses(foco, meses));
      else if (evento.key === "Home") focar(somarDias(foco, -foco.getDay()));
      else if (evento.key === "End") focar(somarDias(foco, 6 - foco.getDay()));
      else return;
      evento.preventDefault();
    });
    calendario.addEventListener("keydown", (evento) => {
      if (evento.key === "Escape") { evento.preventDefault(); aoFechar(true); }
    });

    return { calendario, abrir, fechar, atalho, indisponivel, aberto: () => !calendario.hidden };
  }

  // Quadro dos doze meses, para a competência.
  function painelMeses({ rotulo, aoEscolher, aoFechar }) {
    const calendario = caixa(rotulo);
    const { topo, anterior, titulo, seguinte } = cabecalho("Ano anterior", "Ano seguinte");
    const grade = elemento("ul", { class: "grade-meses" });
    const atalhos = elemento("div", { class: "flex flex-wrap gap-2" });
    calendario.append(topo, grade, atalhos);
    let marcado = null;
    let foco = hoje();

    function desenhar(moverFoco) {
      titulo.textContent = String(foco.getFullYear());
      grade.replaceChildren();
      MESES.forEach((nome, i) => {
        const d = new Date(foco.getFullYear(), i, 1);
        const b = elemento("button", { type: "button", class: "mes-calendario", "data-mes": String(i),
          "aria-label": `${nome} de ${d.getFullYear()}`, tabindex: i === foco.getMonth() ? "0" : "-1",
          "aria-pressed": marcado && marcado.getFullYear() === d.getFullYear() && marcado.getMonth() === i ? "true" : "false" },
        nome.slice(0, 3));
        const h = hoje();
        if (h.getFullYear() === d.getFullYear() && h.getMonth() === i) b.setAttribute("aria-current", "date");
        const item = elemento("li");
        item.append(b);
        grade.append(item);
      });
      if (moverFoco) grade.querySelector(`[data-mes="${foco.getMonth()}"]`).focus();
    }

    function abrir(valor) {
      marcado = valor;
      foco = valor || new Date(hoje().getFullYear(), hoje().getMonth(), 1);
      calendario.hidden = false;
      desenhar(true);
    }

    anterior.addEventListener("click", () => { foco = somarMeses(foco, -12); desenhar(false); });
    seguinte.addEventListener("click", () => { foco = somarMeses(foco, 12); desenhar(false); });
    grade.addEventListener("click", (evento) => {
      const b = evento.target.closest("[data-mes]");
      if (b) aoEscolher(new Date(foco.getFullYear(), Number(b.dataset.mes), 1));
    });
    grade.addEventListener("keydown", (evento) => {
      const passos = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -4, ArrowDown: 4, PageUp: -12, PageDown: 12 };
      if (evento.key in passos) foco = somarMeses(foco, passos[evento.key]);
      else if (evento.key === "Home") foco = new Date(foco.getFullYear(), 0, 1);
      else if (evento.key === "End") foco = new Date(foco.getFullYear(), 11, 1);
      else return;
      evento.preventDefault();
      desenhar(true);
    });
    calendario.addEventListener("keydown", (evento) => {
      if (evento.key === "Escape") { evento.preventDefault(); aoFechar(true); }
    });
    const atalho = (texto, acao) => {
      const b = elemento("button", { type: "button", class: "btn-pequeno" }, texto);
      b.addEventListener("click", acao);
      atalhos.append(b);
    };
    return { calendario, abrir, atalho, fechar: () => { calendario.hidden = true; }, aberto: () => !calendario.hidden };
  }

  // Fecha ao clicar fora ou quando o foco sai de vez do componente.
  function fecharAoSair(raiz, painel, fechar) {
    document.addEventListener("mousedown", (evento) => {
      if (painel.aberto() && !raiz.contains(evento.target)) fechar(false);
    });
    raiz.addEventListener("focusout", (evento) => {
      if (painel.aberto() && evento.relatedTarget && !raiz.contains(evento.relatedTarget)) fechar(false);
    });
  }

  // O campo de data ou de mês dentro de <label>: o rótulo vira <div> (o calendário não pode ficar dentro do rótulo,
  // senão entra no nome do campo) e o campo passa a apontar para o texto do rótulo.
  function prepararCampo(input) {
    const label = input.closest("label");
    let rotuloEl = null;
    if (label) {
      const div = elemento("div", { class: label.className });
      div.append(...label.childNodes);
      label.replaceWith(div);
      rotuloEl = div.querySelector(".rotulo");
      if (rotuloEl && !rotuloEl.id) rotuloEl.id = novoId("rotulo");
    } else if (input.id) {
      rotuloEl = document.querySelector(`label[for="${input.id}"]`);
    }
    const rotulo = input.getAttribute("aria-label") || (rotuloEl ? rotuloEl.textContent.replace("*", "").trim() : "Data");
    return { rotulo, rotuloId: label && rotuloEl && !input.hasAttribute("aria-label") ? rotuloEl.id : null };
  }

  function iniciarIntervalo(raiz) {
    const campos = raiz.querySelector("[data-campos]");
    const entradaInicio = raiz.querySelector("[data-inicio]");
    const entradaFim = raiz.querySelector("[data-fim]");
    if (!campos || !entradaInicio || !entradaFim) return;
    const id = novoId("intervalo");
    const rotulo = raiz.dataset.rotulo || "Período";

    const campo = elemento("div", { class: "campo" });
    campo.append(elemento("span", { class: "rotulo", id: `${id}-rotulo` }, rotulo));
    const botao = elemento("button", { type: "button", class: "seletor-intervalo", id: `${id}-botao`,
      "aria-haspopup": "dialog", "aria-expanded": "false", "aria-labelledby": `${id}-rotulo ${id}-botao` });
    campo.append(botao);

    let inicio = ler(entradaInicio.value);
    let fim = ler(entradaFim.value);
    const texto = () => {
      if (inicio && fim) return `${curta(inicio)} – ${curta(fim)}`;
      if (inicio) return `A partir de ${curta(inicio)}`;
      if (fim) return `Até ${curta(fim)}`;
      return "Escolha o período";
    };
    function definir(a, b) {
      inicio = a;
      fim = b;
      entradaInicio.value = a ? iso(a) : "";
      entradaFim.value = b ? iso(b) : "";
      botao.textContent = texto();
    }
    function fechar(devolverFoco = true) {
      painel.fechar();
      botao.setAttribute("aria-expanded", "false");
      if (devolverFoco) botao.focus();
    }
    const painel = painelDias({ rotulo, intervalo: true, aoEscolher: (a, b) => { definir(a, b); fechar(); },
      aoFechar: fechar });
    botao.setAttribute("aria-controls", painel.calendario.id);
    const h = hoje();
    painel.atalho("Este mês", () => { definir(new Date(h.getFullYear(), h.getMonth(), 1), new Date(h.getFullYear(), h.getMonth() + 1, 0)); fechar(); });
    painel.atalho("Mês passado", () => { definir(new Date(h.getFullYear(), h.getMonth() - 1, 1), new Date(h.getFullYear(), h.getMonth(), 0)); fechar(); });
    painel.atalho("Últimos 30 dias", () => { definir(somarDias(h, -29), h); fechar(); });
    painel.atalho("Limpar", () => { definir(null, null); fechar(); });

    campos.hidden = true;
    raiz.append(campo, painel.calendario);
    botao.addEventListener("click", () => {
      if (painel.aberto()) { fechar(); return; }
      botao.setAttribute("aria-expanded", "true");
      painel.abrir(inicio, fim);
    });
    fecharAoSair(raiz, painel, fechar);
    botao.textContent = texto();
  }

  function iniciarData(input) {
    if (input.closest("[data-intervalo]")) return;
    const { rotulo, rotuloId } = prepararCampo(input);
    const minimo = ler(input.min);
    const maximo = ler(input.max);
    const oculto = elemento("input", { type: "hidden", name: input.name, value: input.value });
    const raiz = elemento("span", { class: "seletor-data" });
    input.before(raiz);
    raiz.append(input, oculto);

    input.removeAttribute("name");
    input.removeAttribute("min");
    input.removeAttribute("max");
    const inicial = ler(input.value);
    input.type = "text";
    input.value = inicial ? curta(inicial) : "";
    Object.entries({ inputmode: "numeric", placeholder: "dd/mm/aaaa", maxlength: "10", autocomplete: "off",
      role: "combobox", "aria-haspopup": "dialog", "aria-expanded": "false" })
      .forEach(([nome, valor]) => input.setAttribute(nome, valor));
    if (rotuloId) input.setAttribute("aria-labelledby", rotuloId);

    function fechar(devolverFoco = true) {
      painel.fechar();
      input.setAttribute("aria-expanded", "false");
      if (devolverFoco) input.focus();
    }
    function definir(d) {
      input.value = d ? curta(d) : "";
      oculto.value = d ? iso(d) : "";
      input.setCustomValidity("");
      input.removeAttribute("aria-invalid");
      avisar(input);
    }
    const painel = painelDias({ rotulo, intervalo: false, minimo, maximo,
      aoEscolher: (d) => { definir(d); fechar(); }, aoFechar: fechar });
    input.setAttribute("aria-controls", painel.calendario.id);
    if (!painel.indisponivel(hoje())) painel.atalho("Hoje", () => { definir(hoje()); fechar(); });
    if (!input.required) painel.atalho("Limpar", () => { definir(null); fechar(); });
    raiz.append(painel.calendario);

    const abrir = (moverFoco) => {
      input.setAttribute("aria-expanded", "true");
      painel.abrir(lerCurta(input.value), null, moverFoco);
    };
    input.addEventListener("click", () => { if (!painel.aberto()) abrir(false); });
    input.addEventListener("keydown", (evento) => {
      if (evento.key === "ArrowDown") { evento.preventDefault(); abrir(true); }
      else if (evento.key === "Escape" && painel.aberto()) { evento.preventDefault(); fechar(); }
    });
    // Digitado: só os números, com as barras postas sozinhas. A data vale quando completa, existente e no limite.
    input.addEventListener("input", (evento) => {
      const digitos = input.value.replace(/\D/g, "").slice(0, 8);
      let formatado = digitos;
      if (digitos.length > 4) formatado = `${digitos.slice(0, 2)}/${digitos.slice(2, 4)}/${digitos.slice(4)}`;
      else if (digitos.length > 2) formatado = `${digitos.slice(0, 2)}/${digitos.slice(2)}`;
      if (formatado !== input.value) input.value = formatado;
      const d = lerCurta(formatado);
      if (!formatado) { oculto.value = ""; input.setCustomValidity(""); return; }
      if (!d) { oculto.value = ""; input.setCustomValidity("Informe a data completa, no formato dd/mm/aaaa."); return; }
      if (maximo && d > maximo) { oculto.value = ""; input.setCustomValidity(`A data não pode passar de ${curta(maximo)}.`); return; }
      if (minimo && d < minimo) { oculto.value = ""; input.setCustomValidity(`A data não pode ser antes de ${curta(minimo)}.`); return; }
      oculto.value = iso(d);
      input.setCustomValidity("");
      if (painel.aberto()) painel.abrir(d, null, false);
    });
    fecharAoSair(raiz, painel, fechar);
  }

  function iniciarMes(input) {
    const { rotulo, rotuloId } = prepararCampo(input);
    const partes = /^(\d{4})-(\d{2})$/.exec(input.value || "");
    let valor = partes ? new Date(Number(partes[1]), Number(partes[2]) - 1, 1) : null;
    const raiz = elemento("span", { class: "seletor-data" });
    input.before(raiz);
    input.type = "hidden";
    const id = novoId("mes");
    const botao = elemento("button", { type: "button", class: "seletor-intervalo", id, "aria-haspopup": "dialog",
      "aria-expanded": "false" });
    botao.setAttribute(rotuloId ? "aria-labelledby" : "aria-label", rotuloId ? `${rotuloId} ${id}` : rotulo);
    raiz.append(botao, input);

    const texto = () => (valor ? `${MESES[valor.getMonth()]} de ${valor.getFullYear()}` : "Escolha o mês");
    function fechar(devolverFoco = true) {
      painel.fechar();
      botao.setAttribute("aria-expanded", "false");
      if (devolverFoco) botao.focus();
    }
    function definir(d) {
      valor = d;
      input.value = `${d.getFullYear()}-${dois(d.getMonth() + 1)}`;
      botao.textContent = texto();
      avisar(input);
      fechar();
    }
    const painel = painelMeses({ rotulo, aoEscolher: definir, aoFechar: fechar });
    botao.setAttribute("aria-controls", painel.calendario.id);
    const h = hoje();
    painel.atalho("Mês passado", () => definir(new Date(h.getFullYear(), h.getMonth() - 1, 1)));
    painel.atalho("Este mês", () => definir(new Date(h.getFullYear(), h.getMonth(), 1)));
    raiz.append(painel.calendario);
    botao.addEventListener("click", () => {
      if (painel.aberto()) { fechar(); return; }
      botao.setAttribute("aria-expanded", "true");
      painel.abrir(valor);
    });
    fecharAoSair(raiz, painel, fechar);
    botao.textContent = texto();
  }

  function iniciar() {
    document.querySelectorAll("[data-intervalo]").forEach(iniciarIntervalo);
    document.querySelectorAll('input[type="date"]').forEach(iniciarData);
    document.querySelectorAll('input[type="month"]').forEach(iniciarMes);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
})();
