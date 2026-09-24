"""Opcao B pela extensao do Chrome (D-018).

Os payloads saem do arquivo real gravado em tests/fixtures. As conversas HTTP
acontecem so dentro do proprio computador (127.0.0.1, porta escolhida pelo
sistema) - nenhum teste acessa a internet.
"""

import json
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.adapters.casas.base import CasaBloqueada
from src.adapters.casas.novibet import ParserNovibet
from src.adapters.extensao import (
    AcumuladorDeOdds,
    AdapterExtensao,
    ErroDaExtensao,
    ReceptorDaExtensao,
    requisicao_permitida,
    torneio_da_pagina,
)
from src.adapters.monitor import MonitorDeSaude
from src.adapters.the_odds_api import AdapterTheOddsApi
from src.armazenamento.sqlite import HistoricoSqlite
from src.comparador.estado import ControleDeRepeticao, EstadoDeMercado
from src.comparador.motor import MotorDeComparacao
from src.config import Config
from src.main import (
    aguardar_primeiras_odds,
    executar_ciclo,
    montar_adapters_de_extensao,
    conferir_extensao,
)
from src.modelos import OddNormalizada
from tests.test_integracao_opcao_b import (
    DETECCAO,
    TORNEIOS,
    URL_FEED,
    ApiFalsa,
    CanalEspiao,
    corpo_novibet,
)

RAIZ = Path(__file__).resolve().parent.parent
PASTA_EXTENSAO = RAIZ / "extensao"
PAGINA_CHENGDU = (
    "https://www.novibet.bet.br/apostas-esportivas/tenis/4372812/atp-250/atp-chengdu/5931297"
)
T0 = datetime(2026, 9, 24, 4, 0, tzinfo=timezone.utc)


def odd(valor, segundos, selecao="sonego", suspenso=False):
    return OddNormalizada(
        casa="novibet_br",
        evento_id_normalizado="duckworth-vs-sonego-2026-09-24T05:00",
        mercado="h2h",
        selecao=selecao,
        odd=valor,
        suspenso=suspenso,
        timestamp_coleta=T0 + timedelta(seconds=segundos),
    )


def postar(porta, caminho, dados, cabecalhos=None, metodo="POST"):
    """Faz o papel da extensao. Devolve o codigo HTTP da resposta."""
    pedido = urllib.request.Request(
        f"http://127.0.0.1:{porta}{caminho}",
        data=json.dumps(dados).encode("utf-8") if dados is not None else None,
        method=metodo,
        headers={"Content-Type": "application/json", **(cabecalhos or {})},
    )
    try:
        with urllib.request.urlopen(pedido, timeout=5) as resposta:
            return resposta.status
    except urllib.error.HTTPError as erro:
        return erro.code


DA_EXTENSAO = {"X-Projeto-Novibet": "1", "Origin": "chrome-extension://abcdef"}


def payload_chengdu():
    return {"tipo": "payload", "url": URL_FEED, "corpo": corpo_novibet(), "pagina": PAGINA_CHENGDU}


@pytest.fixture
def adapter():
    adapter = AdapterExtensao(ParserNovibet(), TORNEIOS, porta=0)
    adapter.iniciar()
    yield adapter
    adapter.encerrar()


# ---------------------------------------------------------- quem pode falar


def test_aceita_so_quem_manda_o_cabecalho_da_extensao():
    assert requisicao_permitida({"X-Projeto-Novibet": "1"})
    assert requisicao_permitida({"X-Projeto-Novibet": "1", "Origin": "chrome-extension://x"})
    assert not requisicao_permitida({})


def test_recusa_pedido_vindo_de_um_site_mesmo_com_o_cabecalho():
    """Um site aberto no navegador nao pode injetar odds falsas no bot."""
    assert not requisicao_permitida(
        {"X-Projeto-Novibet": "1", "Origin": "https://site-qualquer.com"}
    )


# ---------------------------------------------------------- de qual torneio


