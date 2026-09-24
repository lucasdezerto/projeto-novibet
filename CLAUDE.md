# Projeto Novibet — Bot de Detecção de Odds Atrasadas

Bot que detecta casas de apostas com odds atrasadas em relação ao mercado.
Plano completo em `docs/projeto.md`.

Quem está usando o Claude Code **não é programador**. Explique em português
simples o que foi feito e por quê.

## Fluxo de trabalho

O projeto é desenvolvido por duas pessoas, em duas máquinas. Ver `docs/decisoes.md` D-017.

- **Antes de começar qualquer tarefa:** `git pull` na `main`, para trabalhar
  sobre a versão mais nova.
- Ao finalizar cada tarefa, o merge para a branch `main` é automático.
- **Antes de enviar para o GitHub:** rode os testes. Se falharem, não envie.
  Depois `git pull --rebase` e rode os testes de novo, porque a outra pessoa
  pode ter mudado algo no meio do caminho.
- Nada que só vale para uma máquina entra nos arquivos compartilhados
  (caminhos de pasta, chaves, senhas). Isso vai no `.env` ou no
  `CLAUDE.local.md`, que ficam fora do Git.
- Dependência nova (pacote para instalar) só com registro em
  `docs/decisoes.md` e instrução de instalação no README. Senão o bot quebra
  na máquina da outra pessoa.
- No `docs/diario.md`, comece cada entrada com a data e o nome de quem fez.

## Regras

- Leia `docs/decisoes.md` antes de começar. Siga as decisões já registradas.
- Não contorne CAPTCHA, Cloudflare ou qualquer proteção anti-bot. Se um site
  bloquear, pare e avise.
- Nunca coloque chaves de API ou senhas no código. Use o `.env` (fora do Git).
- Toda função nova precisa de teste. Testes não acessam a internet: use os
  payloads gravados em `tests/fixtures/`.
- Ao final de cada sessão, adicione um resumo em `docs/diario.md`.
- Decisões de arquitetura novas vão para `docs/decisoes.md` com data e motivo.
- Cuidado com o consumo da API agregadora: o plano gratuito tem 500 créditos
  por mês. Não escreva código que faça chamadas em laço sem trava.

## Comandos

O Python **não está no PATH** e fica num lugar diferente em cada máquina.
Use o primeiro destes que existir:

1. O que estiver indicado no `CLAUDE.local.md` desta máquina, se houver.
2. `.venv\Scripts\python.exe` (ambiente do próprio projeto).
3. `C:\Users\Admin\AppData\Local\Programs\Python\Python312\python.exe`

Nos comandos abaixo, `python` quer dizer esse executável.

- Rodar os testes: `python -m pytest -q`
- Ver a cobertura da API e o custo em créditos: `python -m src.main --diagnostico`
- Uma coleta só: `python -m src.main --uma-vez`
- Rodar o bot: `python -m src.main`
- Relatório do histórico: `python -m src.main --relatorio`

## Estrutura

- `config/config.json` — torneios, limiares e referência. Ajustes vão aqui, não
  no código.
- `src/adapters/` — fontes de dados. Hoje só a API agregadora (Opção A). Adapters
  próprios por casa (Opção B) entram aqui na Fase 3, implementando `AdapterDeOdds`.
- `src/comparador/motor.py` — as duas regras que decidem o que é atraso.

## Opção B (interceptador de navegador)

- As casas `.bet.br` bloqueiam navegador automatizado (ver `docs/decisoes.md`
  D-011). **Não contorne.** Nada de plugin de disfarce, falsificação de
  impressão digital ou solução de CAPTCHA. Se bloquear, pare e avise.
- O interceptador só lê o que a página já recebe sozinha. Não monte requisição
  para a API interna da casa.
- Parser novo vai em `src/adapters/casas/`, implementando `ParserDeCasa`.
- Todo parser precisa de teste com payload real gravado em `tests/fixtures/`.
- Playwright é opcional: o bot e os testes têm que funcionar sem ele instalado.
