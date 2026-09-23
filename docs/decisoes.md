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

## D-009 — Nenhuma dependência externa além do pytest
**Data:** 2026-09-23
**Decisão:** o bot roda só com a biblioteca padrão do Python.
**Motivo:** menos coisa para instalar e quebrar na máquina de quem não é
programador. `urllib` resolve as chamadas HTTP, `sqlite3` e `json` já vêm juntos.
