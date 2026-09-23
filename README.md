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

**Fonte de dados desta fase:** Opção A do plano — a API agregadora
[The Odds API](https://the-odds-api.com).

> **Leia antes de usar:** a API agregadora **não cobre** nenhuma casa brasileira
> `.bet.br` (Novibet, bet365.bet.br). Veja [docs/decisoes.md](docs/decisoes.md#d-002)
> para entender o que isso significa e o que foi decidido.

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
