"""Alerta no Telegram.

Precisa de TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no .env. Sem eles o bot
segue rodando normalmente e os alertas saem so no console.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from src.modelos import Alerta

log = logging.getLogger(__name__)


class AlertaTelegram:
    nome = "telegram"

    def __init__(self, token: str, chat_id: str, tempo_limite: int = 10):
        self.token = token
        self.chat_id = chat_id
        self.tempo_limite = tempo_limite

    @property
    def _url(self) -> str:
        return f"https://api.telegram.org/bot{self.token}/sendMessage"

    def enviar(self, alerta: Alerta) -> bool:
        corpo = urllib.parse.urlencode(
            {
                "chat_id": self.chat_id,
                "text": alerta.texto(),
                "disable_web_page_preview": "true",
            }
        ).encode("utf-8")
        requisicao = urllib.request.Request(
            self._url,
            data=corpo,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(requisicao, timeout=self.tempo_limite) as resposta:
                resultado = json.loads(resposta.read().decode("utf-8"))
            if not resultado.get("ok"):
                log.error("Telegram recusou a mensagem: %s", resultado)
                return False
            return True
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as erro:
            log.error("Nao consegui enviar o alerta no Telegram: %s", erro)
            return False


def montar_alertadores(config_alertas: dict, token: str | None, chat_id: str | None) -> list:
    """Monta a lista de canais de alerta conforme o config e o .env."""
    canais = []
    if config_alertas.get("console", True):
        from src.alertas.console import AlertaConsole

        canais.append(AlertaConsole())
    if config_alertas.get("telegram", False):
        if token and chat_id:
            canais.append(AlertaTelegram(token, chat_id))
        else:
            log.warning(
                "Telegram ligado no config, mas TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID "
                "nao estao no .env. Alertas sairao so no console."
            )
    return canais
