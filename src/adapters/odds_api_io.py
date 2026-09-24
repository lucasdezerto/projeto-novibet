"""Coletor da odds-api.io.

Entrou no projeto por um motivo especifico: e o unico provedor encontrado que
cobre alguma Novibet (`Novibet` e `Novibet GR`). A Novibet brasileira nao e
coberta por ninguem (ver docs/decisoes.md D-014), entao a ideia e testar se o
atraso de odds e caracteristica da **plataforma** Novibet - caso em que a
versao grega serviria de prova, e o dado esta a venda.

Duas vantagens sobre as outras fontes:

1. **`updatedAt` por casa e por mercado.** A casa informa quando reprecificou.
   Nas outras fontes o bot tinha que inferir isso comparando ciclos; aqui o
   carimbo e da propria fonte, o que deixa a deteccao de atraso bem mais
   precisa.
2. **Referencia de consenso.** Alem da Betfair Exchange, a API expoe uma linha
   sharp agregada chamada `ON Sharp`, que costuma ser referencia melhor que
   uma casa sozinha.

Endpoints usados (base https://api.odds-api.io/v3):
    GET /events?sport=tennis&apiKey=...      lista os jogos
    GET /odds/multi?eventIds=...&bookmakers=...&markets=...&apiKey=...
"""

from __future__ import annotations

import gzip
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from src.adapters.base import AdapterDeOdds
from src.modelos import OddNormalizada, agora_utc
from src.normalizador.eventos import gerar_id_evento, interpretar_horario, normalizar_selecao

URL_BASE = "https://api.odds-api.io/v3"
EVENTOS_POR_CHAMADA = 10  # limite do endpoint /odds/multi
log = logging.getLogger(__name__)

# Como os mercados da odds-api.io entram no schema unico.
MERCADOS = {"ML": "h2h", "Moneyline": "h2h"}

# Nos resultados, cada linha de odd usa estas chaves para dizer de quem e o preco.
LADOS = ("home", "away")


class ErroOddsApiIo(Exception):
    """A API respondeu com erro."""


def _buscar_json(url: str, tempo_limite: int = 25) -> object:
    requisicao = urllib.request.Request(
        url,
        headers={
            "User-Agent": "projeto-novibet-bot/1.0",
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        },
    )
    try:
        with urllib.request.urlopen(requisicao, timeout=tempo_limite) as resposta:
            bruto = resposta.read()
            comprimido = (
                resposta.headers.get("Content-Encoding") == "gzip" or bruto[:2] == b"\x1f\x8b"
            )
    except urllib.error.HTTPError as erro:
        detalhe = erro.read().decode("utf-8", errors="replace")[:300]
        raise ErroOddsApiIo(f"HTTP {erro.code}: {detalhe}") from erro
    except urllib.error.URLError as erro:
        raise ErroOddsApiIo(f"Falha de rede: {erro.reason}") from erro

    # A API responde comprimida mesmo sem pedirmos; descobri isso na marra.
    if comprimido:
        bruto = gzip.decompress(bruto)
    return json.loads(bruto.decode("utf-8"))


def _lista(dados: object) -> list:
    """A API as vezes devolve lista crua, as vezes embrulhada em {'data': [...]}."""
    if isinstance(dados, list):
        return dados
    if isinstance(dados, dict):
        for chave in ("data", "events", "results"):
            if isinstance(dados.get(chave), list):
                return dados[chave]
    return []


