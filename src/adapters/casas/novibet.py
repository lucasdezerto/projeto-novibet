"""Parser da Novibet Brasil (novibet.bet.br).

Como o site funciona, observado no navegador em 2026-09-23:

- Nao usa WebSocket. A pagina do torneio busca um JSON por HTTP a cada ~5s:

      GET /spt/feed/marketviews/location/v2/{grupo}/{locationId}/
          ?lang=pt-BR&timeZ=...&oddsR=1&usrGrp=BR&timestamp={cursor}

- O corpo e uma lista de blocos, e as odds ficam aninhadas assim:

      [ { marketViewGroupId, betViews: [ { items: [ {
            additionalCaptions: { competitor1, competitor2 },
            startDate, isLive,
            markets: [ { betTypeSysname, betItems: [ { code, price, isAvailable } ] } ]
      } ] } ] } ]

- No mercado de vencedor, `code` "1" e o competitor1 e "2" e o competitor2.
- `isAvailable: false` e o mercado suspenso.

O bot nao monta essa URL: ele so le a resposta que a propria pagina pediu.
"""

from __future__ import annotations

import logging
from datetime import datetime

from src.adapters.casas.base import ParserDeCasa
from src.modelos import OddNormalizada
from src.normalizador.eventos import gerar_id_evento, interpretar_horario, normalizar_selecao

log = logging.getLogger(__name__)

URL_BASE = "https://www.novibet.bet.br"

# De que forma cada mercado da Novibet entra no schema unico.
# 'h2h' e o unico que hoje da para comparar com a API agregadora, porque a
# selecao vira o nome normalizado do jogador nos dois lados.
MERCADOS = {
    "TENNIS_SINGLES_MATCH_WINNER": "h2h",
    "TENNIS_DOUBLES_MATCH_WINNER": "h2h",
    "TENNIS_SINGLES_MATCH_GAMES_UNDER_OVER": "totals",
}


