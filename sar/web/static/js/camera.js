/* SAR — foto do paciente pela câmera (AD-18, RF-711), direto ao servidor, sem o agente. Sem script inline (DD-09).
 * Abre a câmera, tira a foto num canvas, mostra a prévia e, ao usar, abre a ingestão (tipo foto_paciente), envia a
 * imagem em JPEG pela rota de captura com o token de uso único (DD-94), conclui e acompanha até a conferência.
 * Nada é gravado na estação: a foto existe só na memória da página.
 */
(function () {
  "use strict";

  const form = document.getElementById("camera");
  if (!form || !window.SARCaptura) return;
  const video = form.querySelector("[data-video]");
  const previa = form.querySelector("[data-previa]");
  const aviso = form.querySelector("[data-aviso]");
  const botoes = {
    abrir: form.querySelector("[data-abrir]"),
    tirar: form.querySelector("[data-tirar]"),
    deNovo: form.querySelector("[data-de-novo]"),
    enviar: form.querySelector("[data-enviar]"),
  };
  const regiao = document.getElementById("situacao");
  let fluxo = null;
  let foto = null;

  function mostrar(modo) {
    const comFoto = modo === "foto";
    video.hidden = comFoto;
    previa.hidden = !comFoto;
    botoes.tirar.disabled = modo !== "camera";
    botoes.deNovo.disabled = !comFoto;
    botoes.enviar.disabled = !comFoto;
  }

  botoes.abrir.addEventListener("click", async () => {
    try {
      fluxo = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 }, audio: false });
    } catch {
      aviso.textContent = "Não foi possível abrir a câmera. Confira se ela está ligada e se o navegador tem permissão.";
      return;
    }
    video.srcObject = fluxo;
    aviso.textContent = "Câmera aberta. Enquadre o rosto e tire a foto.";
    mostrar("camera");
  });

  botoes.tirar.addEventListener("click", () => {
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth || 1280;
    canvas.height = video.videoHeight || 720;
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(
      (blob) => {
        foto = blob;
        if (previa.src) URL.revokeObjectURL(previa.src);
        previa.src = URL.createObjectURL(blob);
        aviso.textContent = "Foto tirada. Use esta foto ou tire de novo.";
        mostrar("foto");
      },
      "image/jpeg",
      0.9,
    );
  });

  botoes.deNovo.addEventListener("click", () => {
    foto = null;
    aviso.textContent = "Câmera aberta. Enquadre o rosto e tire a foto.";
    mostrar("camera");
  });

  form.addEventListener("submit", async (evento) => {
    evento.preventDefault();
    if (!foto || !form.reportValidity()) return;
    botoes.enviar.disabled = true;
    try {
      const ingestao = await window.SARCaptura.abrir(form);
      const base = `/captura/ingestoes/${ingestao.id}`;
      const autorizacao = { Authorization: `Bearer ${ingestao.token}` };
      const envio = await fetch(`${base}/paginas/1`, { method: "PUT", headers: autorizacao, body: foto });
      if (!envio.ok) throw new Error("Não foi possível enviar a foto. Tente de novo.");
      const conclusao = await fetch(`${base}/concluir`, {
        method: "POST",
        headers: { ...autorizacao, "Content-Type": "application/json" },
        body: JSON.stringify({ paginas: 1 }),
      });
      if (!conclusao.ok) throw new Error("Não foi possível enviar a foto. Tente de novo.");
      if (fluxo) fluxo.getTracks().forEach((trilha) => trilha.stop());
      aviso.textContent = "Foto enviada.";
      window.SARCaptura.acompanhar(regiao, ingestao.situacao);
    } catch (erro) {
      aviso.textContent = erro.message;
      botoes.enviar.disabled = false;
    }
  });
})();
