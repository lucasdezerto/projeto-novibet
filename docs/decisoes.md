# Registro de decisões

Toda decisão de arquitetura entra aqui, com data e motivo. O Claude Code lê este
arquivo antes de começar qualquer tarefa nova.

---

## D-001 — Começar pela Opção A (API agregadora)
**Data:** 2026-09-23
**Decisão:** o coletor da Fase 1 usa a The Odds API, não scraping nem WebSocket.
**Motivo:** é a opção mais rápida de construir e a mais barata de manter, conforme
a tabela da seção 2 de [projeto.md](projeto.md). O objetivo da Fase 1 é **medir**,
não operar: só vale a pena construir adapter próprio (Opção B) para as casas que
comprovadamente atrasam.

---

## D-002 — A API agregadora não cobre casas brasileiras `.bet.br`
**Data:** 2026-09-23
**Constatação (verificada na documentação oficial da The Odds API):** as regiões
disponíveis são `us`, `us2`, `us_dfs`, `us_ex`, `uk`, `eu`, `au`, `ca`, `fr`, `se`
e `fi`. **Não existe região `br`.** Nem Novibet, nem bet365.bet.br, nem nenhuma
outra casa `.bet.br` aparece na lista de casas cobertas.

**O que isso significa:** nesta fase o bot **não consegue** apontar que a Novibet
ou a bet365 brasileira estão atrasadas. Ele detecta atraso entre as casas que a
API cobre (europeias e britânicas).

**Decisão:** seguir mesmo assim, por três motivos:
1. O motor de comparação, o normalizador e os alertas são **independentes da
   fonte**. Eles são construídos e validados agora com dados reais e são os mesmos
   que vão rodar quando entrarem as casas brasileiras.
2. A Fase 2 (medição) continua válida: dá para medir quanto e com que frequência
   uma casa atrasa, e calibrar os limiares com dados de verdade.
3. A referência de mercado (Pinnacle / exchanges) vem da API agregadora e é
   exatamente o que as casas brasileiras vão ser comparadas contra na Fase 3.

**Consequência para o plano:** Novibet e bet365.bet.br só entram via **Opção B**
(adapter próprio por casa), na Fase 3. A interface `AdapterDeOdds` já está pronta
para receber esses adapters sem mexer no resto do bot.

---

## D-003 — Só 1 dos 4 torneios do escopo está na lista pública da API
**Data:** 2026-09-23
**Constatação:** na lista publicada de esportes da The Odds API, entre os 4
torneios do escopo só **WTA Singapore** (`tennis_wta_singapore_open`) aparece.
ATP Chengdu, ATP Hangzhou e WTA Seoul não têm chave publicada.

**Decisão:** não deixar as chaves fixas no código. O adapter consulta o endpoint
`/v4/sports` em tempo de execução e resolve cada torneio em duas etapas:
1. tenta as `chaves_api` listadas no `config.json`;
2. se nenhuma existir, procura pelo título usando `termos_nome` + o circuito
   (ATP/WTA), para não confundir o torneio masculino com o feminino da mesma cidade.

**Motivo:** a lista publicada fica desatualizada e a API só expõe torneios que
estão em temporada. A resolução dinâmica faz o bot funcionar assim que o torneio
entrar no ar, sem precisar mexer no código. Torneios que não forem encontrados
aparecem no aviso do `--diagnostico` em vez de derrubar a coleta.

**Verificar:** rode `python -m src.main --diagnostico` com a chave configurada
para ver quais dos 4 torneios a API realmente tem hoje.

---

## D-004 — Preço justo calculado sem a margem da casa
**Data:** 2026-09-23
**Decisão:** antes de comparar, o bot remove o *overround* da casa de referência,
redistribuindo as probabilidades implícitas do mercado.
**Motivo:** sem isso, toda casa pareceria "cara" em relação à referência e o
limiar de desvio viraria chute. Com a margem removida, o número que sai no alerta
("odd 5,2% acima do preço justo") tem significado real.
**Como desligar:** `referencia.remover_margem = false` no `config.json`.

