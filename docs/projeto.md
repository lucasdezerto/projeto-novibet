# Projeto: Bot de Detecção de Odds Atrasadas

## 1. Visão geral

**Oportunidade:** algumas casas de apostas demoram para atualizar suas odds (principalmente ao vivo, após gols, cartões etc.). Durante esse atraso, a odd oferecida fica "desatualizada" em relação ao mercado.

**Solução:** um robô que coleta odds de várias casas, compara com uma referência confiável e dispara um alerta quando uma casa está atrasada.

**Modelo de trabalho:**
- **Construtor:** pessoa não técnica, usando Claude Code para escrever o código.
- **Desenvolvedor (Zeno):** toma as decisões de arquitetura, revisa o trabalho e destrava problemas técnicos.

---

## 2. Formas de coletar as odds

| Opção | Como funciona | Latência | Esforço para construir | Esforço para manter |
|---|---|---|---|---|
| **A. API agregadora** | Serviços como The Odds API, OddsJam API, OpticOdds, SportsDataIO entregam odds de várias casas num formato único | Segundos a dezenas de segundos | Baixo | Baixo (o fornecedor mantém) |
| **B. Interceptar WebSocket/XHR** | Abre o site com Playwright/Puppeteer e lê o JSON que o próprio site recebe | Milissegundos (a melhor) | Alto (um adapter por casa) | Alto (quebra quando o site muda) |
| **C. Scraping de DOM** | Browser headless lendo o HTML da página | Ruim | Médio | Alto e frágil |
| **D. Ferramenta pronta** | BetBurger, RebelBetting, OddsJam etc. | Varia | Nenhum | Nenhum (assinatura) |

**Pontos de atenção:**
- API agregadora pode ser **mais lenta que a própria casa atrasada**, o que a torna inútil para ao vivo.
- Muitas casas brasileiras (.bet.br) podem **não estar cobertas** pelas APIs agregadoras. Verificar antes de contratar.
- Opção C só faz sentido como último recurso, e para pré-jogo.

### Resumo da comparação

- **Mais rápida em latência:** B (WebSocket).
- **Mais rápida de construir:** A (API agregadora).
- **Mais viável de manter:** A, com folga.
- **Regra de decisão:** pré-jogo → A resolve. Ao vivo → só B funciona de verdade.

---

## 3. Como detectar que uma casa está atrasada

É preciso uma **referência de verdade** e comparar todas as casas com ela.

1. **Referência de mercado:** usar uma casa "sharp" (Pinnacle) ou uma exchange (Betfair Exchange, que tem API oficial) como preço justo. Se a casa X está com odd bem acima da referência por mais de N segundos → alerta.
2. **Referência de evento:** feed de placar/eventos ao vivo. Se saiu um gol e a casa X não suspendeu nem reprecificou o mercado em T segundos → alerta.
3. **Staleness por timestamp:** registrar o momento da última mudança de odd de cada casa, por mercado. Se todas mexeram e uma ficou parada → atrasada.

**Parte mais trabalhosa: mapeamento de eventos entre casas.** "Flamengo x Palmeiras" tem nome, ID e horário diferentes em cada site. Precisa de um normalizador (comparação aproximada dos nomes dos times + horário de início).

---

## 4. Arquitetura sugerida

```
[Adapter Casa 1] ─┐
[Adapter Casa 2] ─┼─> Redis (streams/pubsub) ─> Motor de comparação ─> Bot Telegram/Discord
[Referência]     ─┘         (schema único)            │
                                                       └─> Postgres/TimescaleDB (histórico)
```

- **Adapters:** um por fonte, cada um coleta e converte as odds para um schema único.
- **Redis:** fila/canal onde todas as odds normalizadas chegam.
- **Motor de comparação:** compara com a referência e aplica os limiares.
- **Alertas:** Telegram (mais simples e rápido de receber no celular).
- **Histórico:** banco para medir quanto e com que frequência cada casa atrasa.
- **Stack:** Python (asyncio + Playwright) ou Node. Para ao vivo, hospedar perto dos servidores das casas.

### Schema único de odd (sugestão inicial)

```json
{
  "casa": "nome_da_casa",
  "evento_id_normalizado": "flamengo-palmeiras-2026-10-01T21:30",
  "mercado": "1x2",
  "selecao": "casa",
  "odd": 2.15,
  "suspenso": false,
  "timestamp_coleta": "2026-10-01T21:47:12.345Z"
}
```

---

## 5. Plano de execução

A estratégia é **medir antes de investir**: só construir adapters caros para as casas que comprovadamente atrasam.

### Fase 0 — Validação sem código (1 semana)
- [ ] Listar as casas que queremos monitorar.
- [ ] Verificar quais aparecem em alguma API agregadora (The Odds API tem plano gratuito para testar).
- [ ] Testar uma ferramenta pronta (opção D) por alguns dias para ver se a oportunidade existe nessas casas.
- [ ] Definir o foco: **pré-jogo** ou **ao vivo**.

**Decisão ao final:** seguir? Com quais casas? Pré-jogo ou ao vivo?

