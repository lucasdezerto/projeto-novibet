"""Opcao B pela extensao do Chrome (docs/decisoes.md D-018).

Uma pessoa abre as paginas de torneio da casa no Chrome dela, do jeito
normal. A extensao da pasta `extensao/` copia as respostas de odds que a
propria pagina recebeu e manda para este receptor, que so escuta no proprio
computador (127.0.0.1).

Diferenca para o `navegador.py`: la o bot abre um navegador automatizado, e as
casas `.bet.br` bloqueiam isso (D-011). Aqui quem navega e uma pessoa; o bot
so recebe copias.

Limites que valem aqui, de proposito:

- A extensao nao faz requisicao ao site, nao recarrega pagina, nao clica e
  nao resolve verificacao nenhuma. Se a tela de verificacao aparecer, quem
  resolve e a pessoa - ou ninguem.
- Se a pagina mostrar tela de bloqueio, o bot levanta `CasaBloqueada`.
- O receptor recusa pedidos vindos de sites (so aceita a extensao), para
  nenhuma pagina aberta no navegador conseguir injetar odds falsas.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from src.adapters.base import AdapterDeOdds
from src.adapters.casas.base import CasaBloqueada, ParserDeCasa, converter_corpo
from src.modelos import OddNormalizada, agora_utc

log = logging.getLogger(__name__)

CABECALHO_DA_EXTENSAO = "X-Projeto-Novibet"
TAMANHO_MAXIMO_CORPO = 5 * 1024 * 1024
ESTADO_VALIDO_POR_SEGUNDOS = 90
ESQUECER_PRECO_APOS = timedelta(hours=6)


class ErroDaExtensao(RuntimeError):
    """O receptor nao conseguiu subir (ex: porta ja ocupada)."""


def requisicao_permitida(cabecalhos) -> bool:
    """So aceita pedidos da extensao.

    Um site qualquer aberto no navegador consegue mandar POST para
    127.0.0.1, mas nao consegue mandar cabecalho proprio sem o receptor
    autorizar (e ele nunca autoriza). E todo pedido vindo de site traz o
    `Origin` do site, enquanto o da extensao traz `chrome-extension://`.
    """
    if cabecalhos.get(CABECALHO_DA_EXTENSAO) != "1":
        return False
    origem = cabecalhos.get("Origin")
    return origem is None or origem.startswith("chrome-extension://")


def torneio_da_pagina(pagina: str, torneios: list[dict], casa: str = "novibet") -> str:
    """Descobre de qual torneio do config e a aba que mandou o payload.

    O id do feed nao bate com o da pagina (o feed da Novibet usa outro
    numero), entao a comparacao e pelo endereco da aba. Pagina fora do
    config devolve "" - as odds entram mesmo assim, so sem o nome do torneio.
    """
    for torneio in torneios:
        caminho = (torneio.get(casa) or {}).get("caminho")
        if caminho and caminho in (pagina or ""):
            return torneio["id"]
    return ""


class AcumuladorDeOdds:
    """Guarda o que a extensao mandou entre um ciclo do bot e o seguinte.

    A pagina manda uma atualizacao a cada ~5s, e o bot le em ciclos mais
    longos. Guardar so a ultima odd de cada preco apagaria a hora exata em que
    ela mudou - e essa hora e o que mede o atraso. Por isso o acumulador
    entrega, por preco: cada mudanca, no momento em que chegou, e depois a
    leitura mais recente (para o motor saber que o preco segue igual).
    """

    def __init__(self) -> None:
        self._trava = threading.Lock()
        self._ultima: dict[tuple[str, str, str, str], OddNormalizada] = {}
        self._mudancas: list[OddNormalizada] = []
        self._tocadas: set[tuple[str, str, str, str]] = set()

    def registrar(self, odds: list[OddNormalizada]) -> None:
        with self._trava:
            for odd in odds:
                anterior = self._ultima.get(odd.chave)
                if anterior is None or (anterior.odd, anterior.suspenso) != (odd.odd, odd.suspenso):
                    self._mudancas.append(odd)
                self._ultima[odd.chave] = odd
                self._tocadas.add(odd.chave)

    def drenar(self, agora: datetime) -> list[OddNormalizada]:
        with self._trava:
            saida = list(self._mudancas)
            ultima_emitida = {odd.chave: odd for odd in saida}
            for chave in self._tocadas:
                mais_recente = self._ultima[chave]
                if ultima_emitida.get(chave) is not mais_recente:
                    saida.append(mais_recente)
            self._mudancas = []
            self._tocadas = set()

            vencidas = [
                chave
                for chave, odd in self._ultima.items()
                if agora - odd.timestamp_coleta > ESQUECER_PRECO_APOS
            ]
            for chave in vencidas:
                del self._ultima[chave]

        saida.sort(key=lambda odd: odd.timestamp_coleta)
        return saida


class ReceptorDaExtensao:
    """O que fazer com cada mensagem da extensao. Nao sabe nada de HTTP."""

    def __init__(self, parser: ParserDeCasa, torneios: list[dict], apelido: str = "novibet"):
        self.parser = parser
        self.torneios = torneios
        self.apelido = apelido
        self.acumulador = AcumuladorDeOdds()
        self.payloads_recebidos = 0
        self._estados: dict[str, tuple[str, datetime]] = {}
        self._trava = threading.Lock()

    def receber_payload(self, url: str, corpo: str, pagina: str, agora: datetime) -> int:
        """Traduz uma resposta copiada pela extensao. Devolve quantas odds sairam."""
        if not self.parser.interessa(url or ""):
            return 0
        torneio_id = torneio_da_pagina(pagina, self.torneios, self.apelido)
        odds = converter_corpo(self.parser, url, corpo, torneio_id, agora)
        self.acumulador.registrar(odds)
        with self._trava:
            self.payloads_recebidos += 1
        return len(odds)

    def receber_estado(self, pagina: str, titulo: str, texto: str, agora: datetime) -> None:
        """Guarda o titulo e o comeco do texto da aba, para reconhecer bloqueio."""
        with self._trava:
            self._estados[pagina] = (f"{titulo}\n{texto}", agora)

    def drenar(self, agora: datetime) -> list[OddNormalizada]:
        return self.acumulador.drenar(agora)

    def conferir_bloqueio(self, agora: datetime) -> None:
        """Se alguma aba aberta agora mostra tela de bloqueio, para."""
        limite = timedelta(seconds=ESTADO_VALIDO_POR_SEGUNDOS)
        with self._trava:
            recentes = {
                pagina: texto
                for pagina, (texto, quando) in self._estados.items()
                if agora - quando <= limite
            }
            self._estados = {
                pagina: estado
                for pagina, estado in self._estados.items()
                if pagina in recentes
            }
        for pagina, texto in recentes.items():
            if self.parser.esta_bloqueado(texto):
                raise CasaBloqueada(
                    f"{self.parser.nome} esta mostrando tela de verificacao/bloqueio em "
                    f"{pagina}. O bot nao resolve isso: se a pessoa no navegador nao "
                    "conseguir passar normalmente, esta fonte fica desligada."
                )


class ServidorExclusivo(ThreadingHTTPServer):
    """Servidor que se recusa a dividir a porta com outro programa.

    O servidor padrao do Python liga o `SO_REUSEADDR`, e no Windows isso deixa
    dois programas escutarem na mesma porta. Com duas copias do bot abertas,
    a extensao entregaria as odds para uma delas ao acaso, em silencio.
    """

    allow_reuse_address = False

    def server_bind(self):
        exclusivo = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusivo is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusivo, 1)
        super().server_bind()


def _montar_tratador(receptor: ReceptorDaExtensao):
    class Tratador(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - nome exigido pela biblioteca
            if not requisicao_permitida(self.headers):
                self.send_error(403)
                return
            try:
                tamanho = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                tamanho = -1
            if not 0 < tamanho <= TAMANHO_MAXIMO_CORPO:
                self.send_error(413 if tamanho > 0 else 400)
                return
            try:
                dados = json.loads(self.rfile.read(tamanho))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.send_error(400)
                return
            if not isinstance(dados, dict):
                self.send_error(400)
                return

            agora = agora_utc()
            pagina = str(dados.get("pagina") or "")
            if self.path == "/payload":
                receptor.receber_payload(
                    str(dados.get("url") or ""), str(dados.get("corpo") or ""), pagina, agora
                )
            elif self.path == "/estado":
                receptor.receber_estado(
                    pagina, str(dados.get("titulo") or ""), str(dados.get("texto") or ""), agora
                )
            else:
                self.send_error(404)
                return
            self.send_response(204)
            self.end_headers()

        def do_OPTIONS(self):  # noqa: N802
            # Pre-verificacao de site: nunca autorizada.
            self.send_error(403)

        def log_message(self, formato, *args):
            log.debug("receptor: " + formato, *args)

    return Tratador


class AdapterExtensao(AdapterDeOdds):
    def __init__(
        self,
        parser: ParserDeCasa,
        torneios: list[dict],
        porta: int = 8765,
        apelido: str = "novibet",
        endereco: str = "127.0.0.1",
    ):
        self.parser = parser
        self.nome = f"extensao:{parser.nome}"
        self.porta = porta
        self.endereco = endereco
        self.receptor = ReceptorDaExtensao(parser, torneios, apelido)
        self._servidor: ThreadingHTTPServer | None = None
        self._linha: threading.Thread | None = None

    def iniciar(self) -> None:
        if self._servidor is not None:
            return
        try:
            servidor = ServidorExclusivo(
                (self.endereco, self.porta), _montar_tratador(self.receptor)
            )
        except OSError as erro:
            raise ErroDaExtensao(
                f"Nao consegui escutar em {self.endereco}:{self.porta} ({erro}). "
                "Outro programa (ou outra copia do bot) ja esta usando essa porta."
            ) from erro
        servidor.daemon_threads = True
        self._servidor = servidor
        self.porta = servidor.server_address[1]
        self._linha = threading.Thread(target=servidor.serve_forever, daemon=True)
        self._linha.start()
        log.info("Esperando a extensao do Chrome em http://%s:%d", self.endereco, self.porta)

    def coletar(self) -> list[OddNormalizada]:
        self.iniciar()
        agora = agora_utc()
        odds = self.receptor.drenar(agora)
        if not odds:
            self.receptor.conferir_bloqueio(agora)
        return odds

    def encerrar(self) -> None:
        if self._servidor is None:
            return
        self._servidor.shutdown()
        self._servidor.server_close()
        self._servidor = None
        self._linha = None
