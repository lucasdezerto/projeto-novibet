// Roda extensao/pagina.js num "navegador de mentira" e confere que ele:
//  - copia as respostas de odds (fetch e XMLHttpRequest);
//  - ignora o resto;
//  - devolve a pagina a resposta intacta;
//  - nao faz nenhuma requisicao por conta propria.
// Chamado por tests/test_extensao.py. Sai com codigo 1 se algo falhar.
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const FEED = "https://www.novibet.bet.br/spt/feed/marketviews/location/v2/4324/5931237/";
const OUTRA = "https://www.novibet.bet.br/api/banners";
const CORPO = '[{"betViews": []}]';

const pedidos = [];
const mensagens = [];

class RespostaFalsa {
  constructor(url, corpo) { this.url = url; this.corpo = corpo; }
  clone() { return new RespostaFalsa(this.url, this.corpo); }
  text() { return Promise.resolve(this.corpo); }
}

class XhrFalso {
  constructor() { this.ouvintes = {}; this.responseType = ""; }
  open(metodo, url) { this.url = url; }
  send() {
    pedidos.push(this.url);
    this.responseURL = this.url;
    this.responseText = CORPO;
    setTimeout(() => (this.ouvintes.load || []).forEach((f) => f()), 0);
  }
  addEventListener(nome, f) { (this.ouvintes[nome] = this.ouvintes[nome] || []).push(f); }
}

const janela = {
  location: { origin: "https://www.novibet.bet.br" },
  fetch: (url) => { pedidos.push(url); return Promise.resolve(new RespostaFalsa(url, CORPO)); },
  postMessage: (dados, origem) => mensagens.push({ dados, origem }),
};
const contexto = { window: janela, XMLHttpRequest: XhrFalso, JSON, WeakMap, String, Promise };
vm.createContext(contexto);
vm.runInContext(
  fs.readFileSync(path.join(__dirname, "..", "..", "extensao", "pagina.js"), "utf8"),
  contexto
);

(async () => {
  // fetch
  const resposta = await janela.fetch(FEED);
  assert.strictEqual(await resposta.text(), CORPO, "a pagina tem que receber a resposta intacta");
  await janela.fetch(OUTRA);

  // XMLHttpRequest
  const xhr = new contexto.XMLHttpRequest();
  xhr.open("GET", FEED);
  xhr.send();
  const outro = new contexto.XMLHttpRequest();
  outro.open("GET", OUTRA);
  outro.send();

  await new Promise((r) => setTimeout(r, 20));

  assert.deepStrictEqual(pedidos, [FEED, OUTRA, FEED, OUTRA],
    "so os pedidos da propria pagina podem existir");
  assert.strictEqual(mensagens.length, 2, "uma copia do fetch e uma do XHR, nada do resto");
  for (const { dados, origem } of mensagens) {
    assert.strictEqual(origem, "https://www.novibet.bet.br");
    assert.strictEqual(dados.origem, "projeto-novibet");
    assert.strictEqual(dados.url, FEED);
    assert.strictEqual(dados.corpo, CORPO);
  }
  console.log("ok");
})().catch((erro) => { console.error(erro); process.exit(1); });
