# Bot de Detecção de Odds Atrasadas

Robô que compara as odds de várias casas de apostas com uma referência de mercado
e avisa quando uma casa está **atrasada** — ou seja, ainda oferecendo um preço que
o resto do mercado já corrigiu.

**Escopo desta fase:** os 2 primeiros campeonatos ATP e os 2 primeiros WTA da lista:

| Circuito | Torneio |
|---|---|
| ATP | Chengdu (CHN) |
| ATP | Hangzhou (CHN) |
| WTA | Seoul (KOR) |
| WTA | Singapore (SGP) |

**Fontes de dados:**

| Fonte | O que é | Estado |
|---|---|---|
| **Opção A** — API agregadora ([The Odds API](https://the-odds-api.com)) | Odds de várias casas europeias/britânicas num formato só. Dá a **referência de mercado** (Pinnacle, exchanges). | Funcionando |
| **Opção B** — interceptador de navegador | Abre o site da casa e lê o JSON que a própria página recebe. | Código pronto e testado; **acesso bloqueado pelas duas casas** |

> **Leia antes de usar:**
> - A API agregadora **não cobre** nenhuma casa brasileira `.bet.br`
>   ([decisões D-002](docs/decisoes.md#d-002)).
> - A Novibet e a bet365 **bloqueiam navegador automatizado**
>   ([decisões D-011](docs/decisoes.md#d-011)). Este projeto **não contorna**
>   esse bloqueio.

---

## Instalação

Precisa de **Python 3.10 ou mais novo**.

```bash
python -m pip install -r requirements.txt
```

Depois, crie o arquivo de segredos a partir do exemplo:

```bash
copy .env.example .env
```

Abra o `.env` e preencha:

- `ODDS_API_KEY` — chave gratuita em https://the-odds-api.com (obrigatória)
- `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` — opcionais; sem eles os alertas saem só no terminal

O `.env` **não vai para o GitHub** (está no `.gitignore`).

---

## Como usar

**1. Antes de tudo, veja o que a API cobre e quanto isso custa:**

```bash
python -m src.main --diagnostico
```

Esse comando mostra, para cada um dos 4 torneios, se a API tem dados, quantos
créditos restam na sua conta e por quantas horas o saldo dá.

**2. Uma coleta só, para testar:**

```bash
python -m src.main --uma-vez
```

**3. Rodando de verdade (fica em loop até você apertar Ctrl+C):**

```bash
python -m src.main
```

**4. Relatório do que já foi coletado (a entrega da Fase 2):**

```bash
python -m src.main --relatorio
```

**Rodar os testes:**

```bash
python -m pytest -q
```

---

## Opção B — interceptador de navegador

Abre a página da casa num Chromium de verdade e lê o JSON que a **própria
página** recebe. Não inventa requisição, não faz login e não aposta.

Precisa do Playwright (não vem no `requirements.txt` porque é pesado):

```bash
python -m pip install playwright
```

```bash
python -m playwright install chromium
```

Ligue e desligue em `fontes.navegador` no `config/config.json`.

### Estado real: as duas casas bloqueiam

Testado ao vivo em 23/09/2026:

- **bet365.bet.br** — o painel de odds responde *"Não é possível exibir este
  conteúdo"*.
- **novibet.bet.br** — a Cloudflare interrompe com *"Executando verificação de
  segurança / proteção contra bots maliciosos"*.

**Este projeto não contorna esse bloqueio** — sem plugin de disfarce, sem
falsificar impressão digital, sem resolver CAPTCHA. É regra do projeto
(`CLAUDE.md`) e é o que evita ter a conta limitada.

O que o bot faz é **reconhecer** a tela de bloqueio e parar com mensagem clara,
em vez de rodar horas sem coletar nada.

Se quiser tentar com o seu próprio navegador, existe:

```bash
python -m src.main --preparar-navegador
```

Ele abre uma janela **visível** para **você** passar pelas telas uma vez. O bot
não resolve nada; só reaproveita o perfil depois. Se não passar, o certo é
desligar a Opção B para aquela casa.

> Automatizar acesso costuma contrariar os termos de uso das casas. Leia a
> seção 6 de [docs/projeto.md](docs/projeto.md) antes.

### Quando o acesso existir, já está tudo pronto

O parser da Novibet foi escrito sobre um **payload real capturado do site** e
está coberto por testes. O ponto central já é testado: um jogo da Novibet gera
**o mesmo `evento_id_normalizado`** que a API agregadora gera, então o motor
compara a casa brasileira contra a referência de mercado sem saber de onde cada
preço veio.

Para adicionar uma casa nova, escreva um parser em `src/adapters/casas/` —
o interceptador e o resto do bot não mudam.

---

## ⚠️ Cuidado com o consumo da API

O plano gratuito dá **500 créditos por mês**. Cada ciclo de coleta custa
`torneios × regiões × mercados` créditos — com a configuração padrão (4 torneios,
2 regiões, 1 mercado), são **8 créditos por ciclo**.

No intervalo padrão de 120 segundos, o plano gratuito acaba em **cerca de 2 horas
e meia de bot ligado**.

Por isso o bot tem duas travas, ambas no `config/config.json`:

- `parar_com_creditos_restantes` — para sozinho antes de zerar a conta;
- `limite_creditos_por_execucao` — teto de gasto por execução.

**Recomendação:** ligue o bot só durante as janelas de jogos dos torneios
monitorados, não 24 horas por dia.

---

## Como o bot decide que uma casa está atrasada

Para cada jogo, mercado e seleção, o bot escolhe uma **casa de referência**
(Pinnacle, ou uma exchange como Betfair/Smarkets) e calcula o **preço justo** dela
— a odd sem a margem da casa. Depois aplica duas regras:

| Regra | Dispara quando | Ajuste no config |
|---|---|---|
| **Desvio** | A odd da casa está acima do preço justo por mais que o limiar, e continua assim por N segundos | `desvio_minimo`, `duracao_minima_segundos` |
| **Atraso** | A referência mexeu de forma relevante e a casa não acompanhou dentro de N segundos | `movimento_referencia_minimo`, `atraso_maximo_segundos` |

A regra de **atraso** é a que responde direto ao objetivo do projeto. A de
**desvio** serve de rede de segurança: pega a casa lenta mesmo quando o bot não
viu o momento exato em que a referência mexeu.

Tudo que é coletado e todo alerta disparado ficam gravados em
`dados/historico.db` (SQLite), para o relatório da Fase 2.

---

## Estrutura

```
config/config.json       Torneios, limiares, referência — mexa aqui, não no código
src/modelos.py           O schema único de odd que todas as fontes produzem
src/adapters/            Fontes de dados (hoje: the_odds_api.py = Opção A)
src/normalizador/        Faz "J. Sinner" e "Jannik Sinner" virarem o mesmo jogo
src/comparador/          Memória de preços + as duas regras de detecção
src/alertas/             Console e Telegram
src/armazenamento/       Histórico em SQLite
src/main.py              Junta tudo: coletar → comparar → alertar → gravar
tests/                   Testes, todos sem acesso à internet
docs/projeto.md          O plano completo do projeto
docs/decisoes.md         Decisões tomadas e o porquê
docs/diario.md           O que foi feito em cada sessão
docs/retrospectiva.md    Balanço: o que deu certo e o que deu errado
```

Quando chegar a Fase 3 (adapters próprios por casa, via WebSocket), basta criar
um novo arquivo em `src/adapters/` que implemente `AdapterDeOdds`. O resto do bot
não muda.

---

## Riscos

Leia a seção 6 de [docs/projeto.md](docs/projeto.md) antes de usar isto com
dinheiro real. Em resumo: as casas proíbem acesso automatizado, podem limitar a
conta e podem anular apostas feitas em odd "palpavelmente errada".

Este projeto **não contorna** CAPTCHA, Cloudflare ou qualquer proteção anti-bot.

---

## Testar a hipótese da Novibet GR

A Novibet Brasil não é coberta por nenhum agregador. Mas a **Novibet GR**
(Grécia) está disponível na [odds-api.io](https://odds-api.io), e a Novibet roda
a mesma plataforma nos vários mercados.

Se o atraso for característica do motor de precificação da casa, a versão grega
mostra o mesmo comportamento — e esse dado está à venda, sem bloqueio nenhum.

**Passo 1 — conseguir uma chave.** O tier gratuito está **pausado por tempo
indeterminado**, e mesmo aberto ele só dá casas recreativas — a referência
(Betfair Exchange / ON Sharp) exige plano pago. O plano **Solo (R$359/mês,
2 casas)** cobre o teste: Novibet GR + Betfair Exchange. Antes de assinar,
confirme com o suporte se você escolhe quais são as 2 casas.

Com a chave em mãos, ponha no `.env`:

```
ODDS_API_IO_KEY=sua_chave_aqui
```

**Passo 2 — ligar a fonte** no `config/config.json`:

```json
"odds_api_io": { "ativo": true }
```

Para uma medida mais confiável, vale também `"filtrar_torneios": false` — pega
o circuito inteiro em vez de só os 4 torneios, o que dá muito mais amostras.

**Passo 3 — deixar rodar durante os jogos:**

```bash
python -m src.main
```

**Passo 4 — ler o resultado:**

```bash
python -m src.main --medir-atraso
```

Sai uma tabela com a mediana, a média e o máximo de atraso de cada casa, e em
quantos % das vezes ela ficou parada mais de 60 segundos. A casa no topo é a
mais atrasada.

> **O limite honesto:** Novibet GR e Novibet BR são mercados diferentes. Se a
> grega atrasar, é indício forte de que o comportamento é da plataforma — não
> prova sobre a brasileira. Se a grega **não** atrasar, a hipótese morre e a
> conclusão é limpa.
