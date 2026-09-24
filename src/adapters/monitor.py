"""Monitor de saude das fontes.

Item previsto na Fase 3 do plano: "alerta se um adapter parar de receber
dados". Com adapter proprio isso importa muito, porque a falha silenciosa e
o modo de quebrar mais comum - o site muda o formato, o parser para de
reconhecer o payload, e o bot segue rodando feliz sem alertar nada.

Pior ainda: uma fonte morta faz o motor achar que a casa esta "parada" e
disparar alerta de atraso que e so o bot quebrado. Por isso o monitor existe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.modelos import agora_utc


@dataclass
class SaudeDaFonte:
    nome: str
    ultima_coleta_com_dados: datetime | None
    odds_na_ultima_coleta: int
    ciclos_vazios_seguidos: int

    def segundos_sem_dados(self, agora: datetime) -> float | None:
        if self.ultima_coleta_com_dados is None:
            return None
        return (agora - self.ultima_coleta_com_dados).total_seconds()


class MonitorDeSaude:
    def __init__(self, silencio_maximo_segundos: float = 300.0):
        self.silencio_maximo_segundos = silencio_maximo_segundos
        self._fontes: dict[str, SaudeDaFonte] = {}
        self._ja_avisado: set[str] = set()

    def registrar(self, nome: str, quantidade_de_odds: int, agora: datetime | None = None) -> None:
        agora = agora or agora_utc()
        fonte = self._fontes.get(nome)
        if fonte is None:
            fonte = SaudeDaFonte(nome, None, 0, 0)
            self._fontes[nome] = fonte

        fonte.odds_na_ultima_coleta = quantidade_de_odds
        if quantidade_de_odds > 0:
            fonte.ultima_coleta_com_dados = agora
            fonte.ciclos_vazios_seguidos = 0
            self._ja_avisado.discard(nome)
        else:
            fonte.ciclos_vazios_seguidos += 1

    def fontes_em_silencio(self, agora: datetime | None = None) -> list[tuple[str, str]]:
        """Fontes que passaram do limite de silencio, com o motivo.

        Cada fonte so aparece uma vez por episodio: enquanto continuar muda,
        nao repete o aviso a cada ciclo.
        """
        agora = agora or agora_utc()
        avisos: list[tuple[str, str]] = []

        for nome, fonte in self._fontes.items():
            if nome in self._ja_avisado:
                continue

            if fonte.ultima_coleta_com_dados is None:
                if fonte.ciclos_vazios_seguidos >= 3:
                    avisos.append(
                        (nome, f"nunca trouxe odds em {fonte.ciclos_vazios_seguidos} ciclos")
                    )
                    self._ja_avisado.add(nome)
                continue

            silencio = fonte.segundos_sem_dados(agora) or 0.0
            if silencio > self.silencio_maximo_segundos:
                avisos.append((nome, f"sem odds ha {silencio:.0f}s"))
                self._ja_avisado.add(nome)

        return avisos

    def resumo(self, agora: datetime | None = None) -> list[str]:
        agora = agora or agora_utc()
        linhas = []
        for nome, fonte in sorted(self._fontes.items()):
            silencio = fonte.segundos_sem_dados(agora)
            quando = "nunca" if silencio is None else f"ha {silencio:.0f}s"
            linhas.append(f"{nome}: {fonte.odds_na_ultima_coleta} odds no ultimo ciclo, dados {quando}")
        return linhas