### Fase 1 — MVP de medição (1–2 semanas)
- [ ] Projeto base com Git + GitHub.
- [ ] Coletor usando API agregadora (opção A).
- [ ] Referência via Betfair Exchange API (ou Pinnacle na API agregadora).
- [ ] Normalizador de eventos.
- [ ] Motor de comparação simples (diferença de odd + tempo).
- [ ] Alerta no Telegram.
- [ ] Salvar tudo no banco para análise.

**Entregável:** bot rodando e logando atrasos.

### Fase 2 — Coleta de dados (2–4 semanas rodando)
- [ ] Deixar o MVP rodando e acumular histórico.
- [ ] Relatório por casa: frequência de atraso, duração média, diferença média de odd.
- [ ] Ajustar limiares para reduzir alertas falsos.

**Decisão ao final:** quais 2–3 casas justificam um adapter próprio?

### Fase 3 — Adapters de baixa latência (por casa)
- [ ] Um adapter WebSocket (opção B) por vez, só para as casas escolhidas.
- [ ] Testes automatizados com payloads gravados (para detectar quando o site muda o formato).
- [ ] Monitor de saúde: alerta se um adapter parar de receber dados.

### Fase 4 — Operação
- [ ] Hospedagem 24/7 (VPS perto dos servidores das casas).
- [ ] Logs e alertas de falha.
- [ ] Rotina semanal de manutenção dos adapters.

---

## 6. Riscos

- **Termos de uso:** praticamente todas as casas proíbem acesso automatizado e apostas por arbitragem. O resultado mais comum é a **limitação da conta** (stake máximo irrisório).
- **Anulação de apostas:** cláusulas de "odd palpavelmente errada" e de aposta feita após o evento ocorrer permitem à casa cancelar justamente as apostas que o bot identificou.
- **Regulação no Brasil:** com a Lei 14.790/2023, as casas autorizadas (.bet.br) exigem conta verificada por CPF. Múltiplas contas não são uma saída.
- **Proteções anti-bot:** **não contornar** Cloudflare, CAPTCHA ou bloqueios. Priorizar fontes com acesso permitido (APIs oficiais, exchanges, agregadores).
- **Manutenção:** adapters próprios quebram sem aviso. Orçar tempo recorrente para isso.

---

## 7. Como vamos trabalhar com Claude Code

### Papéis
| Quem | Faz |
|---|---|
| Construtor | Pede as tarefas ao Claude Code, testa, descreve o que funcionou e o que não funcionou |
| Claude Code | Escreve o código, roda testes, explica o que fez |
| Desenvolvedor | Aprova o plano de cada fase, revisa os Pull Requests, decide arquitetura |

### Regras do fluxo
1. **Tudo no GitHub.** Cada tarefa vira uma branch e um Pull Request. Nada vai direto para a `main`.
2. **Planejar antes de codar.** Para toda tarefa nova, pedir primeiro um plano ao Claude Code (modo de planejamento) e só aprovar a execução depois.
3. **Tarefas pequenas.** Uma coisa por vez: "criar o coletor da API X", não "fazer o bot".
4. **Decisões ficam escritas.** Toda decisão do desenvolvedor vai para `docs/decisoes.md`, para o Claude Code seguir nas próximas sessões.
5. **Travou? Registrar e chamar.** Se o mesmo erro aparecer 2–3 vezes, parar, abrir uma issue no GitHub descrevendo e marcar o desenvolvedor.

### Estrutura de pastas sugerida
```
/
├── CLAUDE.md              # Instruções permanentes para o Claude Code
├── README.md
├── docs/
│   ├── projeto.md         # Este documento
│   ├── decisoes.md        # Registro de decisões (data, decisão, motivo)
│   └── diario.md          # O que foi feito em cada sessão
├── .claude/
│   └── commands/          # Comandos prontos (ver abaixo)
├── src/
│   ├── adapters/
│   ├── normalizador/
│   ├── comparador/
│   └── alertas/
└── tests/
```

### Rascunho do CLAUDE.md

```markdown
# Contexto
Bot que detecta casas de apostas com odds atrasadas. Documento completo em docs/projeto.md.
Quem está usando o Claude Code NÃO é programador. Explique em português simples o que fez e por quê.

# Regras
- Sempre proponha um plano antes de escrever código e espere aprovação.
- Nunca faça commit direto na main. Crie branch e Pull Request.
- Leia docs/decisoes.md antes de começar. Siga as decisões registradas.
- Não contorne CAPTCHA, Cloudflare ou qualquer proteção anti-bot. Se um site bloquear, pare e avise.
- Nunca coloque chaves de API ou senhas no código. Use o arquivo .env (que não vai para o GitHub).
- Toda função nova precisa de teste.
- Ao final de cada sessão, adicione um resumo em docs/diario.md.
- Se não tiver certeza sobre uma decisão de arquitetura, pergunte em vez de decidir.

# Comandos
- Rodar testes: (preencher)
- Rodar o bot localmente: (preencher)
```

### Comandos prontos sugeridos (`.claude/commands/`)
- `/nova-tarefa` — pede plano, cria branch, executa após aprovação.
- `/fim-de-sessao` — roda testes, atualiza o diário, abre o Pull Request.
- `/pedir-ajuda` — gera uma issue no GitHub com o erro, o que foi tentado e o contexto.
- `/status` — resume o que está pronto, o que falta e em que fase estamos.
