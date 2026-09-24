# Site da Novibet, APIs de mercado e oportunidades para o bot

**Data:** 2026-09-24 · **Autor:** Kevin (sessão com Claude Code)

Levantamento feito depois de construir a extensão do Chrome
([D-018](decisoes.md#d-018)). O pedido foi: testar a extensão; se não desse,
examinar o site e as APIs e listar oportunidades para desenvolver o bot.

---

## Resumo

1. **A extensão não pôde ser instalada por aqui.** Instalar exige ligar o
   Modo do desenvolvedor do Chrome, e isso é você que faz. O teste que deu para
   fazer foi **inconclusivo** (detalhes abaixo). O formato das odds, porém, foi
   conferido ao vivo e **continua igual** ao que o parser da Novibet entende.
2. **O site mostra muito mais do que o bot usa hoje.** Existe um feed "ao
   vivo" com **todos os jogos em andamento, de todos os esportes, a cada 5
   segundos**, com placar e mercado suspenso. E há um feed por jogo com placar
   **ponto a ponto** e a **hora exata em que cada mercado foi reprecificado**.
3. **A maior oportunidade:** com esses dados dá para detectar atraso **usando
   só a própria Novibet**, sem pagar referência. Quando o placar muda e o
   carimbo do mercado continua de antes do ponto, o preço está velho.
4. **Referência de mercado em tempo real custa dinheiro**, e a API da
   Pinnacle está fechada ao público desde julho de 2025. As opções estão na
   seção 4.

---

## 1. Teste da extensão

**O que foi feito:** a Novibet foi aberta no navegador embutido do app.
**Não houve tela da Cloudflare** desta vez. A página mostrou o banner de
cookies (recusado) e a verificação de idade (confirmada com a sua
autorização). Sem login e sem aposta.

O script da extensão (`extensao/pagina.js`) foi injetado na página já aberta,
e **não capturou nada**, embora a página seguisse buscando as odds a cada 5s.

**Por que o teste é inconclusivo, e não uma falha:**

- A extensão de verdade roda **antes** de qualquer script da página
  (`document_start`). Aqui o script entrou **depois**, com o site já montado.
- O site é um aplicativo Angular, que guarda a própria referência para fazer
  as buscas quando abre. As buscas passam por essa referência antiga, e não
  pela função que o script trocou depois.
- Conferido: o site **não desfaz** alterações de propósito. O script injetado
  continuou no lugar por 30s, sem ser trocado de volta.
- Os scripts servidos em `/gpua/...`, que também "embrulham" o `fetch`, são o
  **Google Analytics / Tag Manager** servido pelo domínio da Novibet (as
  chamadas são `/gpua/ga/g/c?...&en=page_view`). É medição de audiência, não
  proteção anti-bot.

**O que falta:** instalar a extensão no Chrome (passo a passo em
[extensao/LEIAME.md](../extensao/LEIAME.md)) e rodar
`python -m src.main --testar-extensao` com a página aberta.

**Observação:** o navegador embutido se identifica como "Claude" no
User-Agent e não foi barrado. No teste de 23/09 (D-011), o Chromium do
Playwright foi. A reação da Cloudflare pode variar por máquina e rede. Isso
**não muda** a decisão de não automatizar navegador: é só um registro.

---

## 2. O que a página da Novibet recebe

Tudo vem do mesmo domínio, por HTTP comum (sem WebSocket), no caminho
`/spt/feed/`. Os endereços abaixo foram **observados**, nunca chamados
diretamente. A regra do projeto continua: não montar requisição para a API
interna da casa.

| Feed | Quando a página busca | O que traz |
|---|---|---|
| `/spt/feed/marketviews/location/v2/4324/{torneio}/` | Página de torneio, pré-jogo, a cada ~30s | Jogos do torneio com vencedor, handicap, total de games e vencedor de set. **É o que o parser atual entende.** |
| `/spt/feed/marketviews/location/v2/4324/6051394/` e `.../4390/` | **A cada 5,0s exatos**, na página de torneio (6051394) e na de ao vivo (4390) | **Todos os jogos ao vivo** (103 na hora do teste), todos os esportes. Foto completa (~18 KB), não só as mudanças. |
| `/spt/feed/marketviews/event/4324/{jogo}` | Página de um jogo, a cada 10–30s (irregular) | Todos os mercados do jogo e **placar ponto a ponto** |
| `/spt/feed/navigation/menu/{id}` | Ao abrir a página | Menu lateral |

### Campos que valem ouro

| Campo | Onde | Para que serve |
|---|---|---|
| `liveData.referenceTime` | feeds ao vivo | Hora do **servidor** da Novibet naquela foto. Permite medir a demora da própria casa. |
| `timestamp` de cada mercado | feed do jogo | Hora em que **aquele mercado** foi reprecificado, no formato do .NET: número de intervalos de 100 nanossegundos desde o ano 1. Conversão: `(ticks − 621355968000000000) / 10⁷` = segundos Unix. Conferido: 23:03:07,8, 4,2s antes da foto. |
| `liveData` (tênis) | feed do jogo | `player1GamePoints`, `setScores`, `player1Serves`, `isInTieBreak` e `timeline` com cada game |
| `liveData` (futebol) | lista ao vivo | Gols, escanteios, cartões, fase ("2º tempo") e tempo decorrido |
| `isAvailable` | todo `betItem` | `false` = mercado suspenso. Na tela: "Mercados não disponíveis". |
| `sportradarMatchId`, `betgeniusFixtureId` | jogos | Identificador do jogo nos grandes fornecedores de dados esportivos. Veio preenchido no ATP Chengdu e vazio no ITF de Maringá. |
| `startDate` | pré-jogo | Horário em UTC (já usado pelo normalizador) |

### Formatos

- **Página de torneio:** `[ { betViews: [ { items: [ jogo ] } ] } ]`. O parser atual lê isso.
- **Lista ao vivo:** `[ { betViews: [ { competitions: [ { events: [ jogo ] } ] } ] } ]`.
  **O parser atual ignora** (devolve lista vazia, sem erro).
- **Jogo:** um objeto só, com `liveData` e `marketCategories[].items[].betViews[]`,
  e os mercados em `marketSysname` (não `betTypeSysname`). **O parser atual
  ignora.**

A extensão já captura os três formatos, porque todos passam pelo filtro
`/spt/feed/marketviews/`. O que falta é o parser entendê-los.

### Outras observações

- O parâmetro `timestamp` na URL é só um prefixo + a hora do computador de
  quem navega, em milissegundos. Não é informação da casa.
- A página carrega o `cdn.geocomply.com` (verificação de localização, usada
  para apostar). Não interfere em ver odds.
- O horário de um jogo mudou (03:10 → 04:00) enquanto a página estava aberta:
  a página se atualiza sozinha, sem recarregar.

---

## 3. Oportunidades, em ordem de valor

### A. Ler o feed "ao vivo" (todos os jogos em uma aba)
Uma única aba aberta na página de ao vivo entrega **todos os jogos em
andamento a cada 5s**, com placar e suspensão. Para "tempo real", é a fonte
certa: não precisa de uma aba por torneio.
**Trabalho:** um parser para o formato `competitions → events` e fixture
gravada com payload real.

### B. Carimbo da própria casa
Com o `timestamp` por mercado (feed do jogo) e o `referenceTime` (feeds ao
vivo), a Novibet passa a informar **quando** mexeu no preço. É o mesmo ganho
que o `updatedAt` da odds-api.io dava (D-016): o `--medir-atraso` passa a
funcionar para a Novibet brasileira, e o motor para de adivinhar por ciclo.
**Trabalho:** preencher `timestamp_fonte` no parser.

### C. Regra de atraso por evento, só com dados da Novibet
É a regra 2 da seção 3 do [projeto.md](projeto.md) ("saiu um gol/ponto e a
casa não reprecificou"), sem precisar de referência paga:

> o placar mudou na foto de 23:03:12, e o carimbo do mercado "vencedor do
> jogo" continua de antes do ponto, com o mercado aberto (`isAvailable: true`)
> → **preço velho à venda**.

**Cuidado:** o placar e o preço podem vir do mesmo fornecedor da Novibet. Se o
placar dela também atrasa, esta regra não enxerga. Por isso existe o item F.
Validar com dados antes de alertar.

### D. Identificador comum entre fontes
O `sportradarMatchId` da Novibet casa com o `externalProviders` (Betradar) que
a OddsPapi publica em cada jogo. Isso dispensa comparar nomes de jogadores
("J. Sinner" x "Jannik Sinner") quando os dois lados tiverem o id.
Limitação: no ITF de Maringá o id veio vazio.

### E. Referência de mercado em tempo real (seção 4)
Continua necessária para a regra de **desvio** (odd acima do preço justo).

### F. Placar independente e rápido
Um feed de placar de fora mostra **quando o ponto aconteceu de verdade**. Aí
dá para medir quanto a Novibet demora para suspender ou reprecificar depois
de cada ponto. É a medida mais direta do "atraso" que o apostador observou.

### G. Outros esportes
A lista ao vivo traz futebol com gols, cartões e escanteios. A mesma regra C
vale para "saiu gol e o mercado não suspendeu". Fica para depois do tênis.

### H. Motor com memória da referência
Já planejado ([diário](diario.md)): sem isso, o bot compara no ritmo da fonte
mais lenta.

---

## 4. APIs de mercado: o que existe hoje

### Referência de preço (preço "justo")

| Fonte | Pinnacle | Betfair Exchange | Tempo real | Custo |
|---|---|---|---|---|
| **Pinnacle direto** | — | — | — | API **fechada ao público desde 23/07/2025**. Só acesso sob medida: pedir por e-mail (api@pinnacle.com). |
| **The Odds API** (em uso) | ✅ (tirada do site público, "pode ter atraso") | ✅ | ❌ consulta a cada 120s | 500 créditos/mês grátis. Não dá para ao vivo. |
| **OddsPapi** | ✅ | ✅ | WebSocket só no pago | Grátis: 250 requisições/mês. Traz ids da Betradar/Sofascore em cada jogo. |
| **odds-api.io** | ✅ na página de casas deles (a D-016 dizia que não havia: **conferir**) | ✅ | WebSocket (<150 ms anunciado) | Solo £49/mês (2 casas). WebSocket dobra o preço. |
| Revendedores de Pinnacle (pinnodds, pinnapi) | ✅ | — | WebSocket | Origem do dado não informada. **Não usar** sem saber de onde vem. |
| **Betfair direto** | — | — | — | API **fechada para quem está no Brasil** desde 01/01/2025. |

### Placar ao vivo de tênis (para os itens C e F)

| Fonte | Ponto a ponto | Tempo real | Custo |
|---|---|---|---|
| **Live Tennis API** | ✅ (planos pagos) | WebSocket com carimbo `published_at` por quadro | Grátis: placar, 100 requisições/dia, sem WebSocket. Pagos de US$ 9,99 a 99,99/mês. Não informa se o dado é licenciado. |
| **tennis-api.com** | ✅ | WebSocket a partir de US$ 99/mês | Planos de US$ 10 e 39/mês só por consulta |
| **Goalserve** | ✅ | a cada 5s | ~US$ 1.000/mês |

ATP, WTA, Challenger e ITF aparecem em todos.

---

## 5. Próximos passos sugeridos

1. **Você:** instalar a extensão e rodar `--testar-extensao` com a página de
   **ao vivo** aberta. Esse é o teste que falta.
2. **Gravar payloads reais:** um modo do receptor que salva o que chega em
   `tests/fixtures/`. Sem fixture real não se escreve parser (regra do projeto).
3. **Parser dos feeds ao vivo e do jogo** (itens A e B), com `timestamp_fonte`
   vindo do carimbo da casa.
4. **Motor com memória da referência** (item H).
5. **Regra por evento** (item C), primeiro só registrando, sem alertar, para
   medir quantas vezes aconteceria.
6. **Decisão de custo** para referência (seção 4) e placar independente
   (item F). Sugestão: começar pelos planos grátis da OddsPapi e da Live
   Tennis API para validar, e só assinar depois.

## Fontes

- [Pinnacle Killed Its Public API (DEV Community)](https://dev.to/ryankr/pinnacle-killed-its-public-api-heres-how-to-get-pinnacle-odds-in-2026-with-code-39pe)
- [Access to Pinnacle API closed since July 23rd, 2025 (Arbusers)](https://arbusers.com/access-to-pinnacle-api-closed-since-july-23rd-2025-t10682/)
- [odds-api.io: Pinnacle Shut Down Their API](https://odds-api.io/blog/pinnacle-api-shutdown-alternatives)
- [odds-api.io: Pinnacle](https://odds-api.io/sportsbooks/pinnacle) · [Betfair Exchange](https://odds-api.io/sportsbooks/betfair-exchange)
- [OddsPapi: Pricing 2026](https://oddspapi.io/blog/odds-api-pricing-2026-comparison/) · [Pinnacle](https://oddspapi.io/sportsbooks/pinnacle) · [WebSocket](https://oddspapi.io/blog/websocket-odds-api-real-time-betting-data/)
- [Betfair: Brazil Direct API Access Not Available](https://support.developer.betfair.com/hc/en-us/articles/17814508363804-Brazil-Direct-API-Access-Not-Available)
- [Live Tennis API](https://livetennisapi.com/) · [tennis-api.com: preços](https://tennis-api.com/api-pricing/) · [Goalserve: tênis](https://www.goalserve.com/en/sport-data-feeds/tennis-api/prices)
- [The Odds API: documentação v4](https://the-odds-api.com/liveapi/guides/v4/)
