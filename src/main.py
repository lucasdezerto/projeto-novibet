"""Ponto de entrada do bot.

Uso:
    python -m src.main                 # roda em loop, no intervalo do config
    python -m src.main --uma-vez       # faz uma coleta so e sai
    python -m src.main --diagnostico   # so mostra o que a API cobre, sem coletar odds
    python -m src.main --relatorio     # imprime o resumo do historico ja gravado

O ciclo e sempre o mesmo: coletar -> normalizar -> comparar -> alertar -> gravar.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from src.adapters.the_odds_api import AdapterTheOddsApi, ErroDaApi, SemCreditos
from src.alertas.telegram import montar_alertadores
from src.armazenamento.sqlite import HistoricoSqlite
from src.comparador.estado import ControleDeRepeticao, EstadoDeMercado
from src.comparador.motor import MotorDeComparacao
from src.config import CAMINHO_CONFIG_PADRAO, Config, carregar_env, chave_api_odds, credenciais_telegram
from src.modelos import agora_utc

log = logging.getLogger("bot")

_parar = False


def _pedir_parada(*_args) -> None:
    global _parar
    _parar = True
    log.info("Parada solicitada. Encerrando apos o ciclo atual...")


def configurar_log(verboso: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verboso else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def montar_adapter(config: Config, chave: str) -> AdapterTheOddsApi:
    coleta = config.coleta
    return AdapterTheOddsApi(
        chave_api=chave,
        torneios=config.torneios,
        regioes=coleta.get("regioes", ["eu"]),
        mercados=coleta.get("mercados", ["h2h"]),
        formato_odds=coleta.get("formato_odds", "decimal"),
        parar_com_creditos_restantes=int(coleta.get("parar_com_creditos_restantes", 20)),
    )


def mostrar_diagnostico(config: Config, adapter: AdapterTheOddsApi) -> int:
    """Confere, sem gastar coleta de odds, o que a API cobre do escopo."""
    print("\n=== Cobertura dos torneios do escopo na API agregadora ===")
    try:
        mapa = adapter.resolver_torneios(forcar=True)
    except (ErroDaApi, SemCreditos) as erro:
        print(f"Nao consegui consultar a API: {erro}")
        return 1

    for torneio in config.torneios:
        item = mapa.get(torneio["id"])
        if item:
            esporte = item["esporte"]
            print(f"  [OK]   {torneio['nome']:<24} -> {esporte['key']} ({esporte.get('title')})")
        else:
            print(f"  [FORA] {torneio['nome']:<24} -> nenhuma chave equivalente na API agora")

    print(f"\nCreditos restantes na API: {adapter.creditos_restantes}")
    custo = len(mapa) * len(adapter.regioes) * len(adapter.mercados)
    intervalo = int(config.coleta.get("intervalo_segundos", 120))
    print(f"Custo por ciclo de coleta: {custo} creditos")
    if custo and adapter.creditos_restantes:
        ciclos = adapter.creditos_restantes // custo
        print(
            f"Com o saldo atual da para ~{ciclos} ciclos "
            f"(~{ciclos * intervalo / 3600:.1f} horas no intervalo de {intervalo}s)."
        )
    return 0


def mostrar_relatorio(config: Config) -> int:
    historico = HistoricoSqlite(config.caminho_banco())
    linhas = historico.resumo_por_casa()
    historico.encerrar()
    if not linhas:
        print("Ainda nao ha alertas gravados no historico.")
        return 0
    print(f"\n{'CASA':<22}{'TIPO':<10}{'ALERTAS':>9}{'DESVIO MEDIO':>15}{'PARADA MEDIA':>15}")
    for casa, tipo, quantidade, desvio, parado in linhas:
        print(f"{casa:<22}{tipo:<10}{quantidade:>9}{desvio:>14}%{parado:>14}s")
    return 0


def executar_ciclo(adapter, motor, canais, repeticao, historico) -> int:
    """Um ciclo completo. Devolve quantos alertas foram disparados."""
    agora = agora_utc()
    odds = adapter.coletar()
    if not odds:
        log.info("Nenhuma odd coletada neste ciclo.")
        return 0

    eventos = len({o.evento_id_normalizado for o in odds})
    casas = len({o.casa for o in odds})
    log.info(
        "Coletadas %d odds | %d jogos | %d casas | creditos restantes: %s",
        len(odds), eventos, casas, adapter.creditos_restantes,
    )

    if historico:
        historico.gravar_odds(odds)

    alertas = motor.avaliar(odds, agora=agora)
    enviados = 0
    for alerta in alertas:
        if not repeticao.pode_enviar(alerta.chave_deduplicacao, agora):
            continue
        repeticao.registrar(alerta.chave_deduplicacao, agora)
        if historico:
            historico.gravar_alerta(alerta)
        for canal in canais:
            canal.enviar(alerta)
        enviados += 1

    if alertas and not enviados:
        log.debug("%d alertas suprimidos por repeticao.", len(alertas))
    return enviados


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description="Bot de deteccao de odds atrasadas")
    analisador.add_argument("--config", default=str(CAMINHO_CONFIG_PADRAO))
    analisador.add_argument("--uma-vez", action="store_true", help="faz uma coleta so e sai")
    analisador.add_argument(
        "--diagnostico", action="store_true", help="mostra a cobertura da API e o custo em creditos"
    )
    analisador.add_argument(
        "--relatorio", action="store_true", help="imprime o resumo do historico gravado"
    )
    analisador.add_argument("--verboso", action="store_true")
    argumentos = analisador.parse_args(argv)

    configurar_log(argumentos.verboso)
    carregar_env()
    config = Config.carregar(argumentos.config)

    if argumentos.relatorio:
        return mostrar_relatorio(config)

    chave = chave_api_odds()
    if not chave:
        print(
            "Falta a chave da API agregadora.\n"
            "1. Pegue uma chave gratuita em https://the-odds-api.com\n"
            "2. Copie .env.example para .env\n"
            "3. Preencha ODDS_API_KEY=sua_chave",
            file=sys.stderr,
        )
        return 2

    adapter = montar_adapter(config, chave)

    if argumentos.diagnostico:
        return mostrar_diagnostico(config, adapter)

    estado = EstadoDeMercado()
    motor = MotorDeComparacao(
        estado=estado,
        casas_referencia=config.referencia.get("casas_preferidas", ["pinnacle"]),
        deteccao=config.deteccao,
        casas_incluir=config.casas_monitoradas.get("incluir"),
        casas_excluir=config.casas_monitoradas.get("excluir"),
        remover_margem=bool(config.referencia.get("remover_margem", True)),
    )
    token, chat_id = credenciais_telegram()
    canais = montar_alertadores(config.alertas, token, chat_id)
    repeticao = ControleDeRepeticao(
        int(config.alertas.get("repetir_mesmo_alerta_apos_segundos", 300))
    )
    historico = HistoricoSqlite(config.caminho_banco())

    signal.signal(signal.SIGINT, _pedir_parada)
    signal.signal(signal.SIGTERM, _pedir_parada)

    intervalo = int(config.coleta.get("intervalo_segundos", 120))
    limite_creditos = int(config.coleta.get("limite_creditos_por_execucao", 400))
    creditos_iniciais = None
    total_alertas = 0

    try:
        fora = adapter.torneios_sem_chave
        if fora:
            log.warning(
                "Fora da cobertura da API (nenhuma odd sera coletada para eles): %s",
                ", ".join(fora),
            )

        while True:
            try:
                total_alertas += executar_ciclo(adapter, motor, canais, repeticao, historico)
            except SemCreditos as erro:
                log.error("Parando: %s", erro)
                break
            except ErroDaApi as erro:
                log.error("Erro na API neste ciclo (vou tentar de novo): %s", erro)

            if creditos_iniciais is None:
                creditos_iniciais = adapter.creditos_usados
            elif adapter.creditos_usados is not None:
                gastos = adapter.creditos_usados - creditos_iniciais
                if gastos >= limite_creditos:
                    log.error(
                        "Parando: limite de %d creditos por execucao atingido.", limite_creditos
                    )
                    break

            if argumentos.uma_vez or _parar:
                break
            time.sleep(intervalo)
    finally:
        adapter.encerrar()
        historico.encerrar()

    log.info("Encerrado. Alertas disparados nesta execucao: %d", total_alertas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
