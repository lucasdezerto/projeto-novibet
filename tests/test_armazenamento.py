from datetime import datetime, timezone

from src.armazenamento.sqlite import HistoricoSqlite
from src.config import Config
from src.modelos import Alerta, OddNormalizada

QUANDO = datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc)


def montar_odd(casa="pinnacle", valor=1.45):
    return OddNormalizada(
        casa=casa,
        evento_id_normalizado="sinner-vs-zverev-2026-09-24T09:00",
        mercado="h2h",
        selecao="sinner",
        odd=valor,
        timestamp_coleta=QUANDO,
        timestamp_fonte=QUANDO,
        torneio_id="atp-chengdu",
        evento_descricao="Jannik Sinner x Alexander Zverev",
    )


def montar_alerta(casa="casa_lenta", tipo="atraso"):
    return Alerta(
        tipo=tipo,
        casa=casa,
        evento_id_normalizado="sinner-vs-zverev-2026-09-24T09:00",
        evento_descricao="Jannik Sinner x Alexander Zverev",
        torneio_id="atp-chengdu",
        mercado="h2h",
        selecao="zverev",
        odd_casa=3.60,
        odd_referencia=2.85,
        casa_referencia="pinnacle",
        desvio=0.26,
        segundos_parado=75.0,
        detalhe="teste",
        timestamp=QUANDO,
    )


def test_grava_e_conta_odds(tmp_path):
    historico = HistoricoSqlite(tmp_path / "h.db")
    assert historico.gravar_odds([montar_odd(), montar_odd("betsson", 1.44)]) == 2
    total = historico.conexao.execute("SELECT COUNT(*) FROM odds").fetchone()[0]
    assert total == 2
    historico.encerrar()


def test_gravar_lista_vazia_nao_faz_nada(tmp_path):
    historico = HistoricoSqlite(tmp_path / "h.db")
    assert historico.gravar_odds([]) == 0
    historico.encerrar()


def test_relatorio_agrupa_alertas_por_casa(tmp_path):
    historico = HistoricoSqlite(tmp_path / "h.db")
    historico.gravar_alerta(montar_alerta())
    historico.gravar_alerta(montar_alerta())
    historico.gravar_alerta(montar_alerta("outra_casa", "desvio"))

    resumo = {(linha[0], linha[1]): linha[2] for linha in historico.resumo_por_casa()}
    assert resumo[("casa_lenta", "atraso")] == 2
    assert resumo[("outra_casa", "desvio")] == 1
    historico.encerrar()


def test_banco_e_criado_mesmo_se_a_pasta_nao_existe(tmp_path):
    caminho = tmp_path / "nova" / "pasta" / "h.db"
    historico = HistoricoSqlite(caminho)
    assert caminho.exists()
    historico.encerrar()


def test_reabrir_o_banco_preserva_o_historico(tmp_path):
    caminho = tmp_path / "h.db"
    primeiro = HistoricoSqlite(caminho)
    primeiro.gravar_alerta(montar_alerta())
    primeiro.encerrar()

    segundo = HistoricoSqlite(caminho)
    assert segundo.resumo_por_casa()[0][2] == 1
    segundo.encerrar()


def test_alerta_vira_texto_legivel():
    texto = montar_alerta().texto()
    assert "ODD ATRASADA" in texto
    assert "casa_lenta" in texto
    assert "3.60" in texto


def test_odd_vira_dicionario_com_datas_em_texto():
    dados = montar_odd().para_dicionario()
    assert dados["timestamp_coleta"] == QUANDO.isoformat()
    assert dados["casa"] == "pinnacle"


# ------------------------------------------------------------------- config


def test_config_do_projeto_carrega_e_tem_os_quatro_torneios():
    config = Config.carregar()
    ids = [t["id"] for t in config.torneios]
    assert ids == ["atp-chengdu", "atp-hangzhou", "wta-seoul", "wta-singapore"]
    assert config.deteccao["desvio_minimo"] > 0
    assert "pinnacle" in config.referencia["casas_preferidas"]


def test_config_le_secoes_ausentes_sem_quebrar():
    config = Config({})
    assert config.torneios == []
    assert config.coleta == {}
    assert config.caminho_banco().name == "historico.db"
