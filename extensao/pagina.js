// Roda dentro da pagina da Novibet, antes dos scripts dela.
//
// So COPIA as respostas de odds que a propria pagina pediu. Nao faz
// requisicao nenhuma, nao muda a resposta que a pagina recebe e nao tenta se
// esconder. Ver docs/decisoes.md D-018.
(() => {
  const FILTRO = "/spt/feed/marketviews/";
  const ORIGEM = "projeto-novibet";

  function encaminhar(url, corpo) {
    window.postMessage(
      { origem: ORIGEM, tipo: "payload", url: String(url), corpo: String(corpo) },
      window.location.origin
    );
  }

  // Respostas pedidas com fetch.
  const fetchOriginal = window.fetch;
  window.fetch = function (...argumentos) {
    const promessa = fetchOriginal.apply(this, argumentos);
    promessa.then(
      (resposta) => {
        if (resposta && resposta.url && resposta.url.includes(FILTRO)) {
          resposta.clone().text().then((corpo) => encaminhar(resposta.url, corpo), () => {});
        }
      },
      () => {}
    );
    return promessa;
  };

  // Respostas pedidas com XMLHttpRequest.
  const enderecos = new WeakMap();
  const abrirOriginal = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (metodo, url, ...resto) {
    enderecos.set(this, String(url));
    return abrirOriginal.call(this, metodo, url, ...resto);
  };
  const enviarOriginal = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (...argumentos) {
    const url = enderecos.get(this) || "";
    if (url.includes(FILTRO)) {
      this.addEventListener("load", () => {
        const final = this.responseURL || url;
        if (this.responseType === "" || this.responseType === "text") {
          encaminhar(final, this.responseText);
        } else if (this.responseType === "json") {
          encaminhar(final, JSON.stringify(this.response));
        }
      });
    }
    return enviarOriginal.apply(this, argumentos);
  };
})();
