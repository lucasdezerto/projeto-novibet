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

from src.adapters.casas.base import CasaBloqueada
from src.adapters.casas.bet365 import ParserBet365
from src.adapters.casas.novibet import ParserNovibet
from src.adapters.monitor import MonitorDeSaude
from src.adapters.navegador import AdapterNavegador, PlaywrightAusente
from src.adapters.the_odds_api import AdapterTheOddsApi, ErroDaApi, SemCreditos
from src.alertas.telegram import montar_alertadores
from src.armazenamento.sqlite import HistoricoSqlite
from src.comparador.estado import ControleDeRepeticao, EstadoDeMercado
from src.comparador.motor import MotorDeComparacao
from src.config import CAMINHO_CONFIG_PADRAO, Config, carregar_env, chave_api_odds, credenciais_telegram
from src.modelos import agora_utc

PARSERS_DISPONIVEIS = {"novibet": ParserNovibet, "bet365": ParserBet365}

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


def montar_adapters_de_navegador(config: Config) -> list[AdapterNavegador]:
    """Monta um adapter da Opcao B por casa ligada no config."""
    navegador = config.fontes.get("navegador", {})
    if not navegador.get("ativo"):
        return []

    perfil = config.caminho_perfil_navegador()
    if perfil:
        perfil.mkdir(parents=True, exist_ok=True)

    adapters = []
    for apelido in navegador.get("casas", []):
        classe = PARSERS_DISPONIVEIS.get(apelido)
        if classe is None:
            log.error("Casa desconhecida no config: %s", apelido)
            continue
        adapters.append(
            AdapterNavegador(
                parser=classe(),
                torneios=config.torneios,
                pasta_perfil=str(perfil) if perfil else None,
                sem_janela=bool(navegador.get("sem_janela", True)),
                segundos_por_ciclo=float(navegador.get("segundos_por_ciclo", 6)),
            )
        )
    return adapters


def preparar_navegador(config: Config) -> int:
    """Abre uma janela de navegador para voce preparar o perfil na mao.

    A Novibet roda verificacao anti-bot da Cloudflare e tem portao de idade.
    O bot **nao** resolve nem contorna nada disso - isso seria quebrar a regra
    do projeto. Quem passa pelas telas e voce, uma vez, nesta janela. O que
    ficar salvo no perfil o bot reaproveita depois.

    Se as telas nao passarem, a resposta certa e desistir da Opcao B para esta
    casa, nao procurar disfarce para o navegador.
    """
    perfil = config.caminho_perfil_navegador()
    if not perfil:
        print("Falta 'pasta_perfil' em fontes.navegador no config.json.", file=sys.stderr)
        return 2
    perfil.mkdir(parents=True, exist_ok=True)

    adapters = montar_adapters_de_navegador(config)
    if not adapters:
        print("Nenhuma casa ligada em fontes.navegador no config.json.", file=sys.stderr)
        return 2

    print(
        "\n=== Preparacao do navegador ===\n"
        f"Perfil: {perfil}\n\n"
        "Vou abrir uma janela em cada pagina de torneio. Na janela:\n"
        "  1. Espere a verificacao de seguranca terminar, se aparecer.\n"
        "  2. Responda ao banner de cookies.\n"
        "  3. Confirme o portao de idade, se ele aparecer.\n"
        "  4. Confira que as odds aparecem na tela.\n\n"
        "Feito isso, volte aqui e aperte Enter. O bot reaproveita esta sessao.\n"
        "Aviso: automatizar acesso costuma contrariar os termos de uso da casa.\n"
        "Leia a secao 6 de docs/projeto.md antes de deixar isso rodando.\n"
    )

    adapter = adapters[0]
    adapter.sem_janela = False
    try:
        adapter.iniciar()
        input("Aperte Enter quando as odds estiverem visiveis na janela... ")
        odds = adapter.coletar()
        if odds:
            print(f"\nFuncionou: {len(odds)} odds interceptadas. Pode rodar o bot normalmente.")
            return 0
        print(
            "\nNenhuma odd foi interceptada. A casa provavelmente segue bloqueando.\n"
            "Desligue esta casa em fontes.navegador no config.json."
        )
        return 1
    except CasaBloqueada as erro:
        print(f"\n{erro}", file=sys.stderr)
        return 1
    except PlaywrightAusente as erro:
        print(f"\n{erro}", file=sys.stderr)
        return 2
    finally:
        adapter.encerrar()


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


