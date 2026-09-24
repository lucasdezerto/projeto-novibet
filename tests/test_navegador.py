"""Testes do interceptador e do monitor de saude.

Nenhum teste abre navegador: o interceptador foi escrito de forma que a parte
que traduz payloads (`traduzir`) seja testavel com dados gravados.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.adapters.casas.base import ParserDeCasa
from src.adapters.casas.novibet import ParserNovibet
from src.adapters.monitor import MonitorDeSaude
from src.adapters.navegador import AdapterNavegador, BufferDePayloads, PlaywrightAusente

FIXTURES = Path(__file__).parent / "fixtures"
AGORA = datetime(2026, 9, 23, 23, 50, tzinfo=timezone.utc)
URL_FEED = "https://www.novibet.bet.br/spt/feed/marketviews/location/v2/4324/5931237/"


def corpo_real() -> str:
    return (FIXTURES / "novibet_atp_chengdu.json").read_text(encoding="utf-8")


def montar_adapter(parser=None):
    return AdapterNavegador(parser=parser or ParserNovibet(), torneios=[])


# -------------------------------------------------------------------- buffer


def test_buffer_guarda_e_esvazia():
    buffer = BufferDePayloads()
    buffer.adicionar("atp-chengdu", URL_FEED, "{}")
    buffer.adicionar("atp-chengdu", URL_FEED, "[]")
    assert len(buffer) == 2

    itens = buffer.drenar()
    assert len(itens) == 2
    assert len(buffer) == 0, "drenar tinha que esvaziar o buffer"


def test_buffer_descarta_os_mais_velhos_em_vez_de_crescer_sem_limite():
    buffer = BufferDePayloads(tamanho_maximo=3)
    for i in range(5):
        buffer.adicionar("t", URL_FEED, str(i))

    itens = buffer.drenar()
    assert len(itens) == 3
    assert [c for _, _, c in itens] == ["2", "3", "4"]
    assert buffer.descartados == 2


# ------------------------------------------------------------------ traduzir


def test_traduz_payload_interceptado_de_verdade():
    odds = montar_adapter().traduzir([("atp-chengdu", URL_FEED, corpo_real())], AGORA)
    assert len(odds) == 6
    assert {o.casa for o in odds} == {"novibet_br"}


def test_varios_payloads_do_mesmo_ciclo_sao_todos_traduzidos():
    capturados = [
        ("atp-chengdu", URL_FEED, corpo_real()),
        ("atp-chengdu", URL_FEED, corpo_real()),
    ]
    assert len(montar_adapter().traduzir(capturados, AGORA)) == 12


def test_payload_que_nao_e_json_e_pulado_sem_derrubar_o_ciclo():
    capturados = [
        ("atp-chengdu", URL_FEED, "<html>pagina de erro</html>"),
        ("atp-chengdu", URL_FEED, corpo_real()),
    ]
    assert len(montar_adapter().traduzir(capturados, AGORA)) == 6


def test_parser_que_explode_nao_derruba_o_bot():
    """Se a casa mudar o formato, o ciclo se perde mas o bot continua vivo."""

    class ParserQuebrado(ParserDeCasa):
        nome = "quebrado"

        def paginas(self, torneios):
            return []

        def interessa(self, url):
            return True

        def converter(self, url, dados, torneio_id, agora):
            raise KeyError("campo que sumiu")

    adapter = montar_adapter(ParserQuebrado())
    assert adapter.traduzir([("t", URL_FEED, "[]")], AGORA) == []


def test_sem_playwright_a_mensagem_diz_como_instalar():
    adapter = montar_adapter()

    def importacao_que_falha():
        raise PlaywrightAusente("A Opcao B precisa do Playwright")

    adapter._importar_playwright = importacao_que_falha
    with pytest.raises(PlaywrightAusente, match="Playwright"):
        adapter.iniciar()


# ------------------------------------------------------------------- monitor


def test_monitor_fica_quieto_enquanto_chega_dado():
    monitor = MonitorDeSaude(silencio_maximo_segundos=300)
    monitor.registrar("novibet_br", 6, AGORA)
    monitor.registrar("novibet_br", 6, AGORA + timedelta(seconds=120))
    assert monitor.fontes_em_silencio(AGORA + timedelta(seconds=120)) == []


def test_monitor_avisa_quando_a_fonte_para_de_trazer_dados():
    monitor = MonitorDeSaude(silencio_maximo_segundos=300)
    monitor.registrar("novibet_br", 6, AGORA)

    depois = AGORA + timedelta(seconds=400)
    monitor.registrar("novibet_br", 0, depois)

    avisos = monitor.fontes_em_silencio(depois)
    assert len(avisos) == 1
    nome, motivo = avisos[0]
    assert nome == "novibet_br"
    assert "sem odds" in motivo


def test_monitor_avisa_so_uma_vez_por_episodio():
    monitor = MonitorDeSaude(silencio_maximo_segundos=300)
    monitor.registrar("novibet_br", 6, AGORA)
    depois = AGORA + timedelta(seconds=400)
    monitor.registrar("novibet_br", 0, depois)

    assert len(monitor.fontes_em_silencio(depois)) == 1
    assert monitor.fontes_em_silencio(depois + timedelta(seconds=60)) == []


def test_monitor_volta_a_avisar_depois_que_a_fonte_se_recupera_e_cai_de_novo():
    monitor = MonitorDeSaude(silencio_maximo_segundos=300)
    monitor.registrar("novibet_br", 6, AGORA)
    caiu = AGORA + timedelta(seconds=400)
    monitor.registrar("novibet_br", 0, caiu)
    assert monitor.fontes_em_silencio(caiu)

    voltou = caiu + timedelta(seconds=30)
    monitor.registrar("novibet_br", 6, voltou)
    assert monitor.fontes_em_silencio(voltou) == []

    caiu_de_novo = voltou + timedelta(seconds=400)
    monitor.registrar("novibet_br", 0, caiu_de_novo)
    assert monitor.fontes_em_silencio(caiu_de_novo)


def test_fonte_que_nunca_trouxe_nada_e_denunciada():
    monitor = MonitorDeSaude()
    for i in range(3):
        monitor.registrar("bet365_br", 0, AGORA + timedelta(seconds=i * 60))

    avisos = monitor.fontes_em_silencio(AGORA + timedelta(seconds=180))
    assert avisos and avisos[0][0] == "bet365_br"
    assert "nunca" in avisos[0][1]


def test_resumo_lista_todas_as_fontes():
    monitor = MonitorDeSaude()
    monitor.registrar("novibet_br", 6, AGORA)
    monitor.registrar("the_odds_api", 40, AGORA)

    resumo = " | ".join(monitor.resumo(AGORA))
    assert "novibet_br" in resumo and "the_odds_api" in resumo
    assert "6 odds" in resumo