---

## D-005 — Duas regras de detecção, não uma
**Data:** 2026-09-23
**Decisão:** o motor roda `atraso` (referência mexeu, casa não acompanhou) **e**
`desvio` (odd acima do preço justo por N segundos).
**Motivo:** o `atraso` é a definição literal do objetivo, mas só dispara se o bot
tiver visto o exato ciclo em que a referência mexeu. Com intervalo de coleta de
120s, muita coisa acontece entre um ciclo e outro. O `desvio` pega a mesma casa
lenta por outro caminho. Os alertas saem etiquetados para dar para separar depois
quais regras produzem alerta bom e quais produzem ruído.

---

## D-006 — Código síncrono, não asyncio
**Data:** 2026-09-23
**Decisão:** a Fase 1 é um laço simples com `time.sleep`, sem `asyncio`.
**Motivo:** a Opção A é uma consulta REST a cada 120 segundos — nada aqui se
beneficia de concorrência, e código síncrono é muito mais fácil de ler para quem
não é programador. O `asyncio` da proposta original faz sentido na Fase 3, quando
entrarem vários WebSockets ao mesmo tempo, e ficará contido dentro dos adapters.

---

## D-007 — SQLite em vez de Postgres/TimescaleDB
**Data:** 2026-09-23
**Decisão:** o histórico da Fase 2 fica num arquivo SQLite.
**Motivo:** não exige instalar nem manter servidor de banco. O volume da Fase 2
(4 torneios, coleta a cada 2 minutos) cabe folgado. A troca para Postgres é direta
se o projeto chegar à operação 24/7 da Fase 4.

---

## D-008 — Sem Redis nesta fase
**Data:** 2026-09-23
**Decisão:** o Redis da arquitetura da seção 4 do projeto não entra agora.
**Motivo:** o Redis existe para desacoplar vários adapters rodando em processos
separados. Com uma única fonte num único processo, ele só acrescentaria uma peça
para instalar e manter. Entra na Fase 3, junto com o segundo adapter.

---

## D-010 — A Novibet é polling HTTP, não WebSocket
**Data:** 2026-09-23
**Constatação (observada no navegador):** a página de torneio da Novibet **não
abre nenhum WebSocket**. Ela busca um JSON por HTTP a cada ~5 segundos:

```
GET /spt/feed/marketviews/location/v2/{grupo}/{locationId}/
    ?lang=pt-BR&timeZ=...&oddsR=1&usrGrp=BR&timestamp={cursor}
```

**Decisão:** o interceptador escuta as duas coisas — respostas HTTP e quadros
de WebSocket — para servir a qualquer casa. O parser da Novibet só filtra pelo
caminho `/spt/feed/marketviews/`.

**Consequência boa:** o piso de latência da Novibet é o ciclo dela de ~5s, não
milissegundos. A vantagem da Opção B sobre a Opção A aqui é menor do que o
plano supunha — mas ainda é grande (5s contra dezenas de segundos).

**IDs dos torneios do escopo na Novibet:** Chengdu 5931297, Hangzhou 5929344,
Seoul 4494906, Singapore 6190873 (estão no `config.json`).

---

## D-011 — As duas casas brasileiras bloqueiam navegador automatizado
**Data:** 2026-09-23

**bet365.bet.br:** o menu lateral carrega, mas o painel de odds devolve
**"Não é possível exibir este conteúdo"**.

**novibet.bet.br:** com Chromium automatizado, a Cloudflare interrompe com
**"Executando verificação de segurança / proteção contra bots maliciosos"**
(Ray ID). O site funciona normalmente num navegador comum — o bloqueio é
específico para automação.

