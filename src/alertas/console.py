"""Alerta no terminal. Sempre funciona, nao depende de configuracao."""

from __future__ import annotations

import logging

from src.modelos import Alerta

log = logging.getLogger(__name__)


class AlertaConsole:
    nome = "console"

    def enviar(self, alerta: Alerta) -> bool:
        separador = "-" * 60
        print(f"\n{separador}\n{alerta.texto()}\n{separador}", flush=True)
        return True
