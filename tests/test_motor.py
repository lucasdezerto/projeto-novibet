from datetime import datetime, timedelta, timezone

from src.comparador.estado import ControleDeRepeticao, EstadoDeMercado
from src.comparador.motor import MotorDeComparacao, calcular_precos_justos
from src.modelos import OddNormalizada

INICIO = datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc)

DETECCAO = {
    "desvio_minimo": 0.04,
    "duracao_minima_segundos": 20,
    "movimento_referencia_minimo": 0.03,
    "atraso_maximo_segundos": 60,
    "odd_minima": 1.2,
    "odd_maxima": 15.0,
}


def odd(casa, selecao, valor, quando, evento="sinner-vs-zverev-2026-09-24T09:00"):
    return OddNormalizada(
        casa=casa,
        evento_id_normalizado=evento,
        mercado="h2h",
        selecao=selecao,
        odd=valor,
        timestamp_coleta=quando,
        torneio_id="atp-chengdu",
        evento_descricao="Jannik Sinner x Alexander Zverev",
    )


def montar_motor(**extras):
    parametros = {
        "estado": EstadoDeMercado(),
        "casas_referencia": ["pinnacle"],
        "deteccao": DETECCAO,
    }
    parametros.update(extras)
    return MotorDeComparacao(**parametros)


# ---------------------------------------------------------------- preco justo


def test_preco_justo_remove_a_margem_da_casa():
    justos = calcular_precos_justos({"a": 1.80, "b": 2.10})
    # Sem margem, as probabilidades tem que somar exatamente 1.
    assert abs(sum(1 / o for o in justos.values()) - 1.0) < 1e-9
    # E as odds justas ficam maiores que as oferecidas.
    assert justos["a"] > 1.80 and justos["b"] > 2.10


def test_preco_justo_com_dados_invalidos_nao_quebra():
    assert calcular_precos_justos({}) == {}
    assert calcular_precos_justos({"a": 0.0, "b": 1.0}) == {}


# ---------------------------------------------------------------- regra desvio


def test_odd_alinhada_com_a_referencia_nao_gera_alerta():
    motor = montar_motor()
    odds = [
        odd("pinnacle", "sinner", 1.45, INICIO),
        odd("pinnacle", "zverev", 2.85, INICIO),
        odd("outra", "sinner", 1.44, INICIO),
        odd("outra", "zverev", 2.80, INICIO),
    ]
    assert motor.avaliar(odds, agora=INICIO) == []


def test_desvio_so_alerta_depois_de_se_sustentar():
    motor = montar_motor()
    referencia = [odd("pinnacle", "sinner", 1.45, INICIO), odd("pinnacle", "zverev", 2.85, INICIO)]
    atrasada = [odd("casa_lenta", "sinner", 1.42, INICIO), odd("casa_lenta", "zverev", 3.60, INICIO)]

    # Primeiro ciclo: o desvio acabou de aparecer, ainda nao alerta.
    assert motor.avaliar(referencia + atrasada, agora=INICIO) == []

    # 25 segundos depois, o desvio continua -> alerta.
    depois = INICIO + timedelta(seconds=25)
    alertas = motor.avaliar(
        [
            odd("pinnacle", "sinner", 1.45, depois),
            odd("pinnacle", "zverev", 2.85, depois),
            odd("casa_lenta", "sinner", 1.42, depois),
            odd("casa_lenta", "zverev", 3.60, depois),
        ],
        agora=depois,
    )
    assert len(alertas) == 1
    alerta = alertas[0]
    assert alerta.tipo == "desvio"
    assert alerta.casa == "casa_lenta"
    assert alerta.selecao == "zverev"
    assert alerta.desvio > 0.04


def test_desvio_que_some_antes_do_prazo_nao_alerta():
    motor = montar_motor()
    motor.avaliar(
        [
            odd("pinnacle", "sinner", 1.45, INICIO),
            odd("pinnacle", "zverev", 2.85, INICIO),
            odd("casa_lenta", "sinner", 1.42, INICIO),
            odd("casa_lenta", "zverev", 3.60, INICIO),
        ],
        agora=INICIO,
    )
    depois = INICIO + timedelta(seconds=25)
    # A casa corrigiu a odd: nao deve alertar, e o relogio do desvio zera.
    alertas = motor.avaliar(
        [
            odd("pinnacle", "sinner", 1.45, depois),
            odd("pinnacle", "zverev", 2.85, depois),
            odd("casa_lenta", "sinner", 1.45, depois),
            odd("casa_lenta", "zverev", 2.84, depois),
        ],
        agora=depois,
    )
    assert alertas == []


def test_odd_abaixo_da_referencia_nunca_alerta():
    """Odd pior que o mercado nao e oportunidade, e so uma casa cara."""
    motor = montar_motor()
    for segundos in (0, 25, 60):
        quando = INICIO + timedelta(seconds=segundos)
        alertas = motor.avaliar(
            [
                odd("pinnacle", "sinner", 1.45, quando),
                odd("pinnacle", "zverev", 2.85, quando),
                odd("casa_cara", "sinner", 1.30, quando),
                odd("casa_cara", "zverev", 2.40, quando),
            ],
            agora=quando,
        )
        assert alertas == []