**Decisão:** **não contornar.** Nada de plugin de disfarce, falsificação de
impressão digital ou solução de CAPTCHA. Isso está proibido no CLAUDE.md e na
seção 6 de [projeto.md](projeto.md), e é o tipo de coisa que leva à limitação
da conta.

**O que foi feito em vez disso:**
1. Os parsers declaram os textos de bloqueio de cada casa. O interceptador
   reconhece a tela e levanta `CasaBloqueada`, que para o bot com mensagem
   clara em vez de deixá-lo rodando sem coletar nada.
2. Existe `--preparar-navegador`: abre uma janela **visível** para **você**
   passar pelas telas uma vez. O bot não resolve nada; ele só reaproveita o
   perfil depois. Se as telas não passarem, a resposta certa é desligar a
   Opção B para aquela casa.
3. O caminho legítimo para ter esses dados é acesso autorizado (API de
   parceiro), não burlar a detecção.

**Estado:** o parser da Novibet está pronto e testado contra payload real
capturado do site. Falta só o acesso. O da bet365 é um esqueleto honesto.

---

## D-012 — Uma fonte com problema não derruba as outras
**Data:** 2026-09-23
**Decisão:** `coletar_de_todas_as_fontes` isola cada fonte: bloqueio, erro de
rede, parser quebrado ou exceção inesperada viram log e lista vazia.
**Motivo:** o bot existe para comparar. Comparar com uma fonte a menos ainda
vale alguma coisa; cair não vale nada. A única exceção que interrompe tudo é
o fim dos créditos da API, porque insistir aí custa dinheiro.

---

## D-013 — Monitor de saúde das fontes
**Data:** 2026-09-23
**Decisão:** `src/adapters/monitor.py` acompanha há quanto tempo cada fonte não
traz odds e avisa uma vez por episódio.
**Motivo:** o modo de falhar mais comum de adapter próprio é silencioso — o
site muda o formato e o parser passa a devolver vazio. Pior: uma fonte morta
faz o motor achar que a casa está "parada" e disparar **alerta de atraso que é
só o bot quebrado**. O monitor separa uma coisa da outra.

---

## D-014 — Levantamento de agregadores: ninguém cobre a Novibet Brasil
**Data:** 2026-09-24

Cinco provedores verificados, procurando especificamente por Novibet `.bet.br`:

| Provedor | Novibet BR | bet365 BR | Outras casas BR |
|---|---|---|---|
| The Odds API | ❌ | ❌ | ❌ nenhuma (não existe região `br`) |
| OpticOdds | ❌ | ❌ | ✅ Betnacional, Galera.bet, Parimatch Brazil |
| odds-api.io | ❌ | ❌ | ✅ Betano BR, BetMGM BR, Rivalo BR, Sportingbet BR, Stake.bet.br, Vbet BR |
| OddsPapi | ❌ | ✅ **sim** | ✅ Betano BR, betboo BR, BetMGM BR, Blaze BR, Brazino777 BR, EstrelaBet BR, KTO BR, Sportingbet BR, Stake BR, Superbet BR |
| Oddsmarket | ❌ | — | não publica a lista |

**A ausência é significativa, não é erro de nome.** Todos esses provedores
separam variantes por país (Betano BR ≠ Betano PT). O odds-api.io lista
"Novibet" e "Novibet GR" — mas **não** "Novibet BR", enquanto lista seis outras
casas com sufixo BR. Ou seja: eles sabem distinguir, e simplesmente não cobrem
a Novibet brasileira.

**Descoberta útil:** a **bet365 BR está disponível** na OddsPapi. A casa que o
navegador não alcança, um agregador entrega.

---

## D-015 — Acesso direto ao feed da Novibet também está bloqueado
**Data:** 2026-09-24

Testei se o endpoint público da Novibet responde a um cliente HTTP comum,
**identificado honestamente** (User-Agent dizendo o que o bot é, sem disfarce).
Não é contorno: é verificar se o dado é publicamente acessível.

