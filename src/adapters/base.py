"""Contrato que toda fonte de odds precisa cumprir."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.modelos import OddNormalizada


class AdapterDeOdds(ABC):
    """Uma fonte de odds.

    Hoje so existe o adapter da API agregadora (Opcao A). Na Fase 3 entram os
    adapters de cada casa (Opcao B) implementando esta mesma interface, e o
    resto do bot nao precisa mudar.
    """

    nome: str = "adapter"

    @abstractmethod
    def coletar(self) -> list[OddNormalizada]:
        """Busca as odds agora e devolve tudo ja no schema unico."""

    def encerrar(self) -> None:
        """Libera recursos. Adapters simples nao precisam sobrescrever."""
