"""Motor de comparacao: decide quando uma casa esta atrasada.

Duas regras rodam a cada ciclo, sobre o mesmo jogo/mercado/selecao:

1. DESVIO - a odd da casa esta acima do preco justo da referencia por mais
   que o limiar, e continua assim ha pelo menos N segundos. Uma odd alta
   demais e o sintoma classico de mercado ainda nao reprecificado.

2. ATRASO - a referencia mexeu de forma relevante ha mais de N segundos e a
   casa nao mexeu desde entao. Esta e a deteccao de atraso propriamente dita,
   independente do tamanho do desvio.

O "preco justo" da referencia e calculado tirando a margem da casa (overround):
somando as probabilidades implicitas de todas as selecoes do mercado e
redistribuindo. Sem isso toda casa pareceria "cara" em relacao a referencia.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from src.comparador.estado import EstadoDeMercado, RegistroDePreco
from src.modelos import Alerta, OddNormalizada, agora_utc


def calcular_precos_justos(odds_por_selecao: dict[str, float]) -> dict[str, float]:
    """Remove a margem da casa e devolve a odd justa de cada selecao.

    Exemplo: odds 1.80 e 2.10 somam 1.032 de probabilidade (3,2% de margem).
    Redistribuindo, as odds justas ficam 1.86 e 2.17.
    """
    probabilidades = {
        selecao: 1.0 / odd for selecao, odd in odds_por_selecao.items() if odd and odd > 1.0
    }
    total = sum(probabilidades.values())
    if total <= 0:
        return {}
    return {selecao: total / prob for selecao, prob in probabilidades.items()}


class MotorDeComparacao:
    def __init__(
        self,
        estado: EstadoDeMercado,
        casas_referencia: list[str],
        deteccao: dict,
        casas_incluir: list[str] | None = None,
        casas_excluir: list[str] | None = None,
        remover_margem: bool = True,
    ):
        self.estado = estado
        self.casas_referencia = list(casas_referencia)
        self.remover_margem = remover_margem
        self.casas_incluir = set(casas_incluir or [])
        self.casas_excluir = set(casas_excluir or [])

        self.desvio_minimo = float(deteccao.get("desvio_minimo", 0.04))
        self.duracao_minima_segundos = float(deteccao.get("duracao_minima_segundos", 20))
        self.movimento_referencia_minimo = float(
            deteccao.get("movimento_referencia_minimo", 0.03)
        )
        self.atraso_maximo_segundos = float(deteccao.get("atraso_maximo_segundos", 60))
        self.odd_minima = float(deteccao.get("odd_minima", 1.2))
        self.odd_maxima = float(deteccao.get("odd_maxima", 15.0))

        # Desde quando cada preco esta desviado. Serve para exigir que o
        # desvio se sustente antes de virar alerta.
        self._desviado_desde: dict[tuple[str, str, str, str], datetime] = {}

        self.ultima_referencia_por_mercado: dict[tuple[str, str], str] = {}
        self.mercados_sem_referencia: set[tuple[str, str]] = set()

    # ------------------------------------------------------------------
    def _casa_monitorada(self, casa: str, casa_referencia: str) -> bool:
        if casa == casa_referencia:
            return False
        if casa in self.casas_excluir:
            return False
        if self.casas_incluir and casa not in self.casas_incluir:
            return False
        return True

    def _escolher_referencia(self, casas_presentes: set[str]) -> str | None:
        for candidata in self.casas_referencia:
            if candidata in casas_presentes:
                return candidata
        return None

    # ------------------------------------------------------------------
    def avaliar(self, odds: list[OddNormalizada], agora: datetime | None = None) -> list[Alerta]:
        """Processa um ciclo de coleta e devolve os alertas encontrados."""
        agora = agora or agora_utc()

        # 1. Atualiza a memoria de precos.
        registros: dict[tuple[str, str, str, str], RegistroDePreco] = {}
        for odd in odds:
            registros[odd.chave] = self.estado.atualizar(odd)

        # 2. Agrupa por jogo+mercado: {(evento, mercado): {casa: {selecao: odd}}}
        agrupado: dict[tuple[str, str], dict[str, dict[str, OddNormalizada]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        for odd in odds:
            agrupado[(odd.evento_id_normalizado, odd.mercado)][odd.casa][odd.selecao] = odd

        alertas: list[Alerta] = []
        self.mercados_sem_referencia = set()

        for chave_mercado, por_casa in agrupado.items():
            referencia = self._escolher_referencia(set(por_casa))
            if referencia is None:
                self.mercados_sem_referencia.add(chave_mercado)
                continue
            self.ultima_referencia_por_mercado[chave_mercado] = referencia

            odds_referencia = {sel: o.odd for sel, o in por_casa[referencia].items()}
            if len(odds_referencia) < 2:
                # Sem o mercado completo nao da para tirar a margem com seguranca.
                self.mercados_sem_referencia.add(chave_mercado)
                continue

            precos_justos = (
                calcular_precos_justos(odds_referencia)
                if self.remover_margem
                else dict(odds_referencia)
            )

            for casa, por_selecao in por_casa.items():
                if not self._casa_monitorada(casa, referencia):
                    continue
                for selecao, odd in por_selecao.items():
                    preco_justo = precos_justos.get(selecao)
                    if not preco_justo:
                        continue
                    alerta = self._avaliar_preco(
                        odd=odd,
                        preco_justo=preco_justo,
                        casa_referencia=referencia,
                        registro_casa=registros.get(odd.chave),
                        registro_referencia=self.estado.obter(
                            (referencia, odd.evento_id_normalizado, odd.mercado, selecao)
                        ),
                        agora=agora,
                    )
                    if alerta:
                        alertas.append(alerta)

        self.estado.limpar_antigos(agora)
        self._esquecer_desvios_de_jogos_encerrados()
        return alertas

    def _esquecer_desvios_de_jogos_encerrados(self) -> None:
        """Sem isto o bot vazaria memoria devagar rodando 24/7."""
        encerrados = [
            chave for chave in self._desviado_desde if self.estado.obter(chave) is None
        ]
        for chave in encerrados:
            del self._desviado_desde[chave]

    # ------------------------------------------------------------------
    def _avaliar_preco(
        self,
        odd: OddNormalizada,
        preco_justo: float,
        casa_referencia: str,
        registro_casa: RegistroDePreco | None,
        registro_referencia: RegistroDePreco | None,
        agora: datetime,
    ) -> Alerta | None:
        if odd.suspenso or registro_casa is None:
            self._desviado_desde.pop(odd.chave, None)
            return None
        if not (self.odd_minima <= odd.odd <= self.odd_maxima):
            self._desviado_desde.pop(odd.chave, None)
            return None

        desvio = (odd.odd / preco_justo) - 1.0
        segundos_parado = registro_casa.segundos_parado(agora)

        def montar(tipo: str, detalhe: str) -> Alerta:
            return Alerta(
                tipo=tipo,
                casa=odd.casa,
                evento_id_normalizado=odd.evento_id_normalizado,
                evento_descricao=odd.evento_descricao,
                torneio_id=odd.torneio_id,
                mercado=odd.mercado,
                selecao=odd.selecao,
                odd_casa=odd.odd,
                odd_referencia=preco_justo,
                casa_referencia=casa_referencia,
                desvio=desvio,
                segundos_parado=segundos_parado,
                detalhe=detalhe,
                timestamp=agora,
            )

        # Regra 2 - atraso: a referencia mexeu e a casa nao acompanhou.
        if registro_referencia is not None:
            movimento = abs(registro_referencia.variacao)
            segundos_desde_movimento = (
                agora - registro_referencia.mudou_em
            ).total_seconds()
            # Estritamente antes: se a casa mexeu no mesmo momento em que a
            # referencia mexeu, ela acompanhou e nao esta atrasada.
            casa_nao_acompanhou = registro_casa.mudou_em < registro_referencia.mudou_em
            if (
                movimento >= self.movimento_referencia_minimo
                and segundos_desde_movimento >= self.atraso_maximo_segundos
                and casa_nao_acompanhou
            ):
                return montar(
                    "atraso",
                    f"A referencia {casa_referencia} mexeu {movimento * 100:.1f}% ha "
                    f"{segundos_desde_movimento:.0f}s e {odd.casa} nao acompanhou.",
                )

        # Regra 1 - desvio sustentado.
        if desvio >= self.desvio_minimo:
            inicio = self._desviado_desde.setdefault(odd.chave, agora)
            duracao = (agora - inicio).total_seconds()
            if duracao >= self.duracao_minima_segundos:
                return montar(
                    "desvio",
                    f"Odd {desvio * 100:.1f}% acima do preco justo ha {duracao:.0f}s.",
                )
        else:
            self._desviado_desde.pop(odd.chave, None)

        return None
