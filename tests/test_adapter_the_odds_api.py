"""Testes do coletor da API agregadora, com payload gravado.

Nenhum teste aqui toca a internet: o adapter recebe uma funcao de busca
falsa. Assim, se a API mudar o formato da resposta, o teste quebra e a gente
fica sabendo antes de rodar em producao.
"""

import json
from pathlib import Path

import pytest

from src.adapters.the_odds_api import AdapterTheOddsApi, ErroDaApi, SemCreditos

FIXTURES = Path(__file__).parent / "fixtures"

ESPORTES = [
    {"key": "tennis_atp_chengdu_open", "group": "Tennis", "title": "ATP Chengdu Open", "active": True},
    {"key": "tennis_wta_singapore_open", "group": "Tennis", "title": "WTA Singapore Open", "active": True},
    {"key": "tennis_wta_korea_open", "group": "Tennis", "title": "WTA Korea Open (Seoul)", "active": True},
    {"key": "soccer_epl", "group": "Soccer", "title": "EPL", "active": True},
]

TORNEIOS = [
    {"id": "atp-chengdu", "nome": "ATP Chengdu (CHN)", "circuito": "ATP",
     "chaves_api": ["tennis_atp_chengdu_open"], "termos_nome": ["chengdu"]},
    {"id": "atp-hangzhou", "nome": "ATP Hangzhou (CHN)", "circuito": "ATP",
     "chaves_api": ["tennis_atp_hangzhou_open"], "termos_nome": ["hangzhou"]},
    {"id": "wta-seoul", "nome": "WTA Seoul (KOR)", "circuito": "WTA",
     "chaves_api": ["tennis_wta_seoul_open"], "termos_nome": ["seoul", "korea open"]},
    {"id": "wta-singapore", "nome": "WTA Singapore (SGP)", "circuito": "WTA",
     "chaves_api": ["tennis_wta_singapore_open"], "termos_nome": ["singapore"]},
]


def carregar_fixture(nome):
    return json.loads((FIXTURES / nome).read_text(encoding="utf-8"))


class BuscaFalsa:
    """Substitui a chamada HTTP por respostas fixas."""

    def __init__(self, odds_por_chave=None, creditos_restantes=100):
        self.odds_por_chave = odds_por_chave or {}
        self.creditos_restantes = creditos_restantes
        self.creditos_usados = 0
        self.urls_chamadas = []

    def __call__(self, url, tempo_limite=20):
        self.urls_chamadas.append(url)
        self.creditos_restantes -= 1
        self.creditos_usados += 1
        cabecalhos = {
            "x-requests-remaining": str(self.creditos_restantes),
            "x-requests-used": str(self.creditos_usados),
        }
        if "/sports/?" in url:
            return ESPORTES, cabecalhos
        for chave, corpo in self.odds_por_chave.items():
            if f"/sports/{chave}/odds" in url:
                return corpo, cabecalhos
        return [], cabecalhos


def montar_adapter(busca, **extras):
    parametros = {
        "chave_api": "chave-de-teste",
        "torneios": TORNEIOS,
        "regioes": ["eu"],
        "mercados": ["h2h"],
        "buscar_json": busca,
    }
    parametros.update(extras)
    return AdapterTheOddsApi(**parametros)


# ------------------------------------------------------- resolucao de torneios


def test_resolve_torneio_pela_chave_exata():
    adapter = montar_adapter(BuscaFalsa())
    mapa = adapter.resolver_torneios()
    assert mapa["atp-chengdu"]["esporte"]["key"] == "tennis_atp_chengdu_open"
    assert mapa["wta-singapore"]["esporte"]["key"] == "tennis_wta_singapore_open"


def test_resolve_torneio_pelo_nome_quando_a_chave_do_config_nao_existe():
    """Seoul esta na API como 'WTA Korea Open', chave diferente da do config."""
    adapter = montar_adapter(BuscaFalsa())
    mapa = adapter.resolver_torneios()
    assert mapa["wta-seoul"]["esporte"]["key"] == "tennis_wta_korea_open"


def test_torneio_sem_cobertura_fica_registrado_e_nao_quebra():
    adapter = montar_adapter(BuscaFalsa())
    adapter.resolver_torneios()
    assert adapter.torneios_sem_chave == ["ATP Hangzhou (CHN)"]