def coletar_de_todas_as_fontes(adapters, monitor, agora) -> list:
    """Junta num unico lote as odds de todas as fontes ligadas.

    E aqui que a Opcao A e a Opcao B se encontram: como as duas produzem o
    mesmo schema e o mesmo id de evento, o motor compara a casa brasileira
    contra a referencia de mercado sem saber de onde cada preco veio.

    Um erro numa fonte nao pode derrubar as outras: o objetivo do bot e
    justamente comparar, e comparar com uma fonte a menos ainda vale.
    """
    odds = []
    for adapter in adapters:
        try:
            coletadas = adapter.coletar()
        except SemCreditos:
            raise
        except CasaBloqueada as erro:
            log.error("Fonte %s bloqueada: %s", adapter.nome, erro)
            coletadas = []
        except (ErroDaApi, PlaywrightAusente) as erro:
            log.error("Fonte %s falhou neste ciclo: %s", adapter.nome, erro)
            coletadas = []
        except Exception as erro:  # noqa: BLE001 - uma fonte nao derruba o bot
            log.exception("Erro inesperado na fonte %s: %s", adapter.nome, erro)
            coletadas = []

        if monitor:
            monitor.registrar(adapter.nome, len(coletadas), agora)
        odds.extend(coletadas)
    return odds


def executar_ciclo(adapters, motor, canais, repeticao, historico, monitor=None) -> int:
    """Um ciclo completo. Devolve quantos alertas foram disparados."""
    agora = agora_utc()
    odds = coletar_de_todas_as_fontes(adapters, monitor, agora)

    if monitor:
        for nome, motivo in monitor.fontes_em_silencio(agora):
            log.error("MONITOR DE SAUDE: a fonte %s esta %s.", nome, motivo)

    if not odds:
        log.info("Nenhuma odd coletada neste ciclo.")
        return 0

    eventos = len({o.evento_id_normalizado for o in odds})
    casas = sorted({o.casa for o in odds})
    log.info(
        "Coletadas %d odds | %d jogos | %d casas (%s)",
        len(odds), eventos, len(casas), ", ".join(casas[:6]),
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
    analisador.add_argument(
        "--preparar-navegador",
        action="store_true",
        help="abre uma janela para voce passar pelas telas da casa uma vez (Opcao B)",
    )
    analisador.add_argument("--verboso", action="store_true")
    argumentos = analisador.parse_args(argv)

    configurar_log(argumentos.verboso)
    carregar_env()
    config = Config.carregar(argumentos.config)

    if argumentos.relatorio:
        return mostrar_relatorio(config)

    if argumentos.preparar_navegador:
        return preparar_navegador(config)

    usa_api = bool(config.fontes.get("api_agregadora", {}).get("ativo", True))
    adapter_api = None

    if usa_api:
        chave = chave_api_odds()
        if not chave:
            print(
                "Falta a chave da API agregadora.\n"
                "1. Pegue uma chave gratuita em https://the-odds-api.com\n"
                "2. Copie .env.example para .env\n"
                "3. Preencha ODDS_API_KEY=sua_chave\n"
                "\n"
                "Se quiser rodar so com a Opcao B (site da casa), desligue a fonte\n"
                "'api_agregadora' no config.json. Sem ela o bot perde a referencia\n"
                "de mercado e so consegue comparar as casas entre si.",
                file=sys.stderr,
            )
            return 2
        adapter_api = montar_adapter(config, chave)

    if argumentos.diagnostico:
        if adapter_api is None:
            print("A API agregadora esta desligada no config; nada a diagnosticar.")
            return 0
        return mostrar_diagnostico(config, adapter_api)

    adapters = ([adapter_api] if adapter_api else []) + montar_adapters_de_navegador(config)
    if not adapters:
        print("Nenhuma fonte de odds ligada no config.json.", file=sys.stderr)
        return 2

    monitor = MonitorDeSaude(
        float(config.fontes.get("navegador", {}).get("silencio_maximo_segundos", 300))
    )

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

    log.info("Fontes ligadas: %s", ", ".join(a.nome for a in adapters))

    try:
        if adapter_api is not None:
            fora = adapter_api.torneios_sem_chave
            if fora:
                log.warning(
                    "Fora da cobertura da API (nenhuma odd sera coletada para eles): %s",
                    ", ".join(fora),
                )

        while True:
            try:
                total_alertas += executar_ciclo(
                    adapters, motor, canais, repeticao, historico, monitor
                )
            except SemCreditos as erro:
                log.error("Parando: %s", erro)
                break
            except ErroDaApi as erro:
                log.error("Erro na API neste ciclo (vou tentar de novo): %s", erro)

            if adapter_api is not None:
                if creditos_iniciais is None:
                    creditos_iniciais = adapter_api.creditos_usados
                elif adapter_api.creditos_usados is not None:
                    gastos = adapter_api.creditos_usados - creditos_iniciais
                    if gastos >= limite_creditos:
                        log.error(
                            "Parando: limite de %d creditos por execucao atingido.",
                            limite_creditos,
                        )
                        break

            if argumentos.uma_vez or _parar:
                break
            time.sleep(intervalo)
    finally:
        for adapter in adapters:
            try:
                adapter.encerrar()
            except Exception as erro:  # noqa: BLE001 - encerramento nao pode falhar
                log.debug("Erro ao encerrar %s: %s", adapter.nome, erro)
        historico.encerrar()
        if monitor:
            for linha in monitor.resumo():
                log.info("Saude final | %s", linha)

    log.info("Encerrado. Alertas disparados nesta execucao: %d", total_alertas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
