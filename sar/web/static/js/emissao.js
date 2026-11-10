/* SAR — emissão de documento para imprimir (DDS §9.1). Sem script nem estilo inline (DD-09).
 * O documento sai por POST, porque a emissão fica registrada (DD-84: GET nunca altera nada), e vem com no-store. O
 * visualizador de PDF do navegador, recebendo o POST numa aba nova, busca o endereço de novo por GET e falha (405).
 * Aqui o POST vai pelo fetch e o PDF abre na aba nova a partir da memória (blob:), sem segunda ida ao servidor nem
 * arquivo gravado na estação. A aba é aberta já no clique, para o navegador não bloquear. Se a resposta não for o
 * PDF (aviso ou recusa), o formulário é enviado de novo, sem o script, para essa mesma aba, que mostra a mensagem.
 * Sem este script, o formulário abre a aba nova como antes.
 */
(function () {
  "use strict";

  const LIBERAR_APOS_MS = 5 * 60 * 1000;
  let contador = 0;

  async function emitir(form) {
    contador += 1;
    const nome = `sar-documento-${Date.now()}-${contador}`;
    const janela = window.open("", nome);
    if (!janela) {
      HTMLFormElement.prototype.submit.call(form);  // bloqueado: segue o caminho sem script
      return;
    }
    janela.document.title = "Gerando o documento…";
    janela.document.body.textContent = "Gerando o documento…";
    let resposta;
    try {
      resposta = await fetch(form.action, { method: "POST", body: new FormData(form), credentials: "same-origin" });
    } catch (erro) {
      janela.document.body.textContent = "Não foi possível falar com o servidor. Feche esta aba e tente de novo.";
      return;
    }
    const tipo = resposta.headers.get("Content-Type") || "";
    if (resposta.ok && tipo.startsWith("application/pdf")) {
      const endereco = URL.createObjectURL(await resposta.blob());
      janela.location.replace(endereco);
      window.setTimeout(() => URL.revokeObjectURL(endereco), LIBERAR_APOS_MS);
      return;
    }
    // Aviso ou recusa: a mesma aba recebe a página do servidor (nada foi emitido nem registrado).
    const alvo = form.getAttribute("target");
    form.setAttribute("target", nome);
    HTMLFormElement.prototype.submit.call(form);
    if (alvo === null) form.removeAttribute("target"); else form.setAttribute("target", alvo);
  }

  document.addEventListener("submit", (evento) => {
    const form = evento.target;
    if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-emitir")) return;
    evento.preventDefault();
    emitir(form);
  });
})();
