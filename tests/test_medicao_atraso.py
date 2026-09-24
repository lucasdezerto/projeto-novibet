"""Testes do relatorio que responde a pergunta do projeto.

"A Novibet atrasa, e quanto?" - medido pelos carimbos `updatedAt` que a fonte
informa, nao por inferencia do bot.
"""

from datetime import datetime, timedelta, timezone

from src.armazenamento.sqlite import HistoricoSqlite
from src.modelos import OddNormalizada

BASE = datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc)


def odd(casa, fonte_em, coleta_em, selecao="sinner", evento="sinner-vs-zverev-2026-09-24T09:00"):
    return OddNormalizada(
        casa=casa,
        evento_id_normalizado=evento,
        mercado="h2h",
        selecao=selecao,
        odd=1.5,
        timestamp_coleta=coleta_em,
        timestamp_fonte=fonte_em,
        torneio_id="atp-chengdu",
        evento_descricao="Sinner x Zverev",
    )


def gravar_ciclos(historico, quantidade, atraso_novibet_s):
    """Cada ciclo: a referencia acabou de mexer, a Novibet mexeu N segundos antes."""
    for i in range(quantidade):
        coleta = BASE + timedelta(seconds=i * 60)
        historico.gravar_odds(
            [
                odd("on_sharp", coleta, coleta),
                odd("novibet_gr", coleta - timedelta(seconds=atraso_novibet_s), coleta),
            ]
        )


def test_mede_o_atraso_de_cada_casa(tmp_path):
    historico = HistoricoSqlite(tmp_path / "h.db")
    gravar_ciclos(historico, quantidade=10, atraso_novibet_s=90)

    resumo = {r["casa"]: r for r in historico.resumo_de_atraso()}
    assert resumo["novibet_gr"]["atraso_mediano_s"] == 90
    assert resumo["on_sharp"]["atraso_mediano_s"] == 0
    assert resumo["novibet_gr"]["amostras"] == 10
    historico.encerrar()


def test_a_casa_mais_atrasada_aparece_primeiro(tmp_path):
    historico = HistoricoSqlite(tmp_path / "h.db")
    gravar_ciclos(historico, quantidade=8, atraso_novibet_s=120)
    assert historico.resumo_de_atraso()[0]["casa"] == "novibet_gr"
    historico.encerrar()


def test_percentual_de_vezes_parada_acima_de_um_minuto(tmp_path):
    historico = HistoricoSqlite(tmp_path / "h.db")
    # 5 ciclos com 90s de atraso, 5 com 10s.
    for i in range(10):
        coleta = BASE + timedelta(seconds=i * 60)
        atraso = 90 if i < 5 else 10
        historico.gravar_odds(
            [odd("on_sharp", coleta, coleta), odd("novibet_gr", coleta - timedelta(seconds=atraso), coleta)]
        )

    resumo = {r["casa"]: r for r in historico.resumo_de_atraso()}
    assert resumo["novibet_gr"]["pct_parada_mais_de_60s"] == 50.0
    assert resumo["novibet_gr"]["atraso_maximo_s"] == 90
    historico.encerrar()


def test_odds_sem_carimbo_da_fonte_sao_ignoradas(tmp_path):
    """A Opcao A e o navegador nao informam updatedAt; nao entram nesta conta."""
    historico = HistoricoSqlite(tmp_path / "h.db")
    historico.gravar_odds([odd("pinnacle", None, BASE), odd("novibet_br", None, BASE)])
    assert historico.resumo_de_atraso() == []
    historico.encerrar()


def test_casa_sozinha_no_mercado_nao_gera_medida(tmp_path):
    """Sem com quem comparar, nao da para dizer que alguem atrasou."""
    historico = HistoricoSqlite(tmp_path / "h.db")
    for i in range(10):
        coleta = BASE + timedelta(seconds=i * 60)
        historico.gravar_odds([odd("novibet_gr", coleta, coleta)])
    assert historico.resumo_de_atraso() == []
    historico.encerrar()


def test_poucas_amostras_nao_viram_conclusao(tmp_path):
    historico = HistoricoSqlite(tmp_path / "h.db")
    gravar_ciclos(historico, quantidade=3, atraso_novibet_s=90)
    assert historico.resumo_de_atraso(minimo_de_amostras=5) == []
    assert historico.resumo_de_atraso(minimo_de_amostras=3)
    historico.encerrar()


def test_cada_selecao_conta_como_amostra_propria(tmp_path):
    historico = HistoricoSqlite(tmp_path / "h.db")
    for i in range(5):
        coleta = BASE + timedelta(seconds=i * 60)
        atrasada = coleta - timedelta(seconds=45)
        for selecao in ("sinner", "zverev"):
            historico.gravar_odds(
                [odd("on_sharp", coleta, coleta, selecao), odd("novibet_gr", atrasada, coleta, selecao)]
            )

    resumo = {r["casa"]: r for r in historico.resumo_de_atraso()}
    assert resumo["novibet_gr"]["amostras"] == 10
    assert resumo["novibet_gr"]["atraso_mediano_s"] == 45
    historico.encerrar()
