"""A prova do projeto: Novibet (Opcao B) comparada contra a referencia (Opcao A).

Este arquivo testa o objetivo que o projeto persegue desde o inicio - detectar
que uma casa brasileira ficou com a odd atrasada em relacao ao mercado. Ele
junta as duas fontes num ciclo so, exatamente como o main.py faz.

Os dados da Novibet saem do payload real capturado do site; os da referencia
imitam o formato da The Odds API para os mesmos jogadores e o mesmo horario.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.adapters.casas.base import CasaBloqueada
from src.adapters.casas.novibet import ParserNovibet
from src.adapters.monitor import MonitorDeSaude
from src.adapters.navegador import AdapterNavegador
from src.adapters.the_odds_api import AdapterTheOddsApi
from src.armazenamento.sqlite import HistoricoSqlite
from src.comparador.estado import ControleDeRepeticao, EstadoDeMercado
from src.comparador.motor import MotorDeComparacao
from src.main import coletar_de_todas_as_fontes, executar_ciclo
from src.modelos import Alerta

FIXTURES = Path(__file__).parent / "fixtures"
URL_FEED = "https://www.novibet.bet.br/spt/feed/marketviews/location/v2/4324/5931237/"

DETECCAO = {
    "desvio_minimo": 0.04,
    "duracao_minima_segundos": 0,
    "movimento_referencia_minimo": 0.03,
    "atraso_maximo_segundos": 60,
    "odd_minima": 1.2,
    "odd_maxima": 15.0,
}

TORNEIOS = [
    {
        "id": "atp-chengdu",
        "nome": "ATP Chengdu (CHN)",
        "circuito": "ATP",
        "chaves_api": ["tennis_atp_chengdu_open"],
        "termos_nome": ["chengdu"],
        "novibet": {"caminho": "/apostas-esportivas/tenis/4372812/atp-250/atp-chengdu/5931297"},
    }
]

ESPORTES = [{"key": "tennis_atp_chengdu_open", "group": "Tennis", "title": "ATP Chengdu Open"}]


def corpo_novibet() -> str:
    return (FIXTURES / "novibet_atp_chengdu.json").read_text(encoding="utf-8")


def payload_referencia(odd_duckworth, odd_sonego):
    """O mesmo jogo, no formato da API agregadora, visto pela Pinnacle."""
    return [
        {
            "commence_time": "2026-09-24T05:00:00Z",
            "home_team": "James Duckworth",
            "away_team": "Lorenzo Sonego",
            "bookmakers": [
                {
                    "key": "pinnacle",
                    "last_update": "2026-09-24T04:00:00Z",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "James Duckworth", "price": odd_duckworth},
                                {"name": "Lorenzo Sonego", "price": odd_sonego},
                            ],
                        }
                    ],
                }
            ],
        }
    ]


class ApiFalsa:
    """Imita a The Odds API, sem rede."""

    def __init__(self):
        self.duckworth = 2.08
        self.sonego = 1.75

    def __call__(self, url, tempo_limite=20):
        cabecalhos = {"x-requests-remaining": "400", "x-requests-used": "100"}
        if "/sports/?" in url:
            return ESPORTES, cabecalhos
        return payload_referencia(self.duckworth, self.sonego), cabecalhos


class NavegadorFalso(AdapterNavegador):
    """Mesmo adapter da Opcao B, mas com payload gravado no lugar do navegador."""

    def __init__(self, parser):
        super().__init__(parser=parser, torneios=TORNEIOS)
        self.corpo = corpo_novibet()
        self.falhar_com = None

    def coletar(self):
        if self.falhar_com:
            raise self.falhar_com
        from src.modelos import agora_utc

        return self.traduzir([("atp-chengdu", URL_FEED, self.corpo)], agora_utc())


class CanalEspiao:
    def __init__(self):
        self.recebidos: list[Alerta] = []

    def enviar(self, alerta):
        self.recebidos.append(alerta)
        return True


def montar(tmp_path):
    api = ApiFalsa()
    adapter_api = AdapterTheOddsApi(
        chave_api="teste", torneios=TORNEIOS, regioes=["eu"], mercados=["h2h"], buscar_json=api
    )
    adapter_navegador = NavegadorFalso(ParserNovibet())
    motor = MotorDeComparacao(
        estado=EstadoDeMercado(), casas_referencia=["pinnacle"], deteccao=DETECCAO
    )
    return (
        api,
        [adapter_api, adapter_navegador],
        adapter_navegador,
        motor,
        CanalEspiao(),
        HistoricoSqlite(tmp_path / "h.db"),
        ControleDeRepeticao(intervalo_segundos=300),
        MonitorDeSaude(silencio_maximo_segundos=300),
    )


# ------------------------------------------------------------------ o essencial


def test_as_duas_fontes_falam_do_mesmo_jogo(tmp_path):
    """Se os ids nao batessem, nada no resto do bot funcionaria."""
    _, adapters, _, _, _, historico, _, monitor = montar(tmp_path)
    odds = coletar_de_todas_as_fontes(adapters, monitor, datetime.now(timezone.utc))

    por_casa = {}
    for o in odds:
        por_casa.setdefault(o.casa, set()).add(o.evento_id_normalizado)

    assert "pinnacle" in por_casa and "novibet_br" in por_casa
    assert por_casa["pinnacle"] & por_casa["novibet_br"], (
        "a Opcao A e a Opcao B nao geraram o mesmo id de evento"
    )
    historico.encerrar()


def test_novibet_alinhada_com_o_mercado_nao_gera_alerta(tmp_path):
    _, adapters, _, motor, canal, historico, repeticao, monitor = montar(tmp_path)
    # Novibet: Duckworth 2.10 / Sonego 1.74. Referencia quase igual.
    executar_ciclo(adapters, motor, [canal], repeticao, historico, monitor)
    assert canal.recebidos == []
    historico.encerrar()


def test_novibet_atrasada_e_detectada_e_alertada(tmp_path):
    """O caso que o projeto inteiro existe para pegar."""
    api, adapters, _, motor, canal, historico, repeticao, monitor = montar(tmp_path)
    executar_ciclo(adapters, motor, [canal], repeticao, historico, monitor)
    assert canal.recebidos == []

    # O mercado despenca para Sonego; a Novibet segue pagando 1.74 nele.
    api.duckworth = 3.60
    api.sonego = 1.32
    executar_ciclo(adapters, motor, [canal], repeticao, historico, monitor)

    assert canal.recebidos, "a Novibet atrasada tinha que alertar"
    alerta = canal.recebidos[0]
    assert alerta.casa == "novibet_br"
    assert alerta.casa_referencia == "pinnacle"
    assert alerta.selecao == "sonego"
    assert alerta.odd_casa == 1.74
    assert alerta.desvio > 0.04
    assert "Duckworth" in alerta.evento_descricao

    gravados = historico.conexao.execute("SELECT casa FROM alertas").fetchall()
    assert ("novibet_br",) in gravados
    historico.encerrar()


def test_odds_das_duas_fontes_vao_para_o_historico(tmp_path):
    _, adapters, _, motor, canal, historico, repeticao, monitor = montar(tmp_path)
    executar_ciclo(adapters, motor, [canal], repeticao, historico, monitor)

    casas = {linha[0] for linha in historico.conexao.execute("SELECT DISTINCT casa FROM odds")}
    assert casas == {"pinnacle", "novibet_br"}
    historico.encerrar()


# ------------------------------------------------------------- resiliencia


def test_uma_fonte_bloqueada_nao_impede_a_outra(tmp_path):
    _, adapters, navegador, motor, canal, historico, repeticao, monitor = montar(tmp_path)
    navegador.falhar_com = CasaBloqueada("bet365 bloqueou o conteudo")

    executar_ciclo(adapters, motor, [canal], repeticao, historico, monitor)
    casas = {linha[0] for linha in historico.conexao.execute("SELECT DISTINCT casa FROM odds")}
    assert casas == {"pinnacle"}, "a API agregadora tinha que continuar coletando"
    historico.encerrar()


def test_erro_inesperado_numa_fonte_nao_derruba_o_ciclo(tmp_path):
    _, adapters, navegador, motor, canal, historico, repeticao, monitor = montar(tmp_path)
    navegador.falhar_com = RuntimeError("o navegador morreu")

    assert executar_ciclo(adapters, motor, [canal], repeticao, historico, monitor) == 0
    assert historico.conexao.execute("SELECT COUNT(*) FROM odds").fetchone()[0] > 0
    historico.encerrar()


def test_monitor_percebe_a_fonte_que_parou_de_trazer_dados(tmp_path):
    _, adapters, navegador, motor, canal, historico, repeticao, monitor = montar(tmp_path)
    agora = datetime(2026, 9, 24, 4, 0, tzinfo=timezone.utc)

    coletar_de_todas_as_fontes(adapters, monitor, agora)
    assert monitor.fontes_em_silencio(agora) == []

    navegador.falhar_com = RuntimeError("parser quebrou")
    depois = agora + timedelta(seconds=400)
    coletar_de_todas_as_fontes(adapters, monitor, depois)

    avisos = dict(monitor.fontes_em_silencio(depois))
    assert "navegador:novibet_br" in avisos
    historico.encerrar()
