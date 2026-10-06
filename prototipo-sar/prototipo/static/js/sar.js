/* SAR — comportamento das telas do protótipo.
 * Nenhum script ou estilo inline: as telas funcionam sob a CSP estrita da DD-09.
 * Os estados visuais vêm só de atributos (aria-pressed, aria-invalid, disabled); o CSS faz o resto.
 * Na construção, estas regras passam para o servidor (htmx) e para componentes Alpine no build CSP;
 * a validação do CPF continua existindo no servidor, que é quem decide (DD-22).
 */
(function () {
  "use strict";

  // ------------------------------------------------------------ CPF (DD-22)
  function cpfValido(texto) {
    const d = (texto || "").replace(/\D/g, "");
    if (d.length !== 11 || /^(\d)\1{10}$/.test(d)) return false;
    const digito = (n) => {
      let soma = 0;
      for (let i = 0; i < n; i++) soma += Number(d[i]) * (n + 1 - i);
      const resto = (soma * 10) % 11;
      return resto === 10 ? 0 : resto;
    };
    return digito(9) === Number(d[9]) && digito(10) === Number(d[10]);
  }

  // ------------------------------------------------------------ Sessões de turno na tela inicial (DD-76)
  // Ciclo: futura -> em preparação (1 h antes) -> aberta -> confirmação liberada (última hora)
  //        -> vencida (terminou sem confirmação) -> confirmada; aí a próxima sessão assume a tela.
  // No sistema, o estado vem do servidor, derivado do relógio (DD-23, DD-30, DD-32). Aqui, o simulador.
  const ESTADOS = {
    futura: { rotulo: "Em breve", passo: null, travado: true, confirmar: false,
      instrucao: (s) => `A preparação começa às ${menosUmaHora(s.dataset.inicio)}.` },
    preparacao: { rotulo: "Em preparação", passo: "preparacao", travado: false, confirmar: false,
      instrucao: () => "Separe fichas e crachás. Quem avisou que vai faltar vai para Faltantes." },
    aberta: { rotulo: "Aberta", passo: "aberta", travado: false, confirmar: false,
      instrucao: (s) => `Marque as faltas. A confirmação é liberada às ${menosUmaHora(s.dataset.fim)}.` },
    liberada: { rotulo: "Confirmação liberada", passo: "aberta", travado: false, confirmar: true,
      instrucao: () => "Confira com a ficha assinada e confirme a sessão." },
    vencida: { rotulo: "Aguardando confirmação", passo: "aberta", travado: false, confirmar: true,
      instrucao: (s) => `Terminou às ${s.dataset.fim}. Confirme com a ficha assinada.` },
  };
  const ORDEM_PASSOS = ["preparacao", "aberta", "confirmada"];

  function menosUmaHora(hhmm) {
    const [h, m] = hhmm.split(":").map(Number);
    return `${String(h - 1).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
  }
  function minutos(hhmm) { const [h, m] = hhmm.split(":").map(Number); return h * 60 + m; }

  function estadoNoMomento(sessao, momento) {
    const agora = minutos(momento), inicio = minutos(sessao.dataset.inicio), fim = minutos(sessao.dataset.fim);
    if (agora < inicio - 60) return "futura";
    if (agora < inicio) return "preparacao";
    if (agora < fim - 60) return "aberta";
    if (agora < fim) return "liberada";
    return "vencida";
  }

  function aplicarEstado(sessao, estado) {
    const def = ESTADOS[estado];
    sessao.dataset.estado = estado;
    sessao.querySelector("[data-rotulo-estado]").textContent = def.rotulo;
    sessao.querySelector("[data-instrucao]").textContent = def.instrucao(sessao);
    if (def.travado) sessao.dataset.travado = "true"; else delete sessao.dataset.travado;
    sessao.querySelectorAll("[data-paciente]").forEach((c) => c.setAttribute("draggable", String(!def.travado)));
    sessao.querySelectorAll('button[data-acao="mover"]').forEach((b) => { b.disabled = def.travado; });
    const confirmar = sessao.querySelector('[data-acao="confirmar"]');
    confirmar.hidden = estado === "futura" || estado === "preparacao";
    confirmar.disabled = !def.confirmar;
    sessao.querySelector("[data-nota-confirmacao]").textContent =
      estado === "aberta" ? `Liberada às ${menosUmaHora(sessao.dataset.fim)}` : "";
    const atual = ORDEM_PASSOS.indexOf(def.passo);
    sessao.querySelectorAll("[data-passo]").forEach((li) => {
      const i = ORDEM_PASSOS.indexOf(li.dataset.passo);
      if (i === atual) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
      if (atual >= 0 && i < atual) li.dataset.feito = ""; else delete li.dataset.feito;
    });
  }

  // Mostra as sessões que pedem ação; se nenhuma pede, a próxima do dia, só para consulta.
  function mostrarSessoes(doc) {
    const sessoes = Array.from(doc.querySelectorAll("[data-sessao]")).filter((s) => !("confirmada" in s.dataset));
    const ativas = sessoes.filter((s) => s.dataset.estado !== "futura");
    doc.querySelectorAll("[data-sessao]").forEach((s) => { s.hidden = true; });
    (ativas.length ? ativas : sessoes.slice(0, 1)).forEach((s) => { s.hidden = false; });
  }

  function iniciarSessoes(doc) {
    const simulador = doc.querySelector("[data-simulador]");
    if (!simulador) return;
    const relogio = doc.querySelector("[data-relogio]");
    const aviso = doc.querySelector("[data-aviso-confirmada]");
    let momento = simulador.querySelector("input:checked").value;

    const aplicarMomento = () => {
      relogio.textContent = `Quarta, 30/09/2026, ${momento}`;
      doc.querySelectorAll("[data-sessao]").forEach((s) => {
        if (!("confirmada" in s.dataset)) aplicarEstado(s, estadoNoMomento(s, momento));
      });
      mostrarSessoes(doc);
    };

    simulador.addEventListener("change", (e) => {
      momento = e.target.value;
      doc.querySelectorAll("[data-sessao]").forEach((s) => { delete s.dataset.confirmada; });
      aviso.classList.add("hidden");
      aplicarMomento();
    });

    doc.addEventListener("click", (e) => {
      const botao = e.target.closest('button[data-acao="confirmar"]');
      if (!botao || botao.disabled) return;
      const sessao = botao.closest("[data-sessao]");
      sessao.dataset.confirmada = "";
      const nome = sessao.querySelector("h2").firstChild.textContent.trim();
      aviso.textContent = `${nome} confirmado às ${momento}. Depois de confirmada, a sessão só muda com autorização da administração.`;
      aviso.classList.remove("hidden");
      mostrarSessoes(doc);
      const proxima = doc.querySelector("[data-sessao]:not([hidden]) h2");
      if (proxima) { proxima.setAttribute("tabindex", "-1"); proxima.focus(); }
    });

    aplicarMomento();
  }

  // ------------------------------------------------------------ Cadastro: mínimo (P-03) e CPF
  function iniciarCadastro(form) {
    const minimos = form.querySelectorAll("[data-minimo]");
    const cpf = form.querySelector('[data-validar="cpf"]');
    const erroCpf = form.querySelector("#cpf-erro");
    const salvar = form.querySelector('[data-acao="salvar-paciente"]');
    const contagem = form.querySelector('[data-contagem="minimo"]');

    const atualizar = () => {
      const preenchidos = Array.from(minimos).filter((c) => c.value.trim() !== "").length;
      const cpfVazio = cpf.value.trim() === "";
      const cpfOk = cpfVazio || cpfValido(cpf.value);

      contagem.textContent = preenchidos;
      if (cpfOk) {
        cpf.removeAttribute("aria-invalid");
        erroCpf.textContent = "";
      } else {
        cpf.setAttribute("aria-invalid", "true");
        erroCpf.textContent = "CPF inválido: confira os dígitos. Deixe em branco se o paciente não trouxe o documento.";
      }
      salvar.disabled = preenchidos < minimos.length || !cpfOk;
    };

    form.addEventListener("input", atualizar);

    // Telefones e contatos (RF-201, RF-202): cada telefone pertence ao paciente ou a um contato (INV-12)
    const clonar = (id) => form.querySelector(`#${id}`).content.firstElementChild.cloneNode(true);
    form.addEventListener("click", (e) => {
      const botao = e.target.closest("button[data-acao]");
      if (!botao) return;
      const acao = botao.dataset.acao;
      if (acao === "adicionar-telefone") {
        // A lista fica ao lado do botão, tanto no paciente quanto em cada contato
        const lista = botao.parentElement.querySelector(":scope > [data-lista-telefones]");
        const linha = clonar("modelo-telefone");
        lista.appendChild(linha);
        linha.querySelector("input").focus();
      } else if (acao === "remover-telefone") {
        const lista = botao.closest("[data-lista-telefones]");
        botao.closest("[data-telefone]").remove();
        const proximo = lista.parentElement.querySelector('[data-acao="adicionar-telefone"]');
        if (proximo) proximo.focus();
      } else if (acao === "adicionar-contato") {
        const cartao = clonar("modelo-contato");
        form.querySelector("[data-lista-contatos]").appendChild(cartao);
        cartao.querySelector("input").focus();
      } else if (acao === "remover-contato") {
        botao.closest("[data-contato]").remove();
        form.querySelector('[data-acao="adicionar-contato"]').focus();
      }
    });
    form.addEventListener("submit", (e) => {
      e.preventDefault(); // protótipo: não há servidor
      salvar.textContent = "Paciente salvo";
      salvar.disabled = true;
    });
    atualizar();
  }

  // ------------------------------------------------------------ Quadros de presentes e faltantes
  // Usados na preparação do turno (faltante = ausência avisada, P-13) e na frequência do turno.
  // Clicar no cartão, usar o botão ou arrastar o cartão troca o quadro. Nada muda depois de travado.
  function iniciarQuadros(tela) {
    const listas = {
      presentes: tela.querySelector('[data-lista="presentes"]'),
      faltantes: tela.querySelector('[data-lista="faltantes"]'),
    };
    const anuncio = tela.querySelector("[data-anuncio]");
    let arrastado = null;

    const atualizar = () => {
      let total = 0;
      for (const zona of Object.keys(listas)) {
        const qtd = listas[zona].children.length;
        total += qtd;
        tela.querySelectorAll(`[data-contagem="${zona}"]`).forEach((el) => { el.textContent = qtd; });
        tela.querySelector(`[data-vazio="${zona}"]`).hidden = qtd > 0;
      }
      tela.querySelectorAll('[data-contagem="total"]').forEach((el) => { el.textContent = total; });
    };

    const mover = (cartao, destino) => {
      if (tela.dataset.travado) return;
      const atual = cartao.dataset.situacao === "faltante" ? "faltantes" : "presentes";
      if (atual === destino) return;
      cartao.dataset.situacao = destino === "faltantes" ? "faltante" : "presente";
      const nome = cartao.querySelector("[data-nome]").textContent;
      const botao = cartao.querySelector('[data-acao="mover"]');
      botao.textContent = destino === "faltantes" ? "Mover para presentes" : "Mover para faltantes";
      botao.setAttribute("aria-label", `${botao.textContent}: ${nome}`);
      listas[destino].appendChild(cartao);
      anuncio.textContent = `${nome} movido para ${destino}.`;
      atualizar();
      botao.focus();
    };

    // O botão é o caminho pelo teclado; com o mouse, clicar em qualquer parte do cartão também move.
    tela.addEventListener("click", (e) => {
      const cartao = e.target.closest("[data-paciente]");
      if (!cartao) return;
      mover(cartao, cartao.dataset.situacao === "faltante" ? "presentes" : "faltantes");
    });

    tela.addEventListener("dragstart", (e) => {
      if (tela.dataset.travado) { e.preventDefault(); return; }
      arrastado = e.target.closest("[data-paciente]");
      if (!arrastado) return;
      arrastado.dataset.arrastando = "true";
      if (e.dataTransfer) {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", arrastado.dataset.paciente);
      }
    });
    tela.addEventListener("dragend", () => {
      if (arrastado) delete arrastado.dataset.arrastando;
      tela.querySelectorAll("[data-zona]").forEach((z) => delete z.dataset.sobre);
      arrastado = null;
    });
    tela.querySelectorAll("[data-zona]").forEach((zona) => {
      zona.addEventListener("dragover", (e) => {
        if (!arrastado) return;
        e.preventDefault();
        zona.dataset.sobre = "true";
      });
      zona.addEventListener("dragleave", (e) => {
        if (!zona.contains(e.relatedTarget)) delete zona.dataset.sobre;
      });
      zona.addEventListener("drop", (e) => {
        e.preventDefault();
        delete zona.dataset.sobre;
        if (arrastado) mover(arrastado, zona.dataset.zona);
      });
    });

    atualizar();
  }

  document.addEventListener("DOMContentLoaded", () => {
    const cadastro = document.querySelector('[data-tela="cadastro"]');
    if (cadastro) iniciarCadastro(cadastro);
    document.querySelectorAll("[data-quadros]").forEach(iniciarQuadros);
    iniciarSessoes(document);
  });

  // Exposto só para os testes do protótipo
  if (typeof window !== "undefined") window.SAR_PROTOTIPO = { cpfValido };
})();
