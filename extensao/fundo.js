// Entrega ao bot, neste computador, o que as abas da Novibet mandaram.
// Se mudar a porta aqui, mude tambem em fontes.extensao.porta no config.json
// e em host_permissions no manifest.json.
const ENDERECO_DO_BOT = "http://127.0.0.1:8765";

function mostrarSituacao(conectado) {
  // "off" no icone = o bot nao esta rodando (ou esta noutra porta).
  chrome.action.setBadgeText({ text: conectado ? "" : "off" });
}

chrome.runtime.onMessage.addListener((mensagem) => {
  const caminho = { payload: "/payload", estado: "/estado" }[mensagem && mensagem.tipo];
  if (!caminho) return;
  fetch(ENDERECO_DO_BOT + caminho, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Projeto-Novibet": "1" },
    body: JSON.stringify(mensagem),
  }).then(
    (resposta) => mostrarSituacao(resposta.ok),
    () => mostrarSituacao(false)
  );
});
