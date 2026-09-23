"""Memoria de curto prazo do bot.

Guarda, para cada preco (casa + jogo + mercado + selecao), qual foi a ultima
odd vista e quando ela mudou pela ultima vez. Sem isso nao da para responder
a pergunta central do projeto: "ha quanto tempo esta casa esta parada?".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.modelos import OddNormalizada


@dataclass
class RegistroDePreco:
    odd: float
    odd_anterior: float | None
    visto_em: datetime
    """Ultima vez que o bot viu este preco (mudando ou nao)."""

    mudou_em: datetime
    """Ultima vez que o valor da odd efetivamente mudou."""

    suspenso: bool = False

    def segundos_parado(self, referencia: datetime) -> float:
        return max(0.0, (referencia - self.mudou_em).total_seconds())

    @property
    def variacao(self) -> float:
        """Tamanho da ultima mudanca, em fracao (0.03 = 3%)."""
        if self.odd_anterior is None or self.odd_anterior <= 0:
            return 0.0
        return (self.odd - self.odd_anterior) / self.odd_anterior


class EstadoDeMercado:
    """Guarda o ultimo estado conhecido de cada preco."""

    def __init__(self) -> None:
        self._registros: dict[tuple[str, str, str, str], RegistroDePreco] = {}

    def atualizar(self, odd: OddNormalizada) -> RegistroDePreco:
        """Registra a odd recebida e devolve o registro atualizado."""
        anterior = self._registros.get(odd.chave)
        if anterior is None:
            registro = RegistroDePreco(
                odd=odd.odd,
                odd_anterior=None,
                visto_em=odd.timestamp_coleta,
                mudou_em=odd.timestamp_fonte or odd.timestamp_coleta,
                suspenso=odd.suspenso,
            )
        elif anterior.odd != odd.odd or anterior.suspenso != odd.suspenso:
            registro = RegistroDePreco(
                odd=odd.odd,
                odd_anterior=anterior.odd,
                visto_em=odd.timestamp_coleta,
                mudou_em=odd.timestamp_coleta,
                suspenso=odd.suspenso,
            )
        else:
            anterior.visto_em = odd.timestamp_coleta
            registro = anterior

        self._registros[odd.chave] = registro
        return registro

    def obter(self, chave: tuple[str, str, str, str]) -> RegistroDePreco | None:
        return self._registros.get(chave)

    def limpar_antigos(self, agora: datetime, segundos: int = 6 * 3600) -> int:
        """Descarta precos que nao aparecem ha muito tempo (jogo ja acabou)."""
        vencidos = [
            chave
            for chave, registro in self._registros.items()
            if (agora - registro.visto_em).total_seconds() > segundos
        ]
        for chave in vencidos:
            del self._registros[chave]
        return len(vencidos)

    def __len__(self) -> int:
        return len(self._registros)


class ControleDeRepeticao:
    """Evita repetir o mesmo alerta a cada ciclo."""

    def __init__(self, intervalo_segundos: int = 300):
        self.intervalo_segundos = intervalo_segundos
        self._ultimo_envio: dict[str, datetime] = {}

    def pode_enviar(self, chave: str, agora: datetime) -> bool:
        anterior = self._ultimo_envio.get(chave)
        if anterior is None:
            return True
        return (agora - anterior).total_seconds() >= self.intervalo_segundos

    def registrar(self, chave: str, agora: datetime) -> None:
        self._ultimo_envio[chave] = agora
        self._limpar_antigos(agora)

    def _limpar_antigos(self, agora: datetime) -> None:
        """Descarta alertas velhos demais para ainda serem repeticao.

        Sem isto o dicionario so cresceria, jogo apos jogo.
        """
        limite = max(self.intervalo_segundos * 10, 3600)
        vencidas = [
            chave
            for chave, quando in self._ultimo_envio.items()
            if (agora - quando).total_seconds() > limite
        ]
        for chave in vencidas:
            del self._ultimo_envio[chave]

    def __len__(self) -> int:
        return len(self._ultimo_envio)
