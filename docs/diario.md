# Diário de sessões

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
