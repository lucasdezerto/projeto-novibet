# Diário de sessões

## 2026-09-24 (Kevin) — Opção B pela extensão do Chrome

**Contexto:** a Novibet é exigência do cliente e o teste da Novibet GR foi
descartado. Caminho escolhido: extensão no Chrome normal de uma pessoa
([D-018](decisoes.md#d-018)).

### O que foi construído
- **`extensao/`** — extensão do Chrome. Copia as respostas de odds que a
  página da Novibet já recebeu (por `fetch` e `XMLHttpRequest`) e entrega ao
  bot em `127.0.0.1:8765`. A cada 20s também manda o título da aba, para o
  bot reconhecer tela de verificação. O ícone mostra `off` quando o bot não
  está rodando.
- **`src/adapters/extensao.py`** — o receptor no bot. Usa o mesmo parser da
  Novibet que já existia. Guarda a hora exata de cada mudança de odd entre um
  ciclo e outro, porque é ela que mede o atraso.
- **`--testar-extensao`** — espera a extensão mandar odds e mostra o que
  chegou.
- Config em `fontes.extensao`, **desligada por padrão** (não muda nada na
  outra máquina).
- **153 testes** (eram 123). Um deles roda o script da extensão de verdade no
  Node, num navegador de mentira, e confere que ele não faz requisição nem
  muda a resposta da página. É pulado se o Node não estiver instalado.

### Bugs encontrados pelos testes
- No Windows, o servidor padrão do Python deixa **dois programas escutarem na
  mesma porta**. Com duas cópias do bot abertas, a extensão entregaria as
  odds para uma delas ao acaso, sem aviso. Agora a porta é exclusiva e a
  segunda cópia recebe erro claro.
- O pytest confundia a função `testar_extensao` com um teste, por causa do
  nome. Virou `conferir_extensao`.

### Ainda não testado
**A extensão ainda não rodou no site de verdade.** Foi testada com o payload
real gravado e um teste ponta a ponta do comando, mas falta instalar no Chrome
e abrir a Novibet.

### Próximos passos
1. Instalar a extensão no Chrome e rodar `--testar-extensao` com a Novibet
   aberta.
2. **Motor com memória da referência:** hoje ele só compara odds do mesmo
   ciclo, então o bot roda no ritmo da The Odds API (120s). Para alertar em
   segundos, o motor precisa lembrar a última referência e rodar em ciclos
   curtos.
3. **Referência em tempo real:** com 500 créditos/mês, a The Odds API não
   acompanha jogo ao vivo. Decidir a fonte (plano pago da odds-api.io ou
   OddsPapi, que têm Pinnacle/Betfair).

## 2026-09-24 (Kevin) — Segunda máquina, padrão de trabalho a dois, novo rumo

### Segunda máquina
- O caminho do Python no CLAUDE.md era o da outra máquina. Nesta, o projeto
  roda num ambiente próprio (`.venv`, criado com o Python 3.12.5 local).
- **123 testes passando** aqui também.

### Padrão para duas pessoas ([D-017](decisoes.md#d-017))
- CLAUDE.md sem caminho de uma máquina só; ajustes locais no `CLAUDE.local.md`
  (fora do Git). A máquina original continua funcionando sem mudar nada.
- `git pull` antes de começar; testes + `git pull --rebase` + testes antes de
  enviar.
- Diário e decisões com junção automática, para não virar conflito.

### Mudança de rumo
O teste da Novibet GR (D-016) foi descartado. Objetivo continua: bot em tempo
real. Levantamento de caminhos:
- **Betfair não dá mais API para clientes no Brasil** desde 01/01/2025. A
  referência sharp tem que vir de um agregador.
- Agregadores com **streaming** (WebSocket/push) cobrindo casas `.bet.br`:
  OddsPapi (bet365 BR, Betano BR, KTO, Superbet...), OpticOdds (Betnacional,
  Galera.bet, Parimatch BR) e odds-api.io (Betano BR, Sportingbet BR...;
  WebSocket dobra o preço do plano).
- Nenhum deles cobre a Novibet BR (D-014).

### Próximos passos
1. Decidir se a Novibet é obrigatória ou se dá para trocar de casa.
2. Se der para trocar: medir o atraso do próprio agregador por casa antes de
   construir o adapter de streaming.

## 2026-09-24 — Caçada por acesso legítimo às odds da Novibet

**Contexto:** a sessão anterior terminou com as duas casas `.bet.br` bloqueando
navegador automatizado. O pedido foi: tentar todas as possibilidades, inclusive
outros agregadores. O objetivo mudou de escala — não é venda em massa, é **um
pedido específico de um apostador**.

### O que foi decidido não fazer

Contornar a detecção de bot continua fora, e vender o bot não muda isso —
distribuir ferramenta de evasão é pior que usá-la. Sem plugin de disfarce,
falsificação de impressão digital, proxy residencial ou resolução de CAPTCHA.

### Levantamento de agregadores ([D-014](decisoes.md#d-014))

Cinco provedores verificados procurando Novibet `.bet.br`:

| Provedor | Novibet BR | bet365 BR | Outras BR |
|---|---|---|---|
| The Odds API | ❌ | ❌ | ❌ nenhuma |
| OpticOdds | ❌ | ❌ | Betnacional, Galera.bet, Parimatch |
| odds-api.io | ❌ | ❌ | 6 casas com sufixo BR |
| OddsPapi | ❌ (360 casas, zero Novibet) | ✅ | 10+ casas BR |
| Oddsmarket | ❌ | — | não publica lista |

A ausência é significativa: todos separam variantes por país (Betano BR ≠
Betano PT). O odds-api.io lista "Novibet" e "Novibet GR", mas **não** "Novibet
BR", enquanto lista seis outras casas com sufixo BR.

**Descoberta útil:** a **bet365 BR está disponível** na OddsPapi — a casa que o
navegador não alcançava, um agregador entrega.

### Teste de acesso direto ([D-015](decisoes.md#d-015))

Testei se o feed público da Novibet responde a um cliente HTTP comum,
**identificado honestamente** (User-Agent dizendo o que o bot é, sem disfarce).
Não é contorno — é verificar se o dado é publicamente acessível.

**HTTP 403** nos dois endpoints, com o desafio da Cloudflare. O bloqueio não é
só contra navegador automatizado; é contra qualquer cliente que não passe pelo
desafio. O teste parou aí.

### A hipótese Novibet GR ([D-016](decisoes.md#d-016))

A Novibet roda a mesma plataforma em vários mercados. Se o atraso for do
**motor de precificação**, a versão grega mostraria o mesmo comportamento — e
`Novibet GR` está disponível na odds-api.io, sem bloqueio.

Confirmado sem precisar de conta (os endpoints `/sports` e `/bookmakers` são
abertos): `Novibet` e `Novibet GR` ativas, tênis suportado, referência via
`Betfair Exchange` ou `ON Sharp`. Não há Pinnacle.

### O que foi construído

- **`src/adapters/odds_api_io.py`** — coletor da odds-api.io, desligado por
  padrão no config.
- **`--medir-atraso`** — relatório que responde a pergunta do projeto: mediana,
  média, máximo de atraso por casa e em quantos % das vezes ela ficou parada
  mais de 60s.
- **123 testes** (eram 98), nenhum acessa a internet.

**Ganho técnico inesperado:** essa API devolve **`updatedAt` por casa e por
mercado** — a casa informa quando reprecificou. As outras fontes obrigavam o
bot a inferir isso comparando ciclos. Com o carimbo da própria fonte, a medida
de atraso fica muito mais precisa. Foi o que tornou o `--medir-atraso` possível.

### O erro que eu cometi e corrigi

Recomendei o tier gratuito da odds-api.io como caminho. Estava errado por dois
motivos:

1. **As novas chaves gratuitas estão pausadas por tempo indeterminado** —
   descoberto pelo usuário ao tentar criar a conta.
2. Mesmo aberto, o gratuito dá só **"2 casas recreativas"**, e *"casas sharp e
   exchanges exigem plano pago"*. A Novibet é recreativa, mas a **referência**
   (Betfair Exchange, ON Sharp) é justamente o que o gratuito não entrega — sem
   ela não há comparação, e o teste não existe.

### Onde o projeto parou

O código está pronto e esperando uma chave. O plano **Solo (R$359/mês, 2 casas)**
cobre o teste com **Novibet GR + Betfair Exchange**. Vale tirar as duas do mesmo
provedor: garante o mesmo universo de jogos e o mesmo id de evento.

**Antes de pagar, confirmar com o suporte:** (a) se o cliente escolhe quais são
as 2 casas do Solo; (b) se existe teste ou reembolso — a página não diz.

### Próximos passos

1. Mandar o e-mail ao suporte da odds-api.io com as duas perguntas.
2. Se confirmarem, assinar o Solo e rodar o bot durante os jogos de ATP/WTA.
3. Ler o resultado com `--medir-atraso`.
4. Se a Novibet GR **não** atrasar, a hipótese morre e a resposta honesta ao
   cliente é que não há caminho legítimo para monitorar a Novibet hoje.


## 2026-09-23 — Opção B: interceptador de navegador

**Objetivo:** implementar e testar a Opção B (ler o tráfego que o site da casa
recebe) como fonte de odds.

### O que foi construído

- **Interceptador genérico** (`src/adapters/navegador.py`) — abre a página num
  Chromium com Playwright e escuta respostas HTTP **e** quadros de WebSocket.
  As páginas ficam abertas entre os ciclos.
- **Contrato de parser por casa** (`src/adapters/casas/base.py`) — adicionar
  uma casa nova é escrever um parser, sem tocar em mais nada.
- **Parser da Novibet** (`src/adapters/casas/novibet.py`) — escrito sobre o
  payload real do site.
- **Parser da bet365** — esqueleto honesto, documentando o bloqueio.
- **Monitor de saúde** (`src/adapters/monitor.py`) — avisa quando uma fonte
  para de trazer dados.
- **`main.py` agora orquestra várias fontes** no mesmo ciclo, com isolamento de
  falhas: uma fonte com problema não derruba as outras.
- **98 testes** (eram 60), nenhum acessa a internet.

### O que foi descoberto observando o site

- **A Novibet não usa WebSocket.** É polling HTTP a cada ~5s em
  `/spt/feed/marketviews/location/v2/...`. O ganho de latência da Opção B sobre
  a Opção A é real, mas menor do que o plano supunha ([D-010](decisoes.md#d-010)).
- Os IDs dos 4 torneios do escopo na Novibet foram capturados e estão no
  `config.json`.

### O bloqueio — a notícia ruim

**As duas casas bloqueiam navegador automatizado** ([D-011](decisoes.md#d-011)):

- bet365: *"Não é possível exibir este conteúdo"* no lugar das odds.
- Novibet: Cloudflare com *"Executando verificação de segurança"*.

Não contornei, por regra do projeto. Em vez disso o bot **reconhece** a tela e
para com mensagem clara. Existe `--preparar-navegador`, que abre uma janela
visível para você passar pelas telas na mão, se quiser tentar.

### Bugs encontrados testando ao vivo

1. O interceptador **engolia em silêncio** o erro de leitura da página, então
   um bloqueio real passava como "nenhuma odd hoje". Agora tenta de novo, usa
   o título da aba e avisa quando não consegue ler.
2. A detecção de bloqueio **falhou na primeira rodada ao vivo**: a Cloudflare
   mostrou a tela em inglês e só havia padrão em português. Agora os padrões
   são bilíngues e o navegador abre com locale pt-BR. Tem teste travando os dois.

### Próximos passos sugeridos

1. Decidir o que fazer sobre o acesso às casas brasileiras: procurar acesso
   autorizado aos dados, ou aceitar que só a Opção A roda por enquanto.
2. Enquanto isso, rodar a Opção A e acumular histórico (Fase 2).
3. Se surgir acesso, o parser da Novibet já está pronto e testado.


## 2026-09-23 — Fase 1: coletor da Opção A (API agregadora)

**Objetivo da sessão:** começar a implementação pela Opção A e ter um bot que
avise quando uma casa está atrasada em relação a outra, nos 2 primeiros torneios
ATP e nos 2 primeiros WTA.

### O que foi construído

- **Schema único de odd** (`src/modelos.py`) — o formato que toda fonte de dados
  produz, exatamente como está na seção 4 do plano.
- **Coletor da Opção A** (`src/adapters/the_odds_api.py`) — busca as odds na The
  Odds API, descobre sozinho quais torneios do escopo estão no ar e controla o
  consumo de créditos.
- **Normalizador** (`src/normalizador/eventos.py`) — faz "J. Sinner" e
  "Jannik Sinner" virarem o mesmo jogo. Era o ponto apontado no plano como o mais
  trabalhoso.
- **Motor de comparação** (`src/comparador/`) — memória de quando cada odd mudou,
  cálculo do preço justo sem a margem da casa, e as duas regras de detecção.
- **Alertas** (`src/alertas/`) — console e Telegram.
- **Histórico** (`src/armazenamento/sqlite.py`) — grava tudo para o relatório da
  Fase 2.
- **58 testes**, todos sem acesso à internet.

### Duas descobertas que mudam o plano

1. **A API agregadora não cobre casas brasileiras.** Não existe região `br` na
   The Odds API, e nem Novibet nem bet365.bet.br estão na lista de casas. Nesta
   fase o bot detecta atraso entre casas europeias/britânicas, não entre as duas
   casas dos links originais. Detalhes em [decisoes.md](decisoes.md#d-002).
2. **Só 1 dos 4 torneios do escopo aparece na lista pública da API**
   (WTA Singapore). Por isso o coletor resolve os torneios em tempo de execução
   em vez de ter as chaves fixas no código. Detalhes em
   [decisoes.md](decisoes.md#d-003).

### Dois bugs encontrados pelos testes

- O motor acusava de atrasada uma casa que **tinha acompanhado** a referência no
  mesmo ciclo (comparação `<=` onde devia ser `<`).
- A comparação aproximada de nomes não casava sobrenome composto escrito com
  espaço ("Auger Aliassime") com o escrito com hífen ("Auger-Aliassime").

Os dois foram corrigidos e têm teste que trava a regressão.

### Ambiente

A máquina não tinha Python. O instalador oficial falha ao gravar o cache de
pacotes (provavelmente antivírus), e o `winget` está com o índice corrompido e
precisa de administrador para consertar. O Python 3.12.10 foi instalado a partir
do pacote NuGet oficial do CPython, em:

```
C:\Users\Admin\AppData\Local\Programs\Python\Python312
```

**Pendência:** essa pasta **não está no PATH**. Ou você adiciona ao PATH, ou usa
o caminho completo do `python.exe` nos comandos.

### Próximos passos sugeridos

1. Pegar a chave gratuita da The Odds API e rodar `--diagnostico` para ver quais
   dos 4 torneios estão realmente disponíveis hoje.
2. Deixar o bot rodando nas janelas de jogos e acumular histórico (Fase 2).
3. Com dados reais, calibrar `desvio_minimo` e `atraso_maximo_segundos`.
4. Decidir, com base no relatório, se vale construir adapter próprio (Opção B)
   para Novibet e bet365.bet.br.
