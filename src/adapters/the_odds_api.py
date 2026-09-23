"""Opcao A: coletor usando a API agregadora The Odds API.

Uma chamada por torneio devolve, de uma vez, as odds de varias casas para
todos os jogos daquele torneio. O adapter converte isso para OddNormalizada.

Atencao ao consumo: cada chamada custa (numero de regioes x numero de
mercados) creditos. O plano gratuito tem 500 creditos por mes, entao o
adapter le os cabecalhos de quota da resposta e para sozinho quando o saldo
fica baixo.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from src.adapters.base import AdapterDeOdds
from src.modelos import OddNormalizada, agora_utc
from src.normalizador.eventos import gerar_id_evento, interpretar_horario, normalizar_selecao

URL_BASE = "https://api.the-odds-api.com/v4"
log = logging.getLogger(__name__)


class SemCreditos(Exception):
    """Saldo de chamadas da API abaixo do limite configurado."""


class ErroDaApi(Exception):
    """A API respondeu com erro."""


def _buscar_json(url: str, tempo_limite: int = 20) -> tuple[object, dict]:
    """Faz o GET e devolve (corpo_json, cabecalhos)."""
    requisicao = urllib.request.Request(url, headers={"User-Agent": "bot-odds-atrasadas/1.0"})
    try:
        with urllib.request.urlopen(requisicao, timeout=tempo_limite) as resposta:
            corpo = resposta.read().decode("utf-8")
            cabecalhos = {k.lower(): v for k, v in resposta.headers.items()}
    except urllib.error.HTTPError as erro:
        detalhe = erro.read().decode("utf-8", errors="replace")[:300]
        raise ErroDaApi(f"HTTP {erro.code} ao chamar a API: {detalhe}") from erro
    except urllib.error.URLError as erro:
        raise ErroDaApi(f"Falha de rede ao chamar a API: {erro.reason}") from erro
    return json.loads(corpo), cabecalhos


class AdapterTheOddsApi(AdapterDeOdds):
    nome = "the_odds_api"

    def __init__(
        self,
        chave_api: str,
        torneios: list[dict],
        regioes: list[str],
        mercados: list[str],
        formato_odds: str = "decimal",
        parar_com_creditos_restantes: int = 20,
        buscar_json: Callable[[str], tuple[object, dict]] = _buscar_json,
    ):
        self.chave_api = chave_api
        self.torneios = torneios
        self.regioes = regioes
        self.mercados = mercados
        self.formato_odds = formato_odds
        self.parar_com_creditos_restantes = parar_com_creditos_restantes
        self._buscar_json = buscar_json

        self.creditos_restantes: int | None = None
        self.creditos_usados: int | None = None
        self._mapa_torneios: dict[str, dict] | None = None
        self._torneios_sem_chave: list[str] = []

    # ------------------------------------------------------------------
    # Descoberta de quais torneios do config existem na API
    # ------------------------------------------------------------------
    def _listar_esportes(self) -> list[dict]:
        parametros = urllib.parse.urlencode({"apiKey": self.chave_api, "all": "false"})
        dados, cabecalhos = self._buscar_json(f"{URL_BASE}/sports/?{parametros}")
        self._registrar_quota(cabecalhos)
        return dados if isinstance(dados, list) else []

    def resolver_torneios(self, forcar: bool = False) -> dict[str, dict]:
        """Descobre a chave de esporte da API para cada torneio do config.

        Tenta primeiro as chaves exatas listadas no config; se nenhuma existir,
        procura pelo titulo usando os termos_nome. Torneios que nao aparecem
        ficam registrados em torneios_sem_chave.
        """
        if self._mapa_torneios is not None and not forcar:
            return self._mapa_torneios

        disponiveis = self._listar_esportes()
        por_chave = {e.get("key", ""): e for e in disponiveis}
        tenis = [
            e
            for e in disponiveis
            if e.get("group", "").lower() == "tennis" or e.get("key", "").startswith("tennis_")
        ]

        mapa: dict[str, dict] = {}
        sem_chave: list[str] = []
        for torneio in self.torneios:
            encontrado = None
            for chave in torneio.get("chaves_api", []):
                if chave in por_chave:
                    encontrado = por_chave[chave]
                    break
            if encontrado is None:
                termos = [t.lower() for t in torneio.get("termos_nome", [])]
                circuito = torneio.get("circuito", "").lower()
                for esporte in tenis:
                    titulo = f"{esporte.get('title', '')} {esporte.get('key', '')}".lower()
                    if circuito and circuito not in titulo:
                        continue
                    if any(termo in titulo for termo in termos):
                        encontrado = esporte
                        break
            if encontrado is None:
                sem_chave.append(torneio["nome"])
            else:
                mapa[torneio["id"]] = {"torneio": torneio, "esporte": encontrado}

        self._mapa_torneios = mapa
        self._torneios_sem_chave = sem_chave
        if sem_chave:
            log.warning(
                "Torneios sem cobertura na API agregadora agora: %s", ", ".join(sem_chave)
            )
        return mapa

    @property
    def torneios_sem_chave(self) -> list[str]:
        if self._mapa_torneios is None:
            self.resolver_torneios()
        return list(self._torneios_sem_chave)

    # ------------------------------------------------------------------
    # Coleta
    # ------------------------------------------------------------------
    def _registrar_quota(self, cabecalhos: dict) -> None:
        for cabecalho, atributo in (
            ("x-requests-remaining", "creditos_restantes"),
            ("x-requests-used", "creditos_usados"),
        ):
            valor = cabecalhos.get(cabecalho)
            if valor is None:
                continue
            try:
                setattr(self, atributo, int(float(valor)))
            except (TypeError, ValueError):
                pass

    def _conferir_quota(self) -> None:
        if (
            self.creditos_restantes is not None
            and self.creditos_restantes <= self.parar_com_creditos_restantes
        ):
            raise SemCreditos(
                f"Restam {self.creditos_restantes} creditos na API "
                f"(limite de seguranca: {self.parar_com_creditos_restantes})."
            )

    def _url_odds(self, chave_esporte: str) -> str:
        parametros = {
            "apiKey": self.chave_api,
            "regions": ",".join(self.regioes),
            "markets": ",".join(self.mercados),
            "oddsFormat": self.formato_odds,
            "dateFormat": "iso",
        }
        return f"{URL_BASE}/sports/{chave_esporte}/odds/?{urllib.parse.urlencode(parametros)}"

    def coletar(self) -> list[OddNormalizada]:
        self._conferir_quota()
        mapa = self.resolver_torneios()
        coletadas: list[OddNormalizada] = []

        for torneio_id, item in mapa.items():
            self._conferir_quota()
            chave_esporte = item["esporte"]["key"]
            try:
                eventos, cabecalhos = self._buscar_json(self._url_odds(chave_esporte))
            except ErroDaApi as erro:
                log.error("Nao consegui coletar %s (%s): %s", torneio_id, chave_esporte, erro)
                continue
            self._registrar_quota(cabecalhos)
            if not isinstance(eventos, list):
                continue
            for evento in eventos:
                coletadas.extend(self._converter_evento(evento, torneio_id))

        return coletadas

    def _converter_evento(self, evento: dict, torneio_id: str) -> list[OddNormalizada]:
        """Traduz um evento da API para o schema unico."""
        jogador_a = evento.get("home_team") or ""
        jogador_b = evento.get("away_team") or ""
        inicio = evento.get("commence_time")
        if not (jogador_a and jogador_b and inicio):
            return []

        try:
            evento_id = gerar_id_evento(jogador_a, jogador_b, inicio)
            momento_inicio = interpretar_horario(inicio)
        except (ValueError, TypeError) as erro:
            log.warning("Evento ignorado por horario invalido (%s): %s", inicio, erro)
            return []

        descricao = f"{jogador_a} x {jogador_b}"
        momento_coleta = agora_utc()
        ao_vivo = momento_inicio <= momento_coleta
        resultado: list[OddNormalizada] = []

        for casa_de_apostas in evento.get("bookmakers", []) or []:
            nome_casa = casa_de_apostas.get("key")
            if not nome_casa:
                continue
            timestamp_fonte = None
            atualizado_em = casa_de_apostas.get("last_update")
            if atualizado_em:
                try:
                    timestamp_fonte = interpretar_horario(atualizado_em)
                except (ValueError, TypeError):
                    timestamp_fonte = None

            for mercado in casa_de_apostas.get("markets", []) or []:
                chave_mercado = mercado.get("key")
                if not chave_mercado:
                    continue
                for possibilidade in mercado.get("outcomes", []) or []:
                    preco = possibilidade.get("price")
                    nome_selecao = possibilidade.get("name")
                    if preco is None or not nome_selecao:
                        continue
                    try:
                        odd = float(preco)
                    except (TypeError, ValueError):
                        continue
                    if odd <= 1.0:
                        continue
                    resultado.append(
                        OddNormalizada(
                            casa=nome_casa,
                            evento_id_normalizado=evento_id,
                            mercado=chave_mercado,
                            selecao=normalizar_selecao(nome_selecao),
                            odd=odd,
                            suspenso=False,
                            timestamp_coleta=momento_coleta,
                            timestamp_fonte=timestamp_fonte,
                            torneio_id=torneio_id,
                            evento_descricao=descricao,
                            ao_vivo=ao_vivo,
                        )
                    )
        return resultado
