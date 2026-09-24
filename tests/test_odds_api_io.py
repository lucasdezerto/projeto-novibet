"""Testes do coletor da odds-api.io.

Nenhum teste toca a internet. Os payloads seguem a forma documentada da API
(https://docs.odds-api.io), inclusive os precos como texto e o `updatedAt` por
casa e por mercado, que e o campo que torna esta fonte interessante.
"""

from datetime import datetime, timezone

import pytest

from src.adapters.odds_api_io import AdapterOddsApiIo, ErroOddsApiIo
from src.normalizador.eventos import gerar_id_evento

TORNEIOS = [
    {
        "id": "atp-chengdu",
        "nome": "ATP Chengdu (CHN)",
        "circuito": "ATP",
        "termos_nome": ["chengdu"],
    },
    {
        "id": "wta-seoul",
        "nome": "WTA Seoul (KOR)",
        "circuito": "WTA",
        "termos_nome": ["seoul", "korea open"],
    },
]

EVENTOS = [
    {
        "id": 123456,
        "home": "Jannik Sinner",
        "away": "Alexander Zverev",
        "date": "2026-09-24T09:00:00Z",
        "status": "pending",
        "sport": {"name": "Tennis", "slug": "tennis"},
        "league": {"name": "ATP Chengdu", "slug": "atp-chengdu"},
    },
    {
        "id": 999001,
        "home": "Iga Swiatek",
        "away": "Aryna Sabalenka",
        "date": "2026-09-24T11:00:00Z",
        "status": "pending",
        "sport": {"name": "Tennis", "slug": "tennis"},
        "league": {"name": "WTA Seoul", "slug": "wta-seoul"},
    },
    {
        "id": 555000,
        "home": "Alguem Qualquer",
        "away": "Outro Qualquer",
        "date": "2026-09-24T13:00:00Z",
        "sport": {"name": "Tennis", "slug": "tennis"},
        "league": {"name": "Challenger Genoa", "slug": "challenger-genoa"},
    },
]

ODDS = [
    {
        "id": 123456,
        "home": "Jannik Sinner",
        "away": "Alexander Zverev",
        "date": "2026-09-24T09:00:00Z",
        "bookmakers": {
            "ON Sharp": [
                {
                    "name": "ML",
                    "updatedAt": "2026-09-24T08:59:00Z",
                    "odds": [{"home": "1.45", "away": "2.85"}],
                }
            ],
            "Novibet GR": [
                {
                    "name": "ML",
                    "updatedAt": "2026-09-24T08:52:00Z",
                    "odds": [{"home": "1.42", "away": "3.60"}],
                }
            ],
        },
    }
]


# Sentinela proprio: None e um dos payloads invalidos que queremos testar,
# entao nao pode significar "use o payload padrao".
PADRAO = object()


class ApiFalsa:
    def __init__(self, eventos=PADRAO, odds=PADRAO):
        self.eventos = EVENTOS if eventos is PADRAO else eventos
        self.odds = ODDS if odds is PADRAO else odds
        self.urls = []

    def __call__(self, url, tempo_limite=25):
        self.urls.append(url)
        if "/events?" in url:
            return self.eventos
        if "/odds/multi?" in url:
            return self.odds
        return []


def montar(api=None, **extras):
    parametros = {
        "chave_api": "chave-de-teste",
        "casas": ["Novibet GR", "ON Sharp"],
        "torneios": TORNEIOS,
        "buscar_json": api or ApiFalsa(),
    }
    parametros.update(extras)
    return AdapterOddsApiIo(**parametros)


# ------------------------------------------------------------ filtro de ligas


def test_filtra_os_jogos_pelos_torneios_do_config():
    eventos = montar().listar_eventos()
    assert [e["id"] for e in eventos] == [123456, 999001], "o Challenger nao devia passar"


def test_sem_filtro_traz_o_circuito_inteiro():
    """Modo de medicao: para saber se a casa atrasa, mais jogo e melhor."""
    eventos = montar(filtrar_torneios=False).listar_eventos()
    assert len(eventos) == 3


def test_liga_com_nome_diferente_ainda_casa_pelo_termo_alternativo():
    eventos = list(EVENTOS)
    eventos[1] = {**eventos[1], "league": {"name": "WTA Korea Open", "slug": "wta-korea-open"}}
    encontrados = montar(ApiFalsa(eventos=eventos)).listar_eventos()
    assert 999001 in [e["id"] for e in encontrados]


def test_nao_confunde_atp_com_wta_na_mesma_cidade():
    eventos = [{**EVENTOS[0], "league": {"name": "WTA Chengdu", "slug": "wta-chengdu"}}]
    assert montar(ApiFalsa(eventos=eventos)).listar_eventos() == []


# ------------------------------------------------------------------ conversao


def test_converte_para_o_schema_unico():
    odds = montar().coletar()
    assert len(odds) == 4  # 2 casas x 2 jogadores
    assert {o.casa for o in odds} == {"novibet_gr", "on_sharp"}
    assert {o.mercado for o in odds} == {"h2h"}
    assert {o.torneio_id for o in odds} == {"atp-chengdu"}
    assert {o.selecao for o in odds} == {"sinner", "zverev"}