def test_busca_por_nome_nao_confunde_atp_com_wta():
    """Um torneio ATP nao pode casar com a entrada WTA da mesma cidade."""
    torneio_atp_singapura = [
        {"id": "atp-singapore", "nome": "ATP Singapore", "circuito": "ATP",
         "chaves_api": [], "termos_nome": ["singapore"]}
    ]
    adapter = montar_adapter(BuscaFalsa(), torneios=torneio_atp_singapura)
    assert adapter.resolver_torneios() == {}
    assert adapter.torneios_sem_chave == ["ATP Singapore"]


def test_lista_de_esportes_e_consultada_uma_vez_so():
    busca = BuscaFalsa()
    adapter = montar_adapter(busca)
    adapter.resolver_torneios()
    adapter.resolver_torneios()
    assert sum(1 for u in busca.urls_chamadas if "/sports/?" in u) == 1


# ------------------------------------------------------------------- conversao


def test_converte_o_payload_para_o_schema_unico():
    busca = BuscaFalsa({"tennis_atp_chengdu_open": carregar_fixture("odds_atp_chengdu.json")})
    odds = montar_adapter(busca).coletar()

    assert {o.casa for o in odds} == {"pinnacle", "betsson", "casa_lenta"}
    assert all(o.mercado == "h2h" for o in odds)
    assert all(o.torneio_id == "atp-chengdu" for o in odds)
    assert all(o.timestamp_fonte is not None for o in odds)

    # O ponto central: casas que escrevem o nome diferente caem no mesmo id.
    assert len({o.evento_id_normalizado for o in odds}) == 1
    assert {o.selecao for o in odds} == {"sinner", "zverev"}


def test_odds_invalidas_sao_descartadas_sem_derrubar_a_coleta():
    payload = [
        {
            "commence_time": "2026-09-24T09:00:00Z",
            "home_team": "Jannik Sinner",
            "away_team": "Alexander Zverev",
            "bookmakers": [
                {
                    "key": "casa_x",
                    "last_update": "2026-09-24T09:00:00Z",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Jannik Sinner", "price": None},
                                {"name": "Alexander Zverev", "price": "abc"},
                                {"name": "Sem preco valido", "price": 1.0},
                                {"name": "Jannik Sinner", "price": 1.45},
                            ],
                        }
                    ],
                }
            ],
        }
    ]
    odds = montar_adapter(BuscaFalsa({"tennis_atp_chengdu_open": payload})).coletar()
    assert len(odds) == 1
    assert odds[0].odd == 1.45


def test_evento_sem_jogadores_ou_horario_e_ignorado():
    payload = [{"commence_time": "2026-09-24T09:00:00Z", "bookmakers": []}]
    assert montar_adapter(BuscaFalsa({"tennis_atp_chengdu_open": payload})).coletar() == []


def test_evento_com_horario_invalido_nao_derruba_a_coleta():
    payload = [
        {"commence_time": "nao-e-data", "home_team": "A Silva", "away_team": "B Souza",
         "bookmakers": [{"key": "c", "markets": [{"key": "h2h",
          "outcomes": [{"name": "A Silva", "price": 2.0}]}]}]}
    ]
    assert montar_adapter(BuscaFalsa({"tennis_atp_chengdu_open": payload})).coletar() == []


# ------------------------------------------------------------------------ quota


def test_le_o_saldo_de_creditos_dos_cabecalhos():
    busca = BuscaFalsa(creditos_restantes=500)
    adapter = montar_adapter(busca)
    adapter.coletar()
    assert adapter.creditos_restantes == busca.creditos_restantes
    assert adapter.creditos_usados == busca.creditos_usados


def test_para_sozinho_quando_o_saldo_fica_baixo():
    busca = BuscaFalsa(creditos_restantes=6)
    adapter = montar_adapter(busca, parar_com_creditos_restantes=5)
    with pytest.raises(SemCreditos):
        adapter.coletar()


def test_erro_em_um_torneio_nao_impede_os_outros():
    fixture = carregar_fixture("odds_atp_chengdu.json")
    busca_ok = BuscaFalsa({"tennis_atp_chengdu_open": fixture})

    def busca_com_falha(url, tempo_limite=20):
        if "/sports/tennis_wta_singapore_open/odds" in url:
            raise ErroDaApi("HTTP 500 simulado")
        return busca_ok(url, tempo_limite)

    odds = montar_adapter(busca_com_falha).coletar()
    assert odds, "as odds do Chengdu tinham que vir mesmo com Singapura falhando"
    assert {o.torneio_id for o in odds} == {"atp-chengdu"}
