from datetime import datetime, timezone

import pytest

from src.normalizador.eventos import (
    arredondar_horario,
    forma_comparavel,
    gerar_id_evento,
    melhor_correspondencia,
    normalizar_nome,
    normalizar_selecao,
    parecidos,
)


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("Jannik Sinner", "sinner"),
        ("Sinner J.", "sinner"),
        ("J. Sinner", "sinner"),
        ("SINNER", "sinner"),
        ("Stefanos Tsitsipas", "tsitsipas"),
        ("Félix Auger-Aliassime", "auger-aliassime"),
        ("Carlos Alcaraz Jr", "alcaraz"),
        ("", ""),
    ],
)
def test_normalizar_nome(entrada, esperado):
    assert normalizar_nome(entrada) == esperado


def test_normalizar_selecao_trata_duplas_sem_depender_da_ordem():
    assert normalizar_selecao("Bopanna/Ebden") == normalizar_selecao("Ebden/Bopanna")
    assert normalizar_selecao("R. Bopanna/M. Ebden") == "bopanna-ebden"


def test_mesmo_jogo_escrito_de_formas_diferentes_gera_o_mesmo_id():
    a = gerar_id_evento("Jannik Sinner", "Alexander Zverev", "2026-09-24T09:00:00Z")
    b = gerar_id_evento("Zverev A.", "Sinner J.", "2026-09-24T09:07:00Z")
    assert a == b


def test_jogos_diferentes_geram_ids_diferentes():
    a = gerar_id_evento("Jannik Sinner", "Alexander Zverev", "2026-09-24T09:00:00Z")
    b = gerar_id_evento("Jannik Sinner", "Carlos Alcaraz", "2026-09-24T09:00:00Z")
    assert a != b


def test_horarios_distantes_nao_viram_o_mesmo_jogo():
    a = gerar_id_evento("Jannik Sinner", "Alexander Zverev", "2026-09-24T09:00:00Z")
    b = gerar_id_evento("Jannik Sinner", "Alexander Zverev", "2026-09-24T11:00:00Z")
    assert a != b


def test_arredondar_horario_encaixa_na_janela_de_15_minutos():
    quando = datetime(2026, 9, 24, 9, 13, 45, tzinfo=timezone.utc)
    assert arredondar_horario(quando).minute == 0
    quando = datetime(2026, 9, 24, 9, 46, 0, tzinfo=timezone.utc)
    assert arredondar_horario(quando).minute == 45


def test_horario_sem_fuso_e_tratado_como_utc():
    com_fuso = gerar_id_evento("A Silva", "B Souza", "2026-09-24T09:00:00Z")
    sem_fuso = gerar_id_evento("A Silva", "B Souza", "2026-09-24T09:00:00")
    assert com_fuso == sem_fuso


def test_comparacao_aproximada():
    assert parecidos("Auger-Aliassime", "Auger Aliassime")
    assert parecidos("Sinner J.", "Jannik Sinner")
    assert not parecidos("Sinner", "Zverev")
    assert melhor_correspondencia("Sinner J.", ["Jannik Sinner", "Carlos Alcaraz"]) == "Jannik Sinner"
    assert melhor_correspondencia("Nadal", ["Jannik Sinner", "Carlos Alcaraz"]) is None


def test_forma_comparavel_ignora_separador_e_ordem():
    assert forma_comparavel("Auger-Aliassime") == forma_comparavel("Auger Aliassime")
    assert forma_comparavel("Bopanna/Ebden") == forma_comparavel("Ebden Bopanna")
    assert forma_comparavel("J. Sinner") == "sinner"
