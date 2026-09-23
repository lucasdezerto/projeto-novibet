"""Leitura do config.json e do .env."""

from __future__ import annotations

import json
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CAMINHO_CONFIG_PADRAO = RAIZ / "config" / "config.json"
CAMINHO_ENV = RAIZ / ".env"


def carregar_env(caminho: Path = CAMINHO_ENV) -> None:
    """Le o .env e joga as variaveis para o ambiente.

    Nao sobrescreve variaveis que ja existem no sistema.
    """
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        nome, _, valor = linha.partition("=")
        nome = nome.strip()
        valor = valor.strip().strip('"').strip("'")
        if nome and nome not in os.environ:
            os.environ[nome] = valor


class Config:
    """Acesso simples ao config.json, com valores padrao seguros."""

    def __init__(self, dados: dict):
        self.dados = dados

    @classmethod
    def carregar(cls, caminho: Path | str = CAMINHO_CONFIG_PADRAO) -> "Config":
        caminho = Path(caminho)
        if not caminho.exists():
            raise FileNotFoundError(f"Arquivo de configuracao nao encontrado: {caminho}")
        return cls(json.loads(caminho.read_text(encoding="utf-8")))

    def secao(self, nome: str) -> dict:
        valor = self.dados.get(nome, {})
        return valor if isinstance(valor, dict) else {}

    @property
    def torneios(self) -> list[dict]:
        return list(self.dados.get("torneios", []))

    @property
    def coleta(self) -> dict:
        return self.secao("coleta")

    @property
    def referencia(self) -> dict:
        return self.secao("referencia")

    @property
    def casas_monitoradas(self) -> dict:
        return self.secao("casas_monitoradas")

    @property
    def deteccao(self) -> dict:
        return self.secao("deteccao")

    @property
    def alertas(self) -> dict:
        return self.secao("alertas")

    @property
    def armazenamento(self) -> dict:
        return self.secao("armazenamento")

    def caminho_banco(self) -> Path:
        relativo = self.armazenamento.get("arquivo_banco", "dados/historico.db")
        caminho = Path(relativo)
        return caminho if caminho.is_absolute() else RAIZ / caminho


def chave_api_odds() -> str | None:
    valor = os.environ.get("ODDS_API_KEY", "").strip()
    return valor or None


def credenciais_telegram() -> tuple[str | None, str | None]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() or None
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip() or None
    return token, chat_id
