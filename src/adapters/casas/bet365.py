"""Parser da bet365 Brasil (bet365.bet.br) - BLOQUEADO.

Estado em 2026-09-23: a bet365 carrega o menu lateral normalmente, mas no
lugar do painel de odds devolve **"Nao e possivel exibir este conteudo"**.
E a deteccao de automacao dela recusando servir o conteudo.

O projeto proibe contornar protecao anti-bot (ver CLAUDE.md e a secao 6 de
docs/projeto.md), entao este parser **nao tenta** nenhum disfarce. Ele existe
para dois fins:

1. Deixar a estrutura pronta: se um dia o acesso for liberado (por exemplo
   via uma API oficial de parceiro), basta preencher `converter`.
2. Detectar o bloqueio de forma explicita, para o bot parar com uma mensagem
   clara em vez de ficar rodando sem coletar nada.

Se voce precisa das odds da bet365, o caminho legitimo e falar com a casa
sobre acesso a dados, nao burlar a detecao.
"""

from __future__ import annotations

from datetime import datetime

from src.adapters.casas.base import ParserDeCasa
from src.modelos import OddNormalizada

URL_BASE = "https://www.bet365.bet.br"


class ParserBet365(ParserDeCasa):
    nome = "bet365_br"

    padroes_de_bloqueio = (
        "não é possível exibir este conteúdo",
        "nao e possivel exibir este conteudo",
        "not possible to display this content",
        "acesso negado",
    )

    def paginas(self, torneios: list[dict]) -> list[tuple[str, str]]:
        paginas = []
        for torneio in torneios:
            bet365 = torneio.get("bet365") or {}
            caminho = bet365.get("caminho")
            if not caminho:
                continue
            paginas.append((torneio["id"], f"{URL_BASE}{caminho}"))
        return paginas

    def interessa(self, url: str) -> bool:
        # Sem acesso ao conteudo, nao ha payload de odds para filtrar.
        return False

    def converter(
        self, url: str, dados: object, torneio_id: str, agora: datetime
    ) -> list[OddNormalizada]:
        return []