**Resultado: HTTP 403** nos dois endpoints, com a página `Just a moment...` da
Cloudflare. O bloqueio não é só contra navegador automatizado — é contra
qualquer cliente que não passe pelo desafio.

**Decisão:** o teste para aqui. Não haverá tentativa de disfarce de
User-Agent, impressão digital, proxy residencial ou resolução de CAPTCHA —
nem para uso próprio, nem para um produto a ser vendido. Distribuir uma
ferramenta de evasão é pior que usá-la.

**Conclusão combinada com [D-014](#d-014):** hoje **não existe caminho
programático legítimo** para as odds da Novibet Brasil. As saídas são pedir a
cobertura aos agregadores, buscar acordo de dados com a casa, ou trocar a casa
monitorada.

---

## D-016 — Testar a hipótese "o atraso é da plataforma Novibet"
**Data:** 2026-09-24

**A ideia:** a Novibet Brasil não é coberta por ninguém, mas a **Novibet GR**
(Grécia) está disponível na odds-api.io, ativa desde 20/08/2026. A Novibet roda
a mesma plataforma nos vários mercados. Se o atraso que o apostador observou é
característica do **motor de precificação** da casa, a versão grega deve exibir
o mesmo comportamento — e esse dado está à venda, sem bloqueio nenhum.

**Confirmado sem precisar de conta** (os endpoints `/sports` e `/bookmakers` da
odds-api.io são abertos):
- `Novibet` e `Novibet GR`, ambas `active: true`;
- tênis suportado (`slug: tennis`);
- referência disponível: `Betfair Exchange` e `ON Sharp` (linha sharp de
  consenso). Não há Pinnacle.

**O ganho técnico inesperado:** essa API devolve **`updatedAt` por casa e por
mercado**. Ou seja, a casa informa quando reprecificou. Nas outras fontes o bot
precisava inferir isso comparando ciclos; aqui o carimbo é da própria fonte.
Isso torna a medida de atraso muito mais precisa e permitiu criar o relatório
`--medir-atraso`.

**O limite honesto da hipótese:** Novibet GR e Novibet BR são mercados
diferentes, com liquidez e possivelmente equipe de trading diferentes. Se a
grega atrasar, isso é **indício forte** de que o comportamento é da plataforma,
não prova de que a brasileira atrasa igual. Se a grega **não** atrasar, aí sim
a conclusão é limpa: a hipótese morre e a operação brasileira teria que ser
observada de outro jeito.

**Implementado:** `src/adapters/odds_api_io.py`, desligado por padrão no
config (`fontes.odds_api_io.ativo: false`), e `--medir-atraso` para ler o
resultado.

**Atualização 24/09 — o tier gratuito não serve (e nem existe agora):**

1. **"As novas chaves de API gratuitas estão pausadas por tempo
   indeterminado."** Chaves gratuitas antigas continuam ativas.
2. Mesmo se estivesse aberto, o plano gratuito dá **"2 casas recreativas"** e
   **"casas sharp e exchanges exigem plano pago"**. A Novibet é recreativa
   (não está na lista de restritas), mas a **referência** — Betfair Exchange,
   ON Sharp — é justamente o que o gratuito não entrega.

**Preços (plano mensal, cobrado em R$):** Solo R$359 (2 casas), Starter R$729
(5), Growth R$1.299 (10), Pro R$1.699 (15).

**O plano Solo basta para o teste:** as 2 casas seriam **Novibet GR + Betfair
Exchange** (ou ON Sharp). Vale insistir em tirar as duas do **mesmo provedor**:
assim os jogos são exatamente os mesmos dos dois lados, com o mesmo id de
evento. Usar a referência da The Odds API sairia de graça, mas a cobertura de
tênis dela é por torneio e pode simplesmente não ter os mesmos jogos —
ficaríamos sem com quem comparar.

**A confirmar antes de pagar:** a página não diz se o cliente **escolhe** quais
são as 2 casas do Solo, e não achei menção a teste grátis nem a reembolso.
Perguntar ao suporte antes de assinar.

---

## D-017 — Duas pessoas, duas máquinas, uma `main`
**Data:** 2026-09-24
**Contexto:** o projeto passou a ter dois desenvolvedores em máquinas
diferentes, um deles não técnico. O CLAUDE.md tinha o caminho do Python de uma
máquina só, o que quebrava os comandos na outra.

**Decisão:**
1. **Nada específico de máquina nos arquivos compartilhados.** O CLAUDE.md
   lista onde procurar o Python, em ordem. O que vale só para uma máquina fica
   no `CLAUDE.local.md` (fora do Git), e as chaves continuam no `.env`.
2. **Ambiente do projeto em `.venv`** para máquinas novas. A máquina original
   continua com o Python que já tinha, sem precisar fazer nada.
3. **`git pull` antes de começar; testes + `git pull --rebase` + testes antes
   de enviar.** A `main` fica sempre com os testes passando.
4. **`docs/diario.md` e `docs/decisoes.md` usam junção automática**
   (`merge=union` no `.gitattributes`): os dois acrescentam entradas nesses
   arquivos e isso não deve virar conflito para quem não é técnico.
5. **Dependência nova só com registro aqui e instrução no README.**

**Motivo:** quem não é técnico não consegue resolver conflito de Git nem
descobrir por que um comando parou de funcionar. O padrão garante que a
máquina dele continue funcionando sem nenhuma ação da parte dele.

---

## D-018 — Opção B por extensão do Chrome, com uma pessoa navegando
**Data:** 2026-09-24
**Decidido por:** Kevin

**Contexto:** a Novibet é exigência do cliente. Nenhum agregador a cobre
(D-014), o acesso direto dá 403 (D-015) e ela bloqueia navegador
automatizado (D-011). O teste com a Novibet GR (D-016) foi descartado.

**Decisão:** a Novibet entra por uma extensão do Chrome (pasta `extensao/`)
instalada no navegador **normal** de uma pessoa. A pessoa abre as páginas de
torneio. A extensão copia as respostas de odds que a própria página pediu e
entrega ao bot em `127.0.0.1`. O resto do bot (parser, motor, alertas) é o
mesmo.

**Por que isto não é contornar a proteção:** quem passa pela Cloudflare é uma
pessoa num navegador comum, que é exatamente o que a verificação existe para
permitir. A extensão não disfarça nada, não altera impressão digital e não
resolve desafio. Os limites, travados em teste (`tests/test_extensao.py`):
- a extensão não faz requisição ao site, não recarrega, não clica;
- só pede permissão para falar com `127.0.0.1:8765` e só roda na Novibet;
- a resposta que a página recebe fica intacta;
- tela de verificação na aba vira `CasaBloqueada`, e quem resolve (ou não) é
  a pessoa;
- o receptor recusa pedidos vindos de sites, para ninguém injetar odds falsas.

**Risco aceito:** os termos de uso das casas costumam proibir coleta
automatizada (seção 6 do projeto). Não há login nem aposta automática, mas o
risco contratual existe e foi aceito conscientemente.

**Limite atual:** o bot ainda compara em ciclos de 120s, porque o motor só
compara odds que chegam no mesmo ciclo e a referência (The Odds API) é cara
de consultar. A Novibet chega a cada ~5s e a hora de cada mudança é
preservada, mas o alerta sai no ritmo do ciclo. O próximo passo é o motor
lembrar a última referência, para rodar em ciclos curtos.

---

## D-009 — Nenhuma dependência externa além do pytest
**Data:** 2026-09-23
**Decisão:** o bot roda só com a biblioteca padrão do Python.
**Motivo:** menos coisa para instalar e quebrar na máquina de quem não é
programador. `urllib` resolve as chamadas HTTP, `sqlite3` e `json` já vêm juntos.