class AdapterOddsApiIo(AdapterDeOdds):
    nome = "odds_api_io"

    def __init__(
        self,
        chave_api: str,
        casas: list[str],
        torneios: list[dict] | None = None,
        esporte: str = "tennis",
        mercados: list[str] | None = None,
        filtrar_torneios: bool = True,
        limite_requisicoes_por_ciclo: int = 6,
        buscar_json: Callable[[str], object] = _buscar_json,
    ):
        self.chave_api = chave_api
        self.casas = list(casas)
        self.torneios = list(torneios or [])
        self.esporte = esporte
        self.mercados = list(mercados or ["ML"])
        # Para medir se a Novibet GR atrasa, quanto mais jogo melhor. Desligar
        # o filtro pega o circuito inteiro em vez de so os 4 torneios do escopo.
        self.filtrar_torneios = filtrar_torneios
        self.limite_requisicoes_por_ciclo = limite_requisicoes_por_ciclo
        self._buscar_json = buscar_json

        self.requisicoes_feitas = 0
        self.eventos_no_ultimo_ciclo = 0

    # ------------------------------------------------------------------
    def _url(self, caminho: str, parametros: dict) -> str:
        parametros = {**parametros, "apiKey": self.chave_api}
        return f"{URL_BASE}{caminho}?{urllib.parse.urlencode(parametros)}"

    def _chamar(self, caminho: str, parametros: dict) -> object:
        self.requisicoes_feitas += 1
        return self._buscar_json(self._url(caminho, parametros))

    # ------------------------------------------------------------------
    def listar_eventos(self) -> list[dict]:
        eventos = [e for e in _lista(self._chamar("/events", {"sport": self.esporte})) if isinstance(e, dict)]
        if not self.filtrar_torneios:
            return eventos
        return [e for e in eventos if self._torneio_do_evento(e)]

    def _torneio_do_evento(self, evento: dict) -> str | None:
        """Descobre a qual torneio do config o evento pertence, pelo nome da liga."""
        liga = evento.get("league") or {}
        titulo = f"{liga.get('name', '')} {liga.get('slug', '')}".lower()
        if not titulo.strip():
            return None
        for torneio in self.torneios:
            circuito = (torneio.get("circuito") or "").lower()
            if circuito and circuito not in titulo:
                continue
            if any((t or "").lower() in titulo for t in torneio.get("termos_nome", [])):
                return torneio["id"]
        return None

    # ------------------------------------------------------------------
    def coletar(self) -> list[OddNormalizada]:
        self.requisicoes_feitas = 0
        eventos = self.listar_eventos()
        self.eventos_no_ultimo_ciclo = len(eventos)
        if not eventos:
            log.info("Nenhum evento de %s encontrado na odds-api.io.", self.esporte)
            return []

        por_id = {str(e.get("id")): e for e in eventos if e.get("id") is not None}
        agora = agora_utc()
        odds: list[OddNormalizada] = []

        ids = list(por_id)
        for inicio in range(0, len(ids), EVENTOS_POR_CHAMADA):
            if self.requisicoes_feitas >= self.limite_requisicoes_por_ciclo:
                log.warning(
                    "Parei em %d requisicoes neste ciclo (limite do plano). "
                    "%d de %d jogos ficaram de fora.",
                    self.requisicoes_feitas, len(ids) - inicio, len(ids),
                )
                break

            lote = ids[inicio : inicio + EVENTOS_POR_CHAMADA]
            parametros = {
                "eventIds": ",".join(lote),
                "bookmakers": ",".join(self.casas),
                "markets": ",".join(self.mercados),
            }
            try:
                resposta = self._chamar("/odds/multi", parametros)
            except ErroOddsApiIo as erro:
                log.error("Falha ao buscar odds do lote %s: %s", lote, erro)
                continue

            for item in _lista(resposta):
                if not isinstance(item, dict):
                    continue
                evento = por_id.get(str(item.get("id"))) or item
                odds.extend(self._converter_evento(item, evento, agora))

        return odds

    # ------------------------------------------------------------------
    def _converter_evento(self, item: dict, evento: dict, agora) -> list[OddNormalizada]:
        jogador_casa = item.get("home") or evento.get("home")
        jogador_fora = item.get("away") or evento.get("away")
        inicio = item.get("date") or evento.get("date")
        if not (jogador_casa and jogador_fora and inicio):
            return []

        try:
            evento_id = gerar_id_evento(jogador_casa, jogador_fora, inicio)
            momento_inicio = interpretar_horario(inicio)
        except (ValueError, TypeError) as erro:
            log.warning("Evento ignorado, horario invalido (%s): %s", inicio, erro)
            return []

        torneio_id = self._torneio_do_evento(evento) or ""
        if not torneio_id:
            liga = (evento.get("league") or {}).get("slug") or ""
            torneio_id = f"outro:{liga}" if liga else "outro"

        descricao = f"{jogador_casa} x {jogador_fora}"
        ao_vivo = momento_inicio <= agora
        nomes = {"home": jogador_casa, "away": jogador_fora}

        casas = item.get("bookmakers")
        if not isinstance(casas, dict):
            return []

        resultado: list[OddNormalizada] = []
        for nome_casa, mercados in casas.items():
            if not isinstance(mercados, list):
                continue
            ja_visto: set[str] = set()
            for mercado in mercados:
                if not isinstance(mercado, dict):
                    continue
                nosso_mercado = MERCADOS.get(mercado.get("name"))
                if not nosso_mercado or nosso_mercado in ja_visto:
                    continue
                ja_visto.add(nosso_mercado)

                # O carimbo que torna esta fonte melhor que as outras: a casa
                # diz quando reprecificou, em vez de o bot ter que adivinhar.
                timestamp_fonte = None
                if mercado.get("updatedAt"):
                    try:
                        timestamp_fonte = interpretar_horario(mercado["updatedAt"])
                    except (ValueError, TypeError):
                        timestamp_fonte = None

                for linha in mercado.get("odds") or []:
                    if not isinstance(linha, dict):
                        continue
                    for lado in LADOS:
                        odd = self._preco(linha.get(lado))
                        if odd is None:
                            continue
                        resultado.append(
                            OddNormalizada(
                                casa=self._apelido(nome_casa),
                                evento_id_normalizado=evento_id,
                                mercado=nosso_mercado,
                                selecao=normalizar_selecao(nomes[lado]),
                                odd=odd,
                                suspenso=False,
                                timestamp_coleta=agora,
                                timestamp_fonte=timestamp_fonte,
                                torneio_id=torneio_id,
                                evento_descricao=descricao,
                                ao_vivo=ao_vivo,
                            )
                        )
        return resultado

    @staticmethod
    def _preco(valor: object) -> float | None:
        """Os precos vem como texto ('1.95'), nao como numero."""
        if valor is None:
            return None
        try:
            odd = float(valor)
        except (TypeError, ValueError):
            return None
        return odd if odd > 1.0 else None

    @staticmethod
    def _apelido(nome_casa: str) -> str:
        """'Novibet GR' -> 'novibet_gr', para casar com o resto do bot."""
        return "_".join(str(nome_casa).lower().replace(".", "_").split())