def test_odds_fora_da_faixa_configurada_sao_ignoradas():
    motor = montar_motor()
    for segundos in (0, 30):
        quando = INICIO + timedelta(seconds=segundos)
        alertas = motor.avaliar(
            [
                odd("pinnacle", "zebra", 20.0, quando),
                odd("pinnacle", "favorito", 1.05, quando),
                odd("casa_lenta", "zebra", 30.0, quando),
                odd("casa_lenta", "favorito", 1.06, quando),
            ],
            agora=quando,
        )
        assert alertas == []


# ---------------------------------------------------------------- regra atraso


def test_casa_parada_depois_da_referencia_mexer_gera_alerta_de_atraso():
    motor = montar_motor()
    motor.avaliar(
        [
            odd("pinnacle", "sinner", 1.45, INICIO),
            odd("pinnacle", "zverev", 2.85, INICIO),
            odd("casa_lenta", "sinner", 1.45, INICIO),
            odd("casa_lenta", "zverev", 2.84, INICIO),
        ],
        agora=INICIO,
    )

    # A referencia despenca (algo aconteceu no jogo); a casa lenta nao mexe.
    movimento = INICIO + timedelta(seconds=10)
    motor.avaliar(
        [
            odd("pinnacle", "sinner", 1.20, movimento),
            odd("pinnacle", "zverev", 4.50, movimento),
            odd("casa_lenta", "sinner", 1.45, movimento),
            odd("casa_lenta", "zverev", 2.84, movimento),
        ],
        agora=movimento,
    )

    # 70 segundos depois do movimento a casa continua parada -> atraso.
    depois = movimento + timedelta(seconds=70)
    alertas = motor.avaliar(
        [
            odd("pinnacle", "sinner", 1.20, depois),
            odd("pinnacle", "zverev", 4.50, depois),
            odd("casa_lenta", "sinner", 1.45, depois),
            odd("casa_lenta", "zverev", 2.84, depois),
        ],
        agora=depois,
    )
    tipos = {a.tipo for a in alertas}
    assert "atraso" in tipos
    atraso = next(a for a in alertas if a.tipo == "atraso")
    assert atraso.casa == "casa_lenta"
    assert atraso.segundos_parado >= 60
    assert "nao acompanhou" in atraso.detalhe


def test_casa_que_acompanhou_a_referencia_nao_gera_atraso():
    motor = montar_motor()
    motor.avaliar(
        [
            odd("pinnacle", "sinner", 1.45, INICIO),
            odd("pinnacle", "zverev", 2.85, INICIO),
            odd("casa_rapida", "sinner", 1.45, INICIO),
            odd("casa_rapida", "zverev", 2.84, INICIO),
        ],
        agora=INICIO,
    )
    movimento = INICIO + timedelta(seconds=10)
    motor.avaliar(
        [
            odd("pinnacle", "sinner", 1.20, movimento),
            odd("pinnacle", "zverev", 4.50, movimento),
            odd("casa_rapida", "sinner", 1.21, movimento),
            odd("casa_rapida", "zverev", 4.40, movimento),
        ],
        agora=movimento,
    )
    depois = movimento + timedelta(seconds=90)
    alertas = motor.avaliar(
        [
            odd("pinnacle", "sinner", 1.20, depois),
            odd("pinnacle", "zverev", 4.50, depois),
            odd("casa_rapida", "sinner", 1.21, depois),
            odd("casa_rapida", "zverev", 4.40, depois),
        ],
        agora=depois,
    )
    assert [a for a in alertas if a.tipo == "atraso"] == []


def test_casa_que_mexeu_antes_da_referencia_ainda_conta_como_atrasada():
    """Mexer em algum momento no passado nao e o mesmo que acompanhar."""
    motor = montar_motor()
    motor.avaliar(
        [
            odd("pinnacle", "sinner", 1.45, INICIO),
            odd("pinnacle", "zverev", 2.85, INICIO),
            odd("casa_lenta", "sinner", 1.45, INICIO),
            odd("casa_lenta", "zverev", 2.84, INICIO),
        ],
        agora=INICIO,
    )
    # A casa mexe sozinha, antes de a referencia mexer.
    mexida_da_casa = INICIO + timedelta(seconds=5)
    motor.avaliar(
        [
            odd("pinnacle", "sinner", 1.45, mexida_da_casa),
            odd("pinnacle", "zverev", 2.85, mexida_da_casa),
            odd("casa_lenta", "sinner", 1.46, mexida_da_casa),
            odd("casa_lenta", "zverev", 2.83, mexida_da_casa),
        ],
        agora=mexida_da_casa,
    )
    movimento = INICIO + timedelta(seconds=10)
    motor.avaliar(
        [
            odd("pinnacle", "sinner", 1.20, movimento),
            odd("pinnacle", "zverev", 4.50, movimento),
            odd("casa_lenta", "sinner", 1.46, movimento),
            odd("casa_lenta", "zverev", 2.83, movimento),
        ],
        agora=movimento,
    )
    depois = movimento + timedelta(seconds=70)
    alertas = motor.avaliar(
        [
            odd("pinnacle", "sinner", 1.20, depois),
            odd("pinnacle", "zverev", 4.50, depois),
            odd("casa_lenta", "sinner", 1.46, depois),
            odd("casa_lenta", "zverev", 2.83, depois),
        ],
        agora=depois,
    )
    assert any(a.tipo == "atraso" for a in alertas)