def test_descobre_o_torneio_pelo_endereco_da_aba():
    assert torneio_da_pagina(PAGINA_CHENGDU, TORNEIOS) == "atp-chengdu"
    assert torneio_da_pagina(PAGINA_CHENGDU + "?x=1", TORNEIOS) == "atp-chengdu"


def test_aba_fora_do_config_fica_sem_torneio():
    assert torneio_da_pagina("https://www.novibet.bet.br/apostas-esportivas/futebol", TORNEIOS) == ""
    assert torneio_da_pagina("", TORNEIOS) == ""


# ---------------------------------------------------------- acumulador


def test_guarda_a_hora_em_que_a_odd_mudou_nao_a_da_ultima_leitura():
    """O motor mede atraso por 'desde quando o preco esta parado'."""
    acumulador = AcumuladorDeOdds()
    acumulador.registrar([odd(1.74, 0)])
    acumulador.registrar([odd(1.80, 10)])
    acumulador.registrar([odd(1.80, 15)])
    acumulador.registrar([odd(1.80, 20)])

    saida = acumulador.drenar(T0 + timedelta(seconds=30))
    assert [(o.odd, o.timestamp_coleta) for o in saida] == [
        (1.74, T0),
        (1.80, T0 + timedelta(seconds=10)),
        (1.80, T0 + timedelta(seconds=20)),
    ]


def test_preco_que_nao_mudou_segue_aparecendo_a_cada_ciclo():
    """Sem isso o motor nao teria a odd parada para comparar com a referencia."""
    acumulador = AcumuladorDeOdds()
    acumulador.registrar([odd(1.74, 0)])
    acumulador.drenar(T0)

    acumulador.registrar([odd(1.74, 5)])
    saida = acumulador.drenar(T0 + timedelta(seconds=10))
    assert [(o.odd, o.timestamp_coleta) for o in saida] == [(1.74, T0 + timedelta(seconds=5))]


def test_mercado_suspenso_conta_como_mudanca():
    acumulador = AcumuladorDeOdds()
    acumulador.registrar([odd(1.74, 0), odd(1.74, 5, suspenso=True)])
    assert [o.suspenso for o in acumulador.drenar(T0)] == [False, True]


def test_sem_nada_novo_devolve_vazio():
    acumulador = AcumuladorDeOdds()
    acumulador.registrar([odd(1.74, 0)])
    acumulador.drenar(T0)
    assert acumulador.drenar(T0 + timedelta(seconds=5)) == []


def test_esquece_preco_de_jogo_que_sumiu_ha_horas():
    acumulador = AcumuladorDeOdds()
    acumulador.registrar([odd(1.74, 0)])
    acumulador.drenar(T0 + timedelta(hours=7))
    # Esquecido: a mesma odd volta a contar como novidade.
    acumulador.registrar([odd(1.74, 7 * 3600 + 1)])
    acumulador.registrar([odd(1.74, 7 * 3600 + 2)])
    assert len(acumulador.drenar(T0 + timedelta(hours=7, seconds=3))) == 2


# ---------------------------------------------------------- receptor


def test_payload_real_vira_odds_com_o_torneio_certo():
    receptor = ReceptorDaExtensao(ParserNovibet(), TORNEIOS)
    quantas = receptor.receber_payload(URL_FEED, corpo_novibet(), PAGINA_CHENGDU, T0)

    odds = receptor.drenar(T0)
    assert quantas > 0 and len(odds) == quantas
    assert {o.casa for o in odds} == {"novibet_br"}
    assert {o.torneio_id for o in odds} == {"atp-chengdu"}
    assert all(o.timestamp_coleta == T0 for o in odds)


def test_resposta_que_nao_e_de_odds_e_ignorada():
    receptor = ReceptorDaExtensao(ParserNovibet(), TORNEIOS)
    assert receptor.receber_payload("https://www.novibet.bet.br/api/banners", "[]", "", T0) == 0
    assert receptor.payloads_recebidos == 0


def test_corpo_quebrado_nao_derruba_o_receptor():
    receptor = ReceptorDaExtensao(ParserNovibet(), TORNEIOS)
    assert receptor.receber_payload(URL_FEED, "{nao e json", PAGINA_CHENGDU, T0) == 0
    assert receptor.drenar(T0) == []


