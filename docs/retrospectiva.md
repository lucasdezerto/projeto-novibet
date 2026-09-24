# Retrospectiva — o que deu certo e o que deu errado

**Período:** 23/09/2026 (Fase 1 + Opção B)
**Estado do código:** 98 testes passando, nada acessa a internet nos testes.

Este documento é o balanço honesto do projeto até aqui. A conclusão curta:
**o bot está construído e funcionando; o que falta não é código, é acesso aos
dados das casas brasileiras.**

---

## Resumo em uma tabela

| Item | Estado |
|---|---|
| Motor de comparação (detecção de atraso) | ✅ Pronto e testado |
| Normalizador de eventos entre casas | ✅ Pronto, provado entre as duas fontes |
| Alertas (console + Telegram) | ✅ Pronto |
| Histórico para a Fase 2 | ✅ Pronto |
| Opção A — API agregadora | ⚠️ Funciona, **mas não cobre casa brasileira** |
| Opção B — interceptador de navegador | ⚠️ Código pronto, **acesso bloqueado pelas casas** |
| Objetivo final (alertar atraso da Novibet) | ❌ **Bloqueado por acesso, não por código** |

---

## O que deu certo

### 1. A arquitetura aguentou o teste real

O melhor sinal do projeto: quando a Opção B entrou, **o motor de comparação, os
alertas e o histórico não mudaram uma linha**. As duas fontes produzem o mesmo
`OddNormalizada` e o motor não sabe de onde cada preço veio.

Isso não foi sorte — foi a decisão de definir o schema único antes de escrever
a primeira fonte. Vale manter essa disciplina.

### 2. O normalizador de eventos funcionou

O plano apontava isso como "a parte mais trabalhosa", e era mesmo. Mas está
resolvido e **provado**: existe um teste que pega um jogo real da Novibet
("James Duckworth" x "Lorenzo Sonego") e confirma que ele gera exatamente o
mesmo identificador que a API agregadora geraria.

Sem isso, nada no resto do bot funcionaria. É a peça que faz a comparação entre
casas ser possível.

### 3. O tráfego da Novibet foi mapeado por completo

Observando o site no navegador, descobri o endpoint exato das odds, o formato
do JSON e os IDs dos 4 torneios do escopo. Capturei um payload real e escrevi o
parser em cima dele, com testes.

**Quando houver acesso, essa parte já está feita.**

### 4. Os testes pegaram bugs de verdade

Quatro bugs reais foram encontrados por testes, não em produção:

1. O motor acusava de atrasada uma casa que **tinha acompanhado** a referência
   no mesmo ciclo (comparação `<=` onde devia ser `<`). Esse geraria alerta
   falso o tempo todo.
2. A comparação de nomes não casava "Auger Aliassime" com "Auger-Aliassime".
3. O interceptador **engolia em silêncio** o erro de leitura da página — um
   bloqueio real da casa apareceria como "nenhuma odd hoje".
4. A detecção de bloqueio só tinha texto em português, e a Cloudflare respondeu
   em inglês. Passou batido na primeira rodada ao vivo.

Os dois últimos só apareceram **testando ao vivo**. Teste de mesa não pegaria.

### 5. Decisões de simplificação que se pagaram

- **SQLite em vez de Postgres** e **sem Redis**: nada para instalar, nada para
  manter. Para o volume atual sobra.
- **Código síncrono em vez de asyncio**: a Opção A é uma consulta a cada 2
  minutos; concorrência ali não traz nada e atrapalha a leitura.
- **Só biblioteca padrão do Python**: a única dependência é o pytest (e o
  Playwright, opcional).

---

## O que deu errado

### 1. A API agregadora não cobre nenhuma casa brasileira ❌

**O maior problema do projeto.** A The Odds API tem as regiões `us`, `uk`, `eu`,
`au`, `ca`, `fr`, `se` e `fi`. **Não existe região `br`.** Nem Novibet, nem
bet365.bet.br, nem nenhuma `.bet.br`.