class ParserNovibet(ParserDeCasa):
    nome = "novibet_br"

    # Textos vistos de verdade na tela de verificacao da Cloudflare em
    # 2026-09-23, rodando Chromium automatizado contra o site.
    #
    # Tem versao em portugues E em ingles de proposito: a Cloudflare escolhe o
    # idioma pelo navegador, e o primeiro teste ao vivo falhou justamente
    # porque a tela veio em ingles e so havia padrao em portugues aqui.
    padroes_de_bloqueio = (
        # Portugues
        "executando verificação de segurança",
        "executando verificacao de seguranca",
        "proteção contra bots",
        "protecao contra bots",
        "um momento",
        "acesso negado",
        # Ingles
        "just a moment",
        "performing security verification",
        "against malicious bots",
        "checking your browser",
        "verifying you are human",
        "access denied",
    )

    def __init__(self, mercados: list[str] | None = None):
        # Por padrao so o vencedor da partida: e o unico comparavel entre casas.
        self.mercados_desejados = set(mercados or ["h2h"])

    # ------------------------------------------------------------------
    def paginas(self, torneios: list[dict]) -> list[tuple[str, str]]:
        """Monta a URL da pagina de cada torneio que tem id da Novibet no config."""
        paginas = []
        for torneio in torneios:
            novibet = torneio.get("novibet") or {}
            caminho = novibet.get("caminho")
            if not caminho:
                continue
            paginas.append((torneio["id"], f"{URL_BASE}{caminho}"))
        return paginas

    def interessa(self, url: str) -> bool:
        return "/spt/feed/marketviews/" in url

    # ------------------------------------------------------------------
    def converter(
        self, url: str, dados: object, torneio_id: str, agora: datetime
    ) -> list[OddNormalizada]:
        if not isinstance(dados, list):
            return []

        odds: list[OddNormalizada] = []
        for bloco in dados:
            if not isinstance(bloco, dict):
                continue
            for visao in bloco.get("betViews") or []:
                if not isinstance(visao, dict):
                    continue
                for evento in visao.get("items") or []:
                    odds.extend(self._converter_evento(evento, torneio_id, agora))
        return odds

    def _converter_evento(
        self, evento: object, torneio_id: str, agora: datetime
    ) -> list[OddNormalizada]:
        if not isinstance(evento, dict):
            return []

        legendas = evento.get("additionalCaptions") or {}
        jogador_1 = legendas.get("competitor1")
        jogador_2 = legendas.get("competitor2")
        inicio = evento.get("startDate")
        if not (jogador_1 and jogador_2 and inicio):
            return []

        try:
            evento_id = gerar_id_evento(jogador_1, jogador_2, inicio)
            interpretar_horario(inicio)
        except (ValueError, TypeError) as erro:
            log.warning("Evento da Novibet ignorado, horario invalido (%s): %s", inicio, erro)
            return []

        descricao = f"{jogador_1} x {jogador_2}"
        ao_vivo = bool(evento.get("isLive"))
        odds: list[OddNormalizada] = []

        # A Novibet as vezes manda o mesmo tipo de mercado duas vezes para o
        # mesmo jogo (visto em 2026-09-23 num jogo marcado "SO"). Ficamos com
        # a primeira ocorrencia para nao gravar dois precos conflitantes.
        ja_visto: set[str] = set()

        for mercado in evento.get("markets") or []:
            if not isinstance(mercado, dict):
                continue
            tipo = mercado.get("betTypeSysname")
            nosso_mercado = MERCADOS.get(tipo)
            if not nosso_mercado or nosso_mercado not in self.mercados_desejados:
                continue
            if nosso_mercado in ja_visto:
                log.debug(
                    "Mercado %s repetido no evento %s; usando so o primeiro.", tipo, evento_id
                )
                continue
            ja_visto.add(nosso_mercado)

            for item in mercado.get("betItems") or []:
                odd = self._converter_item(
                    item=item,
                    nosso_mercado=nosso_mercado,
                    jogador_1=jogador_1,
                    jogador_2=jogador_2,
                    evento_id=evento_id,
                    descricao=descricao,
                    torneio_id=torneio_id,
                    ao_vivo=ao_vivo,
                    agora=agora,
                )
                if odd:
                    odds.append(odd)
        return odds

    def _converter_item(
        self,
        item: object,
        nosso_mercado: str,
        jogador_1: str,
        jogador_2: str,
        evento_id: str,
        descricao: str,
        torneio_id: str,
        ao_vivo: bool,
        agora: datetime,
    ) -> OddNormalizada | None:
        if not isinstance(item, dict):
            return None

        try:
            odd = float(item.get("price"))
        except (TypeError, ValueError):
            return None
        if odd <= 1.0:
            return None

        selecao = self._nome_da_selecao(item, nosso_mercado, jogador_1, jogador_2)
        if not selecao:
            return None

        return OddNormalizada(
            casa=self.nome,
            evento_id_normalizado=evento_id,
            mercado=nosso_mercado,
            selecao=selecao,
            odd=odd,
            # A Novibet marca o mercado fora do ar com isAvailable=false.
            suspenso=item.get("isAvailable") is False,
            timestamp_coleta=agora,
            # A casa nao informa quando reprecificou; quem cronometra isso e o
            # motor, comparando um ciclo com o outro.
            timestamp_fonte=None,
            torneio_id=torneio_id,
            evento_descricao=descricao,
            ao_vivo=ao_vivo,
        )

    @staticmethod
    def _nome_da_selecao(
        item: dict, nosso_mercado: str, jogador_1: str, jogador_2: str
    ) -> str:
        """Traduz o codigo da Novibet para a mesma selecao que as outras fontes usam."""
        codigo = (item.get("code") or "").strip().upper()

        if nosso_mercado == "h2h":
            # O pulo do gato: "1" e "2" viram o nome normalizado do jogador,
            # que e exatamente o que a API agregadora produz. So assim da para
            # comparar a Novibet com a referencia de mercado.
            if codigo == "1":
                return normalizar_selecao(jogador_1)
            if codigo == "2":
                return normalizar_selecao(jogador_2)
            return ""

        if nosso_mercado == "totals":
            linha = (item.get("instanceCaption") or "").replace(",", ".").strip()
            if not linha:
                return ""
            if codigo == "O":
                return f"over-{linha}"
            if codigo == "U":
                return f"under-{linha}"
        return ""