def test_tela_de_verificacao_na_aba_para_a_fonte():
    receptor = ReceptorDaExtensao(ParserNovibet(), TORNEIOS)
    receptor.receber_estado(PAGINA_CHENGDU, "Just a moment...", "", T0)
    with pytest.raises(CasaBloqueada):
        receptor.conferir_bloqueio(T0 + timedelta(seconds=10))


def test_aba_normal_nao_e_bloqueio():
    receptor = ReceptorDaExtensao(ParserNovibet(), TORNEIOS)
    receptor.receber_estado(PAGINA_CHENGDU, "ATP Chengdu | Novibet", "Vencedor da partida", T0)
    receptor.conferir_bloqueio(T0 + timedelta(seconds=10))


def test_aviso_de_bloqueio_antigo_nao_conta_mais():
    """A aba pode ter sido fechada; um aviso de minutos atras nao para o bot."""
    receptor = ReceptorDaExtensao(ParserNovibet(), TORNEIOS)
    receptor.receber_estado(PAGINA_CHENGDU, "Just a moment...", "", T0)
    receptor.conferir_bloqueio(T0 + timedelta(seconds=200))


# ---------------------------------------------------------- pela rede local


def test_extensao_entrega_odds_pelo_endereco_local(adapter):
    assert postar(adapter.porta, "/payload", payload_chengdu(), DA_EXTENSAO) == 204
    odds = adapter.coletar()
    assert odds and {o.torneio_id for o in odds} == {"atp-chengdu"}


def test_endereco_local_recusa_quem_nao_e_a_extensao(adapter):
    assert postar(adapter.porta, "/payload", payload_chengdu()) == 403
    site = {"X-Projeto-Novibet": "1", "Origin": "https://site-qualquer.com"}
    assert postar(adapter.porta, "/payload", payload_chengdu(), site) == 403
    assert postar(adapter.porta, "/payload", None, DA_EXTENSAO, metodo="OPTIONS") == 403
    assert adapter.coletar() == []


def test_endereco_local_recusa_caminho_desconhecido_e_corpo_invalido(adapter):
    assert postar(adapter.porta, "/outra-coisa", {"x": 1}, DA_EXTENSAO) == 404
    assert postar(adapter.porta, "/payload", [1, 2], DA_EXTENSAO) == 400


def test_estado_de_bloqueio_pelo_endereco_local_para_a_fonte(adapter):
    estado = {"tipo": "estado", "pagina": PAGINA_CHENGDU, "titulo": "Just a moment...", "texto": ""}
    assert postar(adapter.porta, "/estado", estado, DA_EXTENSAO) == 204
    with pytest.raises(CasaBloqueada):
        adapter.coletar()


def test_porta_ocupada_vira_erro_claro(adapter):
    segundo = AdapterExtensao(ParserNovibet(), TORNEIOS, porta=adapter.porta)
    with pytest.raises(ErroDaExtensao, match="porta"):
        segundo.iniciar()


# ---------------------------------------------------------- ponta a ponta


def test_novibet_pela_extensao_atrasada_gera_alerta(tmp_path, adapter):
    """O objetivo do projeto, com a Novibet chegando pela extensao."""
    api = ApiFalsa()
    adapter_api = AdapterTheOddsApi(
        chave_api="teste", torneios=TORNEIOS, regioes=["eu"], mercados=["h2h"], buscar_json=api
    )
    motor = MotorDeComparacao(
        estado=EstadoDeMercado(), casas_referencia=["pinnacle"], deteccao=DETECCAO
    )
    canal = CanalEspiao()
    historico = HistoricoSqlite(tmp_path / "h.db")
    repeticao = ControleDeRepeticao(intervalo_segundos=300)
    monitor = MonitorDeSaude(silencio_maximo_segundos=300)
    fontes = [adapter_api, adapter]

    postar(adapter.porta, "/payload", payload_chengdu(), DA_EXTENSAO)
    executar_ciclo(fontes, motor, [canal], repeticao, historico, monitor)
    assert canal.recebidos == []

    # O mercado despenca para Sonego; a pagina da Novibet segue mandando 1.74.
    api.duckworth, api.sonego = 3.60, 1.32
    postar(adapter.porta, "/payload", payload_chengdu(), DA_EXTENSAO)
    executar_ciclo(fontes, motor, [canal], repeticao, historico, monitor)

    assert canal.recebidos, "a Novibet atrasada tinha que alertar"
    alerta = canal.recebidos[0]
    assert (alerta.casa, alerta.selecao, alerta.odd_casa) == ("novibet_br", "sonego", 1.74)
    assert alerta.torneio_id == "atp-chengdu"
    historico.encerrar()