def test_preco_em_texto_vira_numero():
    odds = montar().coletar()
    novibet = {o.selecao: o.odd for o in odds if o.casa == "novibet_gr"}
    assert novibet == {"sinner": 1.42, "zverev": 3.60}


def test_carimbo_de_atualizacao_da_casa_e_aproveitado():
    """E o campo que faz esta fonte valer mais que as outras."""
    odds = montar().coletar()
    novibet = next(o for o in odds if o.casa == "novibet_gr")
    sharp = next(o for o in odds if o.casa == "on_sharp")

    assert novibet.timestamp_fonte == datetime(2026, 9, 24, 8, 52, tzinfo=timezone.utc)
    assert sharp.timestamp_fonte == datetime(2026, 9, 24, 8, 59, tzinfo=timezone.utc)
    # A Novibet reprecificou 7 minutos antes da referencia: e exatamente o
    # sinal de atraso que o projeto procura.
    assert novibet.timestamp_fonte < sharp.timestamp_fonte


def test_o_id_do_evento_e_o_mesmo_das_outras_fontes():
    odds = montar().coletar()
    esperado = gerar_id_evento("Alexander Zverev", "Jannik Sinner", "2026-09-24T09:00:00Z")
    assert {o.evento_id_normalizado for o in odds} == {esperado}


def test_jogo_fora_dos_torneios_do_config_recebe_id_generico():
    api = ApiFalsa(odds=[{**ODDS[0], "id": 555000, "home": "Alguem Qualquer", "away": "Outro Qualquer"}])
    odds = montar(api, filtrar_torneios=False).coletar()
    assert {o.torneio_id for o in odds} == {"outro:challenger-genoa"}


# ------------------------------------------------------- resistencia a lixo


def test_resposta_embrulhada_em_data_tambem_funciona():
    api = ApiFalsa(eventos={"data": EVENTOS}, odds={"data": ODDS})
    assert montar(api).coletar()


def test_payload_estranho_nao_derruba_a_coleta():
    for lixo in [None, {}, [], [None], "texto", [{"id": 1}], [{"bookmakers": "nao e dict"}]]:
        assert montar(ApiFalsa(odds=lixo)).coletar() == []


def test_precos_invalidos_sao_descartados():
    odds_ruins = [
        {
            **ODDS[0],
            "bookmakers": {
                "Novibet GR": [
                    {
                        "name": "ML",
                        "updatedAt": "2026-09-24T08:52:00Z",
                        "odds": [{"home": None, "away": "abc"}, {"home": "1.00", "away": "2.50"}],
                    }
                ]
            },
        }
    ]
    odds = montar(ApiFalsa(odds=odds_ruins)).coletar()
    assert len(odds) == 1 and odds[0].odd == 2.50


def test_mercado_desconhecido_e_ignorado():
    outro = [{**ODDS[0], "bookmakers": {"Novibet GR": [
        {"name": "Totals (Games)", "odds": [{"over": "1.90", "under": "1.90"}]}
    ]}}]
    assert montar(ApiFalsa(odds=outro)).coletar() == []


def test_carimbo_invalido_nao_derruba_o_resto():
    sem_data = [{**ODDS[0], "bookmakers": {"Novibet GR": [
        {"name": "ML", "updatedAt": "nao-e-data", "odds": [{"home": "1.42", "away": "3.60"}]}
    ]}}]
    odds = montar(ApiFalsa(odds=sem_data)).coletar()
    assert len(odds) == 2
    assert all(o.timestamp_fonte is None for o in odds)


# ---------------------------------------------------------------- requisicoes


def test_pede_as_casas_e_os_mercados_certos():
    api = ApiFalsa()
    montar(api).coletar()
    url_odds = next(u for u in api.urls if "/odds/multi?" in u)
    assert "Novibet+GR" in url_odds or "Novibet%20GR" in url_odds
    assert "markets=ML" in url_odds
    assert "apiKey=chave-de-teste" in url_odds


def test_respeita_o_limite_de_requisicoes_do_plano_gratuito():
    """O plano gratuito da 100 por hora e 500 por dia; nao da para estourar."""
    muitos = [{**EVENTOS[0], "id": 1000 + i} for i in range(50)]
    api = ApiFalsa(eventos=muitos)
    adapter = montar(api, limite_requisicoes_por_ciclo=3)
    adapter.coletar()
    assert adapter.requisicoes_feitas <= 3


def test_erro_num_lote_nao_impede_os_outros():
    muitos = [{**EVENTOS[0], "id": 1000 + i} for i in range(20)]
    chamadas = {"n": 0}

    def api(url, tempo_limite=25):
        if "/events?" in url:
            return muitos
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise ErroOddsApiIo("HTTP 500 simulado")
        return ODDS

    assert montar(api, limite_requisicoes_por_ciclo=10).coletar()


def test_nome_da_casa_vira_apelido_do_bot():
    assert AdapterOddsApiIo._apelido("Novibet GR") == "novibet_gr"
    assert AdapterOddsApiIo._apelido("ON Sharp") == "on_sharp"
    assert AdapterOddsApiIo._apelido("Stake.bet.br") == "stake_bet_br"
