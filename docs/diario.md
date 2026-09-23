# Diário de sessões

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
