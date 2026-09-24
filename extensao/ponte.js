// Ponte entre a pagina e a extensao. A pagina (pagina.js) nao pode falar com
// o bot direto; ela avisa aqui, e daqui vai para o fundo.js.
const ORIGEM = "projeto-novibet";

function mandar(mensagem) {
  try {
    chrome.runtime.sendMessage(mensagem);
  } catch (erro) {
    // A extensao foi recarregada e esta aba ficou com a versao velha.
    // Basta recarregar a aba; nao ha o que fazer daqui.
  }
}

window.addEventListener("message", (evento) => {
  const dados = evento.data;
  if (evento.source !== window || !dados || dados.origem !== ORIGEM) return;
  if (dados.tipo !== "payload") return;
  mandar({ tipo: "payload", url: dados.url, corpo: dados.corpo, pagina: location.href });
});

// De tempos em tempos manda o titulo e o comeco do texto da aba. E assim que
// o bot percebe uma tela de verificacao/bloqueio e para, em vez de achar que
// a casa esta "parada".
function mandarEstado() {
  const texto = document.body ? document.body.innerText.slice(0, 1000) : "";
  mandar({ tipo: "estado", pagina: location.href, titulo: document.title, texto });
}
window.addEventListener("load", mandarEstado);
setInterval(mandarEstado, 20000);
