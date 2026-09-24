"""Testes do parser da Novibet, sobre um payload real gravado do site.

O arquivo tests/fixtures/novibet_atp_chengdu.json foi capturado do
novibet.bet.br em 2026-09-23. Se a casa mudar o formato do feed, estes testes
quebram - que e exatamente o alarme que a Fase 3 do plano pede.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from src.adapters.casas.base import CasaBloqueada, ParserDeCasa
from src.adapters.casas.bet365 import ParserBet365
from src.adapters.casas.novibet import ParserNovibet
from src.normalizador.eventos import gerar_id_evento

FIXTURES = Path(__file__).parent / "fixtures"
AGORA = datetime(2026, 9, 23, 23, 50, tzinfo=timezone.utc)

TORNEIOS = [
    {
        "id": "atp-chengdu",
        "nome": "ATP Chengdu (CHN)",
        "novibet": {"caminho": "/apostas-esportivas/tenis/4372812/atp-250/atp-chengdu/5931297"},
    },
    {"id": "atp-hangzhou", "nome": "ATP Hangzhou (CHN)"},
]


def payload_real():
    return json.loads((FIXTURES / "novibet_atp_chengdu.json").read_text(encoding="utf-8"))


# Sentinela proprio: None e um dos payloads invalidos que queremos testar,
# entao nao serve como "use o payload real".
PADRAO = object()


def converter(parser=None, dados=PADRAO):
    parser = parser or ParserNovibet()
    return parser.converter(
        "https://www.novibet.bet.br/spt/feed/marketviews/location/v2/4324/5931237/",
        payload_real() if dados is PADRAO else dados,
        "atp-chengdu",
        AGORA,
    )


# ------------------------------------------------------------------ paginas


def test_monta_a_url_so_dos_torneios_que_tem_caminho_no_config():
    paginas = ParserNovibet().paginas(TORNEIOS)
    assert paginas == [
        (
            "atp-chengdu",
            "https://www.novibet.bet.br/apostas-esportivas/tenis/4372812/atp-250/atp-chengdu/5931297",
        )
    ]


def test_filtro_de_urls_pega_o_feed_de_odds_e_ignora_o_resto():
    parser = ParserNovibet()
    assert parser.interessa(
        "https://www.novibet.bet.br/spt/feed/marketviews/location/v2/4324/5931237/?lang=pt-BR"
    )
    assert not parser.interessa("https://www.novibet.bet.br/chunk-LYZ6T2GX.js")
    assert not parser.interessa("https://www.novibet.bet.br/gpua/ga/g/c?v=2")
    assert not parser.interessa("https://www.novibet.bet.br/spt/feed/navigation/coupon/v2/4324")


# ----------------------------------------------------------------- conversao


def test_converte_o_payload_real_para_o_schema_unico():
    odds = converter()

    assert odds, "o payload real tinha que produzir odds"
    assert {o.casa for o in odds} == {"novibet_br"}
    assert {o.mercado for o in odds} == {"h2h"}
    assert {o.torneio_id for o in odds} == {"atp-chengdu"}
    assert all(o.odd > 1.0 for o in odds)
    assert all(not o.suspenso for o in odds)
    assert all(not o.ao_vivo for o in odds)
    assert all(o.timestamp_coleta == AGORA for o in odds)

    # 3 jogos x 2 jogadores
    assert len(odds) == 6
    assert len({o.evento_id_normalizado for o in odds}) == 3


def test_o_codigo_1_e_2_vira_o_nome_do_jogador():
    """Sem isso nao da para comparar a Novibet com nenhuma outra fonte."""
    odds = converter()
    jogo = [o for o in odds if "duckworth" in o.evento_id_normalizado]

    por_selecao = {o.selecao: o.odd for o in jogo}
    assert por_selecao == {"duckworth": 2.10, "sonego": 1.74}


def test_o_id_do_evento_bate_com_o_que_a_api_agregadora_geraria():
    """O teste que prova que a Opcao A e a Opcao B falam do mesmo jogo."""
    odds = converter()
    ids_novibet = {o.evento_id_normalizado for o in odds}

    # Como a API agregadora escreveria os mesmos jogos.
    id_agregador = gerar_id_evento("Lorenzo Sonego", "James Duckworth", "2026-09-24T05:00:00Z")
    assert id_agregador in ids_novibet


def test_mercado_repetido_no_mesmo_jogo_usa_so_o_primeiro():
    """A Novibet mandou 'Vencedor da partida' duas vezes num jogo real."""
    odds = converter()
    griekspoor = [o for o in odds if "griekspoor" in o.evento_id_normalizado]

    assert len(griekspoor) == 2, "o mercado repetido gerou preco duplicado"
    assert {o.odd for o in griekspoor} == {2.37, 1.73}


def test_mercado_de_total_de_games_so_entra_quando_pedido():
    assert not [o for o in converter() if o.mercado == "totals"]

    odds = converter(ParserNovibet(mercados=["h2h", "totals"]))
    totais = [o for o in odds if o.mercado == "totals"]
    assert totais
    assert {o.selecao for o in totais} >= {"over-22.5", "under-22.5", "over-21.5"}


def test_mercado_fora_do_ar_vira_suspenso():
    dados = payload_real()
    itens = dados[0]["betViews"][0]["items"]
    itens[0]["markets"][0]["betItems"][0]["isAvailable"] = False

    odds = converter(dados=dados)
    suspensas = [o for o in odds if o.suspenso]
    assert len(suspensas) == 1
    assert suspensas[0].selecao == "duckworth"


def test_jogo_ao_vivo_e_marcado():
    dados = payload_real()
    dados[0]["betViews"][0]["items"][0]["isLive"] = True
    assert [o for o in converter(dados=dados) if o.ao_vivo]


# ------------------------------------------------------- resistencia a lixo


def test_payload_de_formato_inesperado_devolve_vazio_sem_levantar_erro():
    parser = ParserNovibet()
    for lixo in [None, {}, "texto", [], [None], [{"betViews": None}], [{"betViews": [{}]}]]:
        assert converter(parser, lixo) == []


def test_evento_sem_jogadores_ou_sem_data_e_ignorado():
    dados = payload_real()
    itens = dados[0]["betViews"][0]["items"]
    itens[0]["additionalCaptions"] = {"competitor1": "So um jogador"}
    itens[1]["startDate"] = None
    itens[2]["startDate"] = "nao-e-data"
    assert converter(dados=dados) == []


def test_preco_invalido_e_descartado_sem_derrubar_o_resto():
    dados = payload_real()
    itens = dados[0]["betViews"][0]["items"]
    itens[0]["markets"][0]["betItems"][0]["price"] = None
    itens[1]["markets"][0]["betItems"][0]["price"] = "abc"
    itens[2]["markets"][0]["betItems"][0]["price"] = 1.0

    odds = converter(dados=dados)
    assert len(odds) == 3, "so os precos validos tinham que sobrar"


def test_codigo_de_selecao_desconhecido_e_ignorado():
    dados = payload_real()
    dados[0]["betViews"][0]["items"][0]["markets"][0]["betItems"][0]["code"] = "Z"
    odds = converter(dados=dados)
    assert len(odds) == 5


# ------------------------------------------------------------------ bloqueio


def test_novibet_reconhece_a_tela_da_cloudflare_que_apareceu_de_verdade():
    """Texto capturado rodando Chromium automatizado em 2026-09-23."""
    parser = ParserNovibet()
    tela_real = (
        "www.novibet.bet.br\n"
        "Executando verificação de segurança\n"
        "Este site utiliza um serviço de segurança para proteção contra bots "
        "maliciosos. Esta página é exibida enquanto o site verifica se você não é um bot.\n"
        "Ray ID: a3fd806479e9f1bd"
    )
    assert parser.esta_bloqueado(tela_real)
    assert parser.esta_bloqueado("Verifying you are human. Aguarde...")
    assert not parser.esta_bloqueado("Apostas ATP 250 Chengdu | Odds Tenis")
    assert not parser.esta_bloqueado("James Duckworth x Lorenzo Sonego 2.10 1.74")


def test_bloqueio_e_reconhecido_tambem_em_ingles():
    """A Cloudflare escolhe o idioma pelo navegador.

    O primeiro teste ao vivo passou batido justamente por isto: a tela veio
    em ingles e so havia padrao em portugues.
    """
    parser = ParserNovibet()
    tela_em_ingles = (
        "Just a moment...\n"
        "www.novibet.bet.br\n"
        "Performing security verification\n"
        "This website uses a security service to protect against malicious bots. "
        "This page is displayed while the website verifies you are not a bot.\n"
        "Ray ID: a3fd855d6894f1d7"
    )
    assert parser.esta_bloqueado(tela_em_ingles)


def test_bet365_reconhece_a_tela_que_apareceu_de_verdade():
    """Texto capturado do bet365.bet.br em 2026-09-23."""
    parser = ParserBet365()
    assert parser.esta_bloqueado("Não é possível exibir este conteúdo")
    assert parser.esta_bloqueado("NÃO É POSSÍVEL EXIBIR ESTE CONTEÚDO")
    assert not parser.esta_bloqueado("Tênis - Próximos")


def test_bet365_nao_coleta_nada_enquanto_estiver_bloqueado():
    parser = ParserBet365()
    assert parser.interessa("https://www.bet365.bet.br/qualquer/coisa") is False
    assert parser.converter("url", [{"qualquer": "coisa"}], "atp-chengdu", AGORA) == []


def test_casa_bloqueada_e_uma_excecao_de_parada():
    assert issubclass(CasaBloqueada, Exception)
    assert isinstance(ParserNovibet(), ParserDeCasa)
    assert isinstance(ParserBet365(), ParserDeCasa)
