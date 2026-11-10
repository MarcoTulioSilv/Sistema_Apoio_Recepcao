/* SAR — pesquisa nos quadros de relatório que rolam (a ocupação e os dados de cadastro). Sem script nem estilo inline
 * (DD-09). Filtra as linhas do quadro enquanto se digita, sem diferenciar maiúsculas nem acentos, e mostra quantas
 * estão à vista. O total do rodapé não muda: é o do quadro inteiro. Sem este script, o campo fica escondido.
 */
(function () {
  "use strict";

  const normalizar = (texto) => texto.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

  document.querySelectorAll("[data-pesquisa]").forEach((caixa) => {
    const quadro = caixa.closest("[data-quadro]");
    const campo = caixa.querySelector("input");
    const contagem = caixa.querySelector("[data-contagem]");
    if (!quadro || !campo || !contagem) return;
    const linhas = Array.from(quadro.querySelectorAll("tbody tr[data-linha]"));
    const textos = linhas.map((linha) => normalizar(linha.textContent));
    caixa.hidden = false;
    campo.addEventListener("input", () => {
      const termo = normalizar(campo.value.trim());
      let vistas = 0;
      linhas.forEach((linha, i) => {
        const mostra = !termo || textos[i].includes(termo);
        linha.hidden = !mostra;
        if (mostra) vistas += 1;
      });
      contagem.textContent = termo ? `${vistas} de ${linhas.length}` : `${linhas.length} ${caixa.dataset.nome}`;
    });
  });
})();
