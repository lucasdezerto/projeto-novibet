"""Schema unico de odd.

Toda fonte de dados (API agregadora agora, adapters de site depois) converte
o que coletou para OddNormalizada. O resto do bot so conhece este formato.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class OddNormalizada:
    casa: str
    """Identificador da casa de apostas, ex: 'pinnacle', 'novibet_br'."""

    evento_id_normalizado: str
    """Id do jogo igual em todas as fontes, ex: 'sinner-vs-alcaraz-2026-09-24T09:00'."""

    mercado: str
    """Tipo de mercado, ex: 'h2h' (vencedor da partida)."""

    selecao: str
    """O que foi apostado, ex: o nome normalizado do jogador."""

    odd: float

    suspenso: bool = False
    """True quando a casa tirou o mercado do ar (comum ao vivo)."""

    timestamp_coleta: datetime = field(default_factory=agora_utc)
    """Momento em que o bot recebeu o dado."""

    timestamp_fonte: datetime | None = None
    """Momento que a propria fonte diz ter atualizado a odd, quando ela informa."""

    torneio_id: str = ""
    """Id do torneio no config, ex: 'atp-chengdu'."""

    evento_descricao: str = ""
    """Texto legivel do jogo, para aparecer no alerta."""

    ao_vivo: bool = False

    @property
    def chave(self) -> tuple[str, str, str, str]:
        """Identifica de forma unica um preco: casa + jogo + mercado + selecao."""
        return (self.casa, self.evento_id_normalizado, self.mercado, self.selecao)

    @property
    def chave_mercado(self) -> tuple[str, str, str]:
        """Identifica o mercado sem a casa, para comparar casas entre si."""
        return (self.evento_id_normalizado, self.mercado, self.selecao)

    def para_dicionario(self) -> dict:
        dados = asdict(self)
        for campo in ("timestamp_coleta", "timestamp_fonte"):
            valor = dados[campo]
            dados[campo] = valor.isoformat() if valor else None
        return dados


@dataclass(frozen=True)
class Alerta:
    tipo: str
    """'desvio' (odd fora do preco justo) ou 'atraso' (casa parada depois da referencia mexer)."""

    casa: str
    evento_id_normalizado: str
    evento_descricao: str
    torneio_id: str
    mercado: str
    selecao: str

    odd_casa: float
    odd_referencia: float
    casa_referencia: str

    desvio: float
    """Quanto a odd da casa esta acima do preco justo, em fracao (0.052 = 5,2%)."""

    segundos_parado: float
    """Ha quantos segundos a odd da casa nao muda."""

    detalhe: str = ""
    timestamp: datetime = field(default_factory=agora_utc)

    @property
    def chave_deduplicacao(self) -> str:
        return f"{self.tipo}|{self.casa}|{self.evento_id_normalizado}|{self.mercado}|{self.selecao}"

    def texto(self) -> str:
        rotulo = "ODD ATRASADA" if self.tipo == "atraso" else "ODD FORA DO PRECO"
        return (
            f"[{rotulo}] {self.casa}\n"
            f"{self.evento_descricao} ({self.torneio_id})\n"
            f"Mercado: {self.mercado} | Selecao: {self.selecao}\n"
            f"Odd da casa: {self.odd_casa:.2f} | Preco justo ({self.casa_referencia}): "
            f"{self.odd_referencia:.2f}\n"
            f"Desvio: {self.desvio * 100:+.1f}% | Parada ha {self.segundos_parado:.0f}s\n"
            f"{self.detalhe}"
        ).strip()