# ---------------------------------------------------------- main.py


def config_com_extensao(ativo, porta=0):
    return Config(
        {
            "torneios": TORNEIOS,
            "fontes": {"extensao": {"ativo": ativo, "casas": ["novibet"], "porta": porta}},
        }
    )


def test_extensao_desligada_nao_monta_nada():
    assert montar_adapters_de_extensao(config_com_extensao(False)) == []


def test_extensao_ligada_monta_um_adapter_por_casa():
    adapters = montar_adapters_de_extensao(config_com_extensao(True, porta=9999))
    assert [(a.nome, a.porta) for a in adapters] == [("extensao:novibet_br", 9999)]


def test_conferencia_da_extensao_avisa_quando_ela_esta_desligada():
    assert conferir_extensao(config_com_extensao(False)) == 2


def test_conferencia_da_extensao_sem_nada_chegando_falha():
    assert conferir_extensao(config_com_extensao(True), tentativas=1, pausa=0) == 1


def test_espera_ate_a_primeira_leva_de_odds():
    class Falso:
        def __init__(self):
            self.chamadas = 0

        def coletar(self):
            self.chamadas += 1
            return [odd(1.74, 0)] if self.chamadas == 3 else []

    pausas = []
    falso = Falso()
    assert aguardar_primeiras_odds(falso, tentativas=5, pausa=2, dormir=pausas.append)
    assert falso.chamadas == 3 and pausas == [2, 2]

    falso = Falso()
    assert aguardar_primeiras_odds(falso, tentativas=2, pausa=2, dormir=pausas.append) == []


# ---------------------------------------------------------- a extensao em si


def test_extensao_nao_pede_permissao_alem_do_endereco_local():
    """Trava da D-018: a extensao so fala com o bot, e so le a Novibet."""
    manifesto = json.loads((PASTA_EXTENSAO / "manifest.json").read_text(encoding="utf-8"))
    assert manifesto["manifest_version"] == 3
    assert not manifesto.get("permissions")
    assert manifesto["host_permissions"] == ["http://127.0.0.1:8765/*"]
    for script in manifesto["content_scripts"]:
        assert all(".novibet.bet.br/" in m or "//novibet.bet.br/" in m for m in script["matches"])


def test_porta_da_extensao_bate_com_a_do_config():
    config = json.loads((RAIZ / "config" / "config.json").read_text(encoding="utf-8"))
    porta = config["fontes"]["extensao"]["porta"]
    fundo = (PASTA_EXTENSAO / "fundo.js").read_text(encoding="utf-8")
    assert f'"http://127.0.0.1:{porta}"' in fundo


def test_filtro_da_extensao_e_o_mesmo_do_parser():
    pagina = (PASTA_EXTENSAO / "pagina.js").read_text(encoding="utf-8")
    filtro = re.search(r'const FILTRO = "([^"]+)"', pagina).group(1)
    assert ParserNovibet().interessa(f"https://www.novibet.bet.br{filtro}x")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js nao instalado")
def test_script_da_pagina_so_copia_e_nao_muda_a_resposta():
    """Roda o pagina.js de verdade, num ambiente de mentira, com o Node."""
    roteiro = PASTA_EXTENSAO.parent / "tests" / "js" / "teste_pagina.js"
    resultado = subprocess.run(
        ["node", str(roteiro)], capture_output=True, text=True, timeout=30
    )
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
