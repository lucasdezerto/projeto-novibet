"""Opcao B: interceptador de trafego num navegador de verdade.

Abre a pagina da casa num Chromium controlado pelo Playwright e escuta o que
a propria pagina recebe - tanto respostas HTTP quanto quadros de WebSocket.
As paginas ficam abertas entre os ciclos, entao o bot le as atualizacoes no
ritmo da casa, sem ter que perguntar nada.

Limites que este adapter respeita de proposito:

- **Nao inventa requisicao.** So le respostas que a pagina pediu sozinha.
- **Nao contorna protecao anti-bot.** Se o parser reconhecer a tela de
  bloqueio, levanta `CasaBloqueada` e o bot para.
- **Nao faz login e nao aposta.** Navega so em pagina publica de odds.

O Playwright e importado so quando o adapter e usado, para que o resto do bot
(e os testes) funcione sem ele instalado.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime

from src.adapters.base import AdapterDeOdds
from src.adapters.casas.base import CasaBloqueada, ParserDeCasa
from src.modelos import OddNormalizada, agora_utc

log = logging.getLogger(__name__)

MENSAGEM_SEM_PLAYWRIGHT = (
    "A Opcao B precisa do Playwright, que nao esta instalado.\n"
    "Instale com:\n"
    "    python -m pip install playwright\n"
    "    python -m playwright install chromium"
)


class PlaywrightAusente(RuntimeError):
    pass


class BufferDePayloads:
    """Fila do que foi interceptado, entre a thread do navegador e o bot.

    Os eventos do Playwright chegam por callback; o `coletar()` do bot roda
    noutro momento. Este buffer liga os dois com seguranca.
    """

    def __init__(self, tamanho_maximo: int = 500):
        self.tamanho_maximo = tamanho_maximo
        self._itens: list[tuple[str, str, str]] = []
        self._trava = threading.Lock()
        self.descartados = 0

    def adicionar(self, torneio_id: str, url: str, corpo: str) -> None:
        with self._trava:
            if len(self._itens) >= self.tamanho_maximo:
                self._itens.pop(0)
                self.descartados += 1
            self._itens.append((torneio_id, url, corpo))

    def drenar(self) -> list[tuple[str, str, str]]:
        with self._trava:
            itens, self._itens = self._itens, []
            return itens

    def __len__(self) -> int:
        with self._trava:
            return len(self._itens)


class AdapterNavegador(AdapterDeOdds):
    def __init__(
        self,
        parser: ParserDeCasa,
        torneios: list[dict],
        pasta_perfil: str | None = None,
        sem_janela: bool = True,
        segundos_por_ciclo: float = 6.0,
        tempo_limite_navegacao: int = 45000,
    ):
        self.parser = parser
        self.nome = f"navegador:{parser.nome}"
        self.torneios = torneios
        self.pasta_perfil = pasta_perfil
        self.sem_janela = sem_janela
        self.segundos_por_ciclo = segundos_por_ciclo
        self.tempo_limite_navegacao = tempo_limite_navegacao

        self.buffer = BufferDePayloads()
        self._playwright = None
        self._contexto = None
        self._paginas: dict[str, object] = {}
        self._iniciado = False
        self.payloads_recebidos = 0

    # ------------------------------------------------------------------
    def _importar_playwright(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as erro:
            raise PlaywrightAusente(MENSAGEM_SEM_PLAYWRIGHT) from erro
        return sync_playwright

    def iniciar(self) -> None:
        """Abre o navegador e deixa uma aba por torneio rodando."""
        if self._iniciado:
            return

        sync_playwright = self._importar_playwright()
        self._playwright = sync_playwright().start()

        # Site .bet.br em portugues: sem isto a pagina (e as telas de
        # verificacao) vem em ingles, o que ja escondeu um bloqueio de nos
        # uma vez.
        preferencias = {"locale": "pt-BR", "timezone_id": "America/Sao_Paulo"}

        if self.pasta_perfil:
            # Perfil persistente: voce aceita o portao de idade e os cookies
            # uma vez, na mao, e o bot reaproveita dali em diante. Evita que o
            # bot declare idade no seu lugar.
            self._contexto = self._playwright.chromium.launch_persistent_context(
                self.pasta_perfil, headless=self.sem_janela, **preferencias
            )
        else:
            navegador = self._playwright.chromium.launch(headless=self.sem_janela)
            self._contexto = navegador.new_context(**preferencias)

        for torneio_id, url in self.parser.paginas(self.torneios):
            self._abrir_pagina(torneio_id, url)

        self._iniciado = True
        if not self._paginas:
            log.warning(
                "Nenhuma pagina aberta para %s: falta o caminho da casa no config.json.",
                self.parser.nome,
            )

    def _abrir_pagina(self, torneio_id: str, url: str) -> None:
        pagina = self._contexto.new_page()
        self._ligar_escutas(pagina, torneio_id)
        try:
            pagina.goto(url, timeout=self.tempo_limite_navegacao, wait_until="domcontentloaded")
        except Exception as erro:  # noqa: BLE001 - o Playwright usa erros proprios
            log.error("Nao consegui abrir %s: %s", url, erro)
            return
        self._paginas[torneio_id] = pagina
        log.info("Pagina aberta para %s: %s", torneio_id, url)

    def _ligar_escutas(self, pagina, torneio_id: str) -> None:
        """Escuta as respostas HTTP e os quadros de WebSocket da pagina."""

        def ao_receber_resposta(resposta) -> None:
            try:
                url = resposta.url
                if not self.parser.interessa(url):
                    return
                corpo = resposta.text()
            except Exception:  # noqa: BLE001 - resposta ja descartada pelo navegador
                return
            self.payloads_recebidos += 1
            self.buffer.adicionar(torneio_id, url, corpo)

        def ao_abrir_websocket(ws) -> None:
            if not self.parser.interessa(ws.url):
                return
            log.info("WebSocket relevante aberto: %s", ws.url)

            def ao_receber_quadro(carga) -> None:
                if isinstance(carga, (bytes, bytearray)):
                    return
                self.payloads_recebidos += 1
                self.buffer.adicionar(torneio_id, ws.url, carga)

            ws.on("framereceived", ao_receber_quadro)

        pagina.on("response", ao_receber_resposta)
        pagina.on("websocket", ao_abrir_websocket)

    # ------------------------------------------------------------------
    def coletar(self) -> list[OddNormalizada]:
        """Deixa as paginas rodarem um pouco e traduz o que elas receberam."""
        if not self._iniciado:
            self.iniciar()

        self._deixar_rodar()
        capturados = self.buffer.drenar()

        if not capturados:
            self._conferir_bloqueio()
            return []

        return self.traduzir(capturados, agora_utc())

    def _deixar_rodar(self) -> None:
        """Da tempo para a pagina buscar a proxima atualizacao sozinha."""
        alguma = next(iter(self._paginas.values()), None)
        if alguma is None:
            return
        try:
            alguma.wait_for_timeout(self.segundos_por_ciclo * 1000)
        except Exception as erro:  # noqa: BLE001
            log.debug("Espera interrompida: %s", erro)

    def traduzir(
        self, capturados: list[tuple[str, str, str]], agora: datetime
    ) -> list[OddNormalizada]:
        """Converte os payloads brutos para o schema unico.

        Fica separado de `coletar` para poder ser testado com payloads
        gravados, sem abrir navegador nenhum.
        """
        odds: list[OddNormalizada] = []
        for torneio_id, url, corpo in capturados:
            try:
                dados = json.loads(corpo)
            except (json.JSONDecodeError, TypeError):
                continue
            try:
                odds.extend(self.parser.converter(url, dados, torneio_id, agora))
            except Exception as erro:  # noqa: BLE001 - formato da casa mudou
                log.error(
                    "O parser de %s falhou em %s (o formato da casa pode ter mudado): %s",
                    self.parser.nome, url, erro,
                )
        return odds

    def _texto_da_pagina(self, pagina) -> str:
        """Le o que da para ler da pagina, com uma segunda tentativa.

        Telas de verificacao anti-bot se recarregam sozinhas, e uma leitura
        que cai no meio da recarga levanta erro. Engolir esse erro calado
        faria o bot achar que esta tudo bem com a casa bloqueada - por isso
        aqui tentamos de novo e, no fim, usamos ate o titulo da aba.
        """
        partes: list[str] = []
        for tentativa in range(2):
            try:
                partes.append(pagina.title() or "")
            except Exception as erro:  # noqa: BLE001
                log.debug("Nao consegui ler o titulo: %s", erro)
            try:
                partes.append(pagina.inner_text("body"))
                break
            except Exception as erro:  # noqa: BLE001
                log.debug("Leitura da pagina falhou (tentativa %d): %s", tentativa + 1, erro)
                try:
                    pagina.wait_for_timeout(1500)
                except Exception:  # noqa: BLE001
                    break
        return "\n".join(p for p in partes if p)

    def _conferir_bloqueio(self) -> None:
        """Sem dados, verifica se a casa esta bloqueando - e para se estiver."""
        nao_lidas = []
        for torneio_id, pagina in self._paginas.items():
            texto = self._texto_da_pagina(pagina)
            if not texto:
                nao_lidas.append(torneio_id)
                continue
            if self.parser.esta_bloqueado(texto):
                raise CasaBloqueada(
                    f"{self.parser.nome} esta bloqueando o conteudo em {torneio_id}. "
                    "O projeto nao contorna protecao anti-bot: pare e procure um "
                    "acesso autorizado aos dados."
                )

        if nao_lidas:
            log.warning(
                "Nao consegui ler o conteudo de %s para saber se ha bloqueio.",
                ", ".join(nao_lidas),
            )

    def encerrar(self) -> None:
        for pagina in self._paginas.values():
            try:
                pagina.close()
            except Exception:  # noqa: BLE001
                pass
        self._paginas.clear()
        for recurso in (self._contexto, self._playwright):
            try:
                if recurso is not None:
                    recurso.close() if recurso is self._contexto else recurso.stop()
            except Exception:  # noqa: BLE001
                pass
        self._contexto = None
        self._playwright = None
        self._iniciado = False
