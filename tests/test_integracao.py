"""Teste de ponta a ponta do ciclo do bot, sem tocar a internet.

Monta o mesmo encadeamento que o main.py monta (coletar -> comparar ->
alertar -> gravar) e confere que uma casa atrasada de verdade produz alerta,
que o alerta chega no canal e que fica gravado no historico.
"""

from datetime import datetime, timedelta, timezone

from src.adapters.the_odds_api import AdapterTheOddsApi
from src.armazenamento.sqlite import HistoricoSqlite
from src.comparador.estado import ControleDeRepeticao, EstadoDeMercado
from src.comparador.motor import MotorDeComparacao
from src.main import executar_ciclo
from src.modelos import Alerta

TORNEIOS = [
    {"id": "atp-chengdu", "nome": "ATP Chengdu (CHN)", "circuito": "ATP",
     "chaves_api": ["tennis_atp_chengdu_open"], "termos_nome": ["chengdu"]}
]

ESPORTES = [
    {"key": "tennis_atp_chengdu_open", "group": "Tennis", "title": "ATP Chengdu Open"}
]


def payload(odd_lenta):
    """Um jogo com a referencia e uma casa cuja odd a gente controla."""
    return [
        {
            "commence_time": "2026-09-24T09:00:00Z",
            "home_team": "Jannik Sinner",
            "away_team": "Alexander Zverev",
            "bookmakers": [
                {
                    "key": "pinnacle",
                    "last_update": "2026-09-24T09:00:00Z",
                    "markets": [{"key": "h2h", "outcomes": [
                        {"name": "Jannik Sinner", "price": 1.45},
                        {"name": "Alexander Zverev", "price": 2.85},
                    ]}],
                },
                {
                    "key": "casa_lenta",
                    "last_update": "2026-09-24T09:00:00Z",
                    "markets": [{"key": "h2h", "outcomes": [
                        {"name": "Sinner J.", "price": 1.42},
                        {"name": "Zverev A.", "price": odd_lenta},
                    ]}],
                },
            ],
        }
    ]


class BuscaControlada:
    def __init__(self):
        self.odd_lenta = 2.84

    def __call__(self, url, tempo_limite=20):
        cabecalhos = {"x-requests-remaining": "400", "x-requests-used": "100"}
        if "/sports/?" in url:
            return ESPORTES, cabecalhos
        return payload(self.odd_lenta), cabecalhos


class CanalEspiao:
    def __init__(self):
        self.recebidos: list[Alerta] = []

    def enviar(self, alerta):
        self.recebidos.append(alerta)
        return True


def montar(tmp_path):
    busca = BuscaControlada()
    adapter = AdapterTheOddsApi(
        chave_api="teste", torneios=TORNEIOS, regioes=["eu"], mercados=["h2h"],
        buscar_json=busca,
    )
    motor = MotorDeComparacao(
        estado=EstadoDeMercado(),
        casas_referencia=["pinnacle"],
        deteccao={
            "desvio_minimo": 0.04,
            # Zero de propÃ³sito: aqui os ciclos rodam em milissegundos, entao
            # nenhuma espera de verdade passaria. As regras de tempo estao
            # cobertas no test_motor.py, que injeta o relogio. O que este
            # arquivo testa e o encadeamento das pecas.
            "duracao_minima_segundos": 0,
            "movimento_referencia_minimo": 0.03,
            "atraso_maximo_segundos": 60,
            "odd_minima": 1.2,
            "odd_maxima": 15.0,
        },
    )
    canal = CanalEspiao()
    historico = HistoricoSqlite(tmp_path / "h.db")
    repeticao = ControleDeRepeticao(intervalo_segundos=300)
    return busca, adapter, motor, canal, historico, repeticao


def test_ciclo_completo_com_odds_alinhadas_nao_alerta_mas_grava(tmp_path):
    busca, adapter, motor, canal, historico, repeticao = montar(tmp_path)
    enviados = executar_ciclo([adapter], motor, [canal], repeticao, historico)

    assert enviados == 0
    assert canal.recebidos == []
    gravadas = historico.conexao.execute("SELECT COUNT(*) FROM odds").fetchone()[0]
    assert gravadas == 4, "as 4 odds coletadas tinham que ir para o historico"
    historico.encerrar()


def test_ciclo_completo_detecta_casa_atrasada_alerta_e_grava(tmp_path):
    busca, adapter, motor, canal, historico, repeticao = montar(tmp_path)

    # Ciclo 1: tudo alinhado.
    executar_ciclo([adapter], motor, [canal], repeticao, historico)
    assert canal.recebidos == []

    # A casa lenta trava numa odd muito acima do preco justo.
    busca.odd_lenta = 3.60
    executar_ciclo([adapter], motor, [canal], repeticao, historico)
    executar_ciclo([adapter], motor, [canal], repeticao, historico)

    assert canal.recebidos, "a casa parada acima do preco justo tinha que alertar"
    alerta = canal.recebidos[0]
    assert alerta.casa == "casa_lenta"
    assert alerta.casa_referencia == "pinnacle"
    assert alerta.selecao == "zverev"
    assert alerta.torneio_id == "atp-chengdu"
    assert alerta.desvio > 0.04

    gravados = historico.conexao.execute(
        "SELECT casa, tipo FROM alertas"
    ).fetchall()
    assert ("casa_lenta", alerta.tipo) in gravados
    historico.encerrar()


def test_alerta_repetido_nao_e_reenviado_no_ciclo_seguinte(tmp_path):
    busca, adapter, motor, canal, historico, repeticao = montar(tmp_path)
    executar_ciclo([adapter], motor, [canal], repeticao, historico)
    busca.odd_lenta = 3.60
    for _ in range(4):
        executar_ciclo([adapter], motor, [canal], repeticao, historico)

    chaves = {a.chave_deduplicacao for a in canal.recebidos}
    assert len(canal.recebidos) == len(chaves), "o mesmo alerta saiu mais de uma vez"
    historico.encerrar()


def test_ciclo_sem_odds_nao_quebra(tmp_path):
    _, adapter, motor, canal, historico, repeticao = montar(tmp_path)
    adapter._buscar_json = lambda url, tempo_limite=20: (
        (ESPORTES, {}) if "/sports/?" in url else ([], {})
    )
    adapter._mapa_torneios = None
    assert executar_ciclo([adapter], motor, [canal], repeticao, historico) == 0
    historico.encerrar()