A Fase 0 do plano previa exatamente essa verificação ("Verificar quais aparecem
em alguma API agregadora"). A checagem foi feita — só que depois de escolher a
Opção A, não antes.

**Lição:** a Fase 0 existia por um motivo. Fazer a verificação antes teria
mudado a ordem do trabalho.

### 2. Só 1 dos 4 torneios do escopo está na lista pública da API ❌

Dos torneios pedidos, apenas **WTA Singapore** tem chave publicada. Chengdu,
Hangzhou e Seoul não aparecem.

Contornado: o coletor resolve os torneios em tempo de execução consultando a
API, em vez de ter as chaves fixas no código. Rode `--diagnostico` para ver o
que existe hoje de verdade.

### 3. As duas casas bloqueiam navegador automatizado ❌

Testado ao vivo em 23/09/2026:

- **bet365.bet.br** — o menu lateral carrega, mas no lugar do painel de odds
  vem *"Não é possível exibir este conteúdo"*.
- **novibet.bet.br** — a Cloudflare interrompe com *"Executando verificação de
  segurança / proteção contra bots maliciosos"*. O site funciona normalmente
  num navegador comum; o bloqueio é específico para automação.

**Não foi contornado, de propósito.** Sem plugin de disfarce, sem falsificar
impressão digital, sem resolver CAPTCHA. É regra do projeto e é o que evita ter
a conta limitada — que é o risco nº 1 da seção 6 do plano.

O que o bot faz é **reconhecer** a tela e parar com mensagem clara, em vez de
rodar horas sem coletar nada.

### 4. A premissa de latência da Opção B estava otimista ⚠️

O plano dizia que a Opção B daria latência de **milissegundos**, via WebSocket.

Na prática, **a Novibet não usa WebSocket.** Ela faz polling HTTP a cada ~5
segundos. Ou seja: o piso de latência da Novibet é o ciclo dela, não o nosso.

A Opção B continua melhor que a Opção A (5s contra dezenas de segundos), mas a
vantagem é bem menor do que a tabela do plano sugeria. Isso muda o cálculo de
"vale a pena o esforço de um adapter próprio?".

### 5. O ambiente deu muito mais trabalho que o esperado ⚠️

A máquina não tinha Python, e instalar foi uma novela:

- `winget` está com o índice corrompido e consertar exige administrador.
- O instalador oficial do python.org falhou ao gravar o cache de pacotes
  (provavelmente antivírus), erro `0x80070003`.
- Funcionou pelo **pacote NuGet oficial do CPython**, extraído à mão.

**Pendência aberta:** o Python ficou em
`C:\Users\Admin\AppData\Local\Programs\Python\Python312` e **não está no
PATH**. Ou você adiciona, ou usa o caminho completo nos comandos.

### 6. O plano gratuito da API dura pouco ⚠️

500 créditos por mês. Com 4 torneios × 2 regiões, cada ciclo custa 8 créditos.
No intervalo padrão de 120s, **o mês inteiro acaba em ~2h30 de bot ligado**.

Mitigado com duas travas no `config.json` (`parar_com_creditos_restantes` e
`limite_creditos_por_execucao`), mas na prática significa: ligue o bot só nas
janelas de jogos, não 24/7.

---

## O que aprendi sobre o processo

**Verificar acesso antes de construir.** Os dois maiores bloqueios do projeto
(sem região `br`, casas bloqueando bot) eram descobríveis em uma hora de
verificação. A Fase 0 do plano previa isso.

**Testar ao vivo cedo.** Dois dos quatro bugs só apareceram rodando contra o
site real. Payload gravado é ótimo para regressão, mas não substitui a primeira
execução de verdade.

**Separar "não consegui" de "está tudo bem".** O bug mais perigoso foi o
interceptador engolindo o erro em silêncio: o bot pareceria saudável com a
fonte morta. Pior ainda, uma fonte morta faz o motor achar que a casa está
"parada" e disparar **alerta de atraso que é só o bot quebrado**. Foi por isso
que o monitor de saúde entrou.

---

## A decisão que está na mesa

O código está pronto. O que falta é acesso. As saídas reais:

1. **Procurar acesso autorizado aos dados** das casas brasileiras (API de
   parceiro, feed licenciado). É o caminho limpo, e o parser da Novibet já
   está escrito e testado esperando por isso.
2. **Rodar só a Opção A** e aceitar que ela compara casas europeias entre si.
   Serve para validar o motor e calibrar os limiares com dados reais (Fase 2),
   mas **não alerta sobre Novibet nem bet365**.
3. **Reavaliar o escopo** — talvez as casas que valem a pena monitorar sejam
   outras, cobertas pela API agregadora.

Minha recomendação: seguir com (2) em paralelo a (1). A Fase 2 gera o dado que
diz se a oportunidade existe de verdade, e isso não depende de destravar o
acesso às casas brasileiras.

---

## Referências

- Plano original: [projeto.md](projeto.md)
- Todas as decisões com data e motivo: [decisoes.md](decisoes.md)
- Histórico das sessões: [diario.md](diario.md)
