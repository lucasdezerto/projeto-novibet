# Projeto Novibet — Bot de Detecção de Odds Atrasadas

Bot que detecta casas de apostas com odds atrasadas em relação ao mercado.
Plano completo em `docs/projeto.md`.

Quem está usando o Claude Code **não é programador**. Explique em português
simples o que foi feito e por quê.

## Fluxo de trabalho

- Ao finalizar cada tarefa, o merge para a branch `main` é automático.

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

O Python **não está no PATH**. Use o caminho completo:

```
C:\Users\Admin\AppData\Local\Programs\Python\Python312\python.exe
```

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