# ---------------------------------------------------------------- filtros


def test_sem_casa_de_referencia_o_mercado_e_ignorado():
    motor = montar_motor()
    alertas = motor.avaliar(
        [odd("casa_a", "sinner", 1.45, INICIO), odd("casa_b", "zverev", 3.60, INICIO)],
        agora=INICIO,
    )
    assert alertas == []
    assert motor.mercados_sem_referencia


def test_lista_de_exclusao_silencia_a_casa():
    motor = montar_motor(casas_excluir=["casa_lenta"])
    for segundos in (0, 30):
        quando = INICIO + timedelta(seconds=segundos)
        alertas = motor.avaliar(
            [
                odd("pinnacle", "sinner", 1.45, quando),
                odd("pinnacle", "zverev", 2.85, quando),
                odd("casa_lenta", "sinner", 1.42, quando),
                odd("casa_lenta", "zverev", 3.60, quando),
            ],
            agora=quando,
        )
        assert alertas == []


def test_lista_de_inclusao_monitora_so_quem_esta_nela():
    motor = montar_motor(casas_incluir=["outra_casa"])
    for segundos in (0, 30):
        quando = INICIO + timedelta(seconds=segundos)
        alertas = motor.avaliar(
            [
                odd("pinnacle", "sinner", 1.45, quando),
                odd("pinnacle", "zverev", 2.85, quando),
                odd("casa_lenta", "sinner", 1.42, quando),
                odd("casa_lenta", "zverev", 3.60, quando),
            ],
            agora=quando,
        )
        assert alertas == []


def test_a_referencia_nunca_e_alertada_contra_ela_mesma():
    motor = montar_motor()
    for segundos in (0, 30):
        quando = INICIO + timedelta(seconds=segundos)
        alertas = motor.avaliar(
            [odd("pinnacle", "sinner", 1.45, quando), odd("pinnacle", "zverev", 2.85, quando)],
            agora=quando,
        )
        assert alertas == []


# ---------------------------------------------------------------- repeticao


def test_controle_de_repeticao_segura_o_mesmo_alerta():
    controle = ControleDeRepeticao(intervalo_segundos=300)
    assert controle.pode_enviar("x", INICIO)
    controle.registrar("x", INICIO)
    assert not controle.pode_enviar("x", INICIO + timedelta(seconds=299))
    assert controle.pode_enviar("x", INICIO + timedelta(seconds=300))


def test_controle_de_repeticao_nao_cresce_para_sempre():
    controle = ControleDeRepeticao(intervalo_segundos=300)
    controle.registrar("jogo_de_ontem", INICIO)
    assert len(controle) == 1
    controle.registrar("jogo_de_hoje", INICIO + timedelta(hours=5))
    assert len(controle) == 1, "o alerta antigo tinha que ter sido descartado"


def test_motor_esquece_desvios_de_jogos_ja_encerrados():
    motor = montar_motor()
    motor.avaliar(
        [
            odd("pinnacle", "sinner", 1.45, INICIO),
            odd("pinnacle", "zverev", 2.85, INICIO),
            odd("casa_lenta", "sinner", 1.42, INICIO),
            odd("casa_lenta", "zverev", 3.60, INICIO),
        ],
        agora=INICIO,
    )
    assert motor._desviado_desde, "o desvio tinha que estar sendo cronometrado"

    # Sete horas depois o jogo ja acabou e nada mais chega dele.
    motor.avaliar([], agora=INICIO + timedelta(hours=7))
    assert motor._desviado_desde == {}


def test_estado_marca_quando_a_odd_mudou():
    estado = EstadoDeMercado()
    estado.atualizar(odd("casa", "sinner", 1.50, INICIO))
    depois = INICIO + timedelta(seconds=30)
    registro = estado.atualizar(odd("casa", "sinner", 1.50, depois))
    # Odd igual: o relogio de "parado" continua correndo.
    assert registro.segundos_parado(depois) == 30

    mudanca = INICIO + timedelta(seconds=60)
    registro = estado.atualizar(odd("casa", "sinner", 1.60, mudanca))
    assert registro.segundos_parado(mudanca) == 0
    assert abs(registro.variacao - (0.10 / 1.50)) < 1e-9


def test_estado_descarta_precos_de_jogos_antigos():
    estado = EstadoDeMercado()
    estado.atualizar(odd("casa", "sinner", 1.50, INICIO))
    assert len(estado) == 1
    estado.limpar_antigos(INICIO + timedelta(hours=7), segundos=6 * 3600)
    assert len(estado) == 0
