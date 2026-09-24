"""Contrato de um parser de casa (Opcao B).

A Opcao B tem duas partes bem separadas, de proposito:

- **O interceptador** (`src/adapters/navegador.py`) abre a pagina da casa num
  navegador de verdade e escuta o que o proprio site recebe. Ele e generico:
  serve para qualquer casa.
- **O parser** (este contrato) sabe, para UMA casa, quais respostas interessam
  e como traduzir o JSON dela para o schema unico.

Separar assim significa que adicionar uma casa nova e escrever um parser novo,
sem tocar no interceptador nem no resto do bot.

Regra do projeto: o interceptador so le o que a pagina ja recebe sozinha. Ele
nao inventa requisicoes, nao contorna CAPTCHA, Cloudflare nem qualquer
protecao anti-bot. Se a casa bloquear, o parser avisa por `esta_bloqueado` e o
bot para.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from src.modelos import OddNormalizada


class CasaBloqueada(Exception):
    """A casa esta recusando servir o conteudo para o navegador do bot.

    Isto nao e para ser contornado. E um sinal de parada.
    """


class ParserDeCasa(ABC):
    """Traduz o trafego de uma casa para o schema unico."""

    nome: str = "casa"
    """Identificador da casa no resto do bot, ex: 'novibet_br'."""

    padroes_de_bloqueio: tuple[str, ...] = ()
    """Trechos de texto que, se aparecerem na pagina, indicam bloqueio."""

    @abstractmethod
    def paginas(self, torneios: list[dict]) -> list[tuple[str, str]]:
        """Devolve os pares (torneio_id, url) que o navegador deve manter abertos."""

    @abstractmethod
    def interessa(self, url: str) -> bool:
        """Diz se vale a pena olhar o corpo desta resposta.

        Uma pagina de casa de apostas faz centenas de requisicoes (imagens,
        scripts, rastreadores). Este filtro evita desperdicar trabalho com
        tudo que nao for odds.
        """

    @abstractmethod
    def converter(
        self, url: str, dados: object, torneio_id: str, agora: datetime
    ) -> list[OddNormalizada]:
        """Traduz um payload interceptado para o schema unico.

        Recebe o JSON ja decodificado. Deve devolver lista vazia (nunca
        levantar excecao) quando o payload nao for do tipo esperado: a casa
        muda o formato sem avisar e um ciclo perdido e melhor que o bot cair.
        """

    def esta_bloqueado(self, texto_da_pagina: str) -> bool:
        """Procura na pagina os sinais de bloqueio declarados pela casa."""
        texto = (texto_da_pagina or "").lower()
        return any(padrao.lower() in texto for padrao in self.padroes_de_bloqueio)
