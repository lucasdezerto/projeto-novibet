"""Historico em SQLite.

A Fase 2 do projeto e justamente acumular dados para responder "quais casas
atrasam, com que frequencia e por quanto tempo". Tudo que o bot coleta e todo
alerta que ele dispara ficam gravados aqui.

SQLite foi escolhido por ser um arquivo so, sem servidor para instalar. Se o
volume crescer, a troca para Postgres/TimescaleDB e direta.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from src.modelos import Alerta, OddNormalizada

ESQUEMA = """
CREATE TABLE IF NOT EXISTS odds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    casa TEXT NOT NULL,
    evento_id TEXT NOT NULL,
    evento_descricao TEXT,
    torneio_id TEXT,
    mercado TEXT NOT NULL,
    selecao TEXT NOT NULL,
    odd REAL NOT NULL,
    suspenso INTEGER NOT NULL DEFAULT 0,
    ao_vivo INTEGER NOT NULL DEFAULT 0,
    timestamp_coleta TEXT NOT NULL,
    timestamp_fonte TEXT
);

CREATE INDEX IF NOT EXISTS idx_odds_evento ON odds (evento_id, mercado, selecao);
CREATE INDEX IF NOT EXISTS idx_odds_casa_tempo ON odds (casa, timestamp_coleta);

CREATE TABLE IF NOT EXISTS alertas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL,
    casa TEXT NOT NULL,
    evento_id TEXT NOT NULL,
    evento_descricao TEXT,
    torneio_id TEXT,
    mercado TEXT NOT NULL,
    selecao TEXT NOT NULL,
    odd_casa REAL NOT NULL,
    odd_referencia REAL NOT NULL,
    casa_referencia TEXT NOT NULL,
    desvio REAL NOT NULL,
    segundos_parado REAL NOT NULL,
    detalhe TEXT,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alertas_casa ON alertas (casa, timestamp);
"""


def _texto_data(valor: datetime | None) -> str | None:
    return valor.isoformat() if valor else None


class HistoricoSqlite:
    def __init__(self, caminho: Path | str):
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.conexao = sqlite3.connect(str(self.caminho))
        self.conexao.executescript(ESQUEMA)
        self.conexao.commit()

    def gravar_odds(self, odds: list[OddNormalizada]) -> int:
        if not odds:
            return 0
        linhas = [
            (
                o.casa,
                o.evento_id_normalizado,
                o.evento_descricao,
                o.torneio_id,
                o.mercado,
                o.selecao,
                o.odd,
                int(o.suspenso),
                int(o.ao_vivo),
                _texto_data(o.timestamp_coleta),
                _texto_data(o.timestamp_fonte),
            )
            for o in odds
        ]
        self.conexao.executemany(
            "INSERT INTO odds (casa, evento_id, evento_descricao, torneio_id, mercado, "
            "selecao, odd, suspenso, ao_vivo, timestamp_coleta, timestamp_fonte) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            linhas,
        )
        self.conexao.commit()
        return len(linhas)

    def gravar_alerta(self, alerta: Alerta) -> None:
        self.conexao.execute(
            "INSERT INTO alertas (tipo, casa, evento_id, evento_descricao, torneio_id, "
            "mercado, selecao, odd_casa, odd_referencia, casa_referencia, desvio, "
            "segundos_parado, detalhe, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                alerta.tipo,
                alerta.casa,
                alerta.evento_id_normalizado,
                alerta.evento_descricao,
                alerta.torneio_id,
                alerta.mercado,
                alerta.selecao,
                alerta.odd_casa,
                alerta.odd_referencia,
                alerta.casa_referencia,
                alerta.desvio,
                alerta.segundos_parado,
                alerta.detalhe,
                _texto_data(alerta.timestamp),
            ),
        )
        self.conexao.commit()

    def resumo_por_casa(self) -> list[tuple]:
        """Relatorio da Fase 2: quem atrasa mais, quanto e por quanto tempo."""
        cursor = self.conexao.execute(
            "SELECT casa, tipo, COUNT(*) AS alertas, "
            "ROUND(AVG(desvio) * 100, 2) AS desvio_medio_pct, "
            "ROUND(AVG(segundos_parado), 1) AS segundos_parado_medio "
            "FROM alertas GROUP BY casa, tipo ORDER BY alertas DESC"
        )
        return cursor.fetchall()

    def resumo_de_atraso(self, minimo_de_amostras: int = 5) -> list[dict]:
        """Mede, casa por casa, o quanto ela reprecifica depois do mercado.

        Só funciona com fontes que informam `timestamp_fonte` (o `updatedAt`
        da odds-api.io). Para cada foto do mercado, a casa que reprecificou
        mais recentemente define o "agora" daquele mercado; o atraso de cada
        casa é a distância até ela.

        É este número que responde à pergunta do projeto: a Novibet atrasa, e
        quanto?
        """
        linhas = self.conexao.execute(
            "SELECT casa, evento_id, mercado, selecao, timestamp_coleta, timestamp_fonte "
            "FROM odds WHERE timestamp_fonte IS NOT NULL"
        ).fetchall()

        # Agrupa por foto do mercado: mesmo jogo, mesmo mercado, mesma coleta.
        fotos: dict[tuple, dict[str, datetime]] = {}
        for casa, evento, mercado, selecao, coleta, fonte in linhas:
            try:
                momento = datetime.fromisoformat(fonte)
            except (TypeError, ValueError):
                continue
            chave = (evento, mercado, selecao, coleta)
            por_casa = fotos.setdefault(chave, {})
            # Se a casa aparecer duas vezes, fica a atualização mais recente.
            if casa not in por_casa or momento > por_casa[casa]:
                por_casa[casa] = momento

        atrasos: dict[str, list[float]] = {}
        for por_casa in fotos.values():
            if len(por_casa) < 2:
                continue  # sem com quem comparar
            mais_recente = max(por_casa.values())
            for casa, momento in por_casa.items():
                atrasos.setdefault(casa, []).append((mais_recente - momento).total_seconds())

        resumo = []
        for casa, valores in atrasos.items():
            if len(valores) < minimo_de_amostras:
                continue
            ordenados = sorted(valores)
            meio = len(ordenados) // 2
            mediana = (
                ordenados[meio]
                if len(ordenados) % 2
                else (ordenados[meio - 1] + ordenados[meio]) / 2
            )
            resumo.append(
                {
                    "casa": casa,
                    "amostras": len(valores),
                    "atraso_medio_s": sum(valores) / len(valores),
                    "atraso_mediano_s": mediana,
                    "atraso_maximo_s": ordenados[-1],
                    "pct_parada_mais_de_60s": 100.0
                    * sum(1 for v in valores if v > 60)
                    / len(valores),
                }
            )
        return sorted(resumo, key=lambda r: r["atraso_mediano_s"], reverse=True)

    def encerrar(self) -> None:
        self.conexao.close()
