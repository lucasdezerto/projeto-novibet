"""Normalizacao de nomes e de identificadores de evento.

Problema que isto resolve: o mesmo jogo aparece com nome e id diferentes em
cada casa ("J. Sinner", "Sinner J.", "Jannik Sinner"). Para comparar odds
entre casas o bot precisa de um id igual nos dois lados.

Regra do id: <jogador_a>-vs-<jogador_b>-<data_hora_ate_o_minuto>, com os dois
nomes em ordem alfabetica para nao depender de quem a casa chama de mandante.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from datetime import datetime, timedelta, timezone

# Sufixos que aparecem no fim do nome e nao ajudam a identificar o jogador.
_SUFIXOS_IGNORADOS = {"jr", "sr", "ii", "iii"}


def remover_acentos(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def normalizar_nome(nome: str) -> str:
    """Transforma o nome de um jogador numa forma comparavel entre casas.

    'J. Sinner' e 'Jannik Sinner' viram os dois 'sinner': mantemos apenas o
    sobrenome (ultima palavra com mais de uma letra), que e a parte que as
    casas escrevem por extenso com mais consistencia.
    """
    texto = remover_acentos(nome or "").lower()
    texto = texto.replace("&", " e ")
    texto = re.sub(r"[^a-z0-9\s'-]", " ", texto)
    partes = [p.strip("-'") for p in texto.split()]
    partes = [p for p in partes if p and p not in _SUFIXOS_IGNORADOS]
    if not partes:
        return ""

    # Formato "Sobrenome J." ou "Sobrenome J": a inicial fica no fim.
    if len(partes) > 1 and len(partes[-1]) == 1:
        partes = partes[:-1]

    significativas = [p for p in partes if len(p) > 1]
    if not significativas:
        return "-".join(partes)

    # Duplas ("Bopanna/Ebden") ja vem tratadas por normalizar_selecao.
    return significativas[-1]


def normalizar_selecao(nome: str) -> str:
    """Normaliza o lado apostado: um jogador ou uma dupla separada por '/'."""
    bruto = (nome or "").strip()
    if not bruto:
        return ""
    if "/" in bruto:
        jogadores = [normalizar_nome(p) for p in bruto.split("/")]
        jogadores = [j for j in jogadores if j]
        return "-".join(sorted(jogadores))
    return normalizar_nome(bruto)


def arredondar_horario(quando: datetime, minutos: int = 15) -> datetime:
    """Encaixa o horario numa janela de N minutos.

    As casas divergem em alguns minutos no horario de inicio; sem isso o mesmo
    jogo geraria ids diferentes.
    """
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=timezone.utc)
    quando = quando.astimezone(timezone.utc).replace(second=0, microsecond=0)
    resto = quando.minute % minutos
    return quando - timedelta(minutes=resto)


def interpretar_horario(valor: str | datetime) -> datetime:
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    texto = (valor or "").strip().replace("Z", "+00:00")
    quando = datetime.fromisoformat(texto)
    return quando if quando.tzinfo else quando.replace(tzinfo=timezone.utc)


def gerar_id_evento(participante_a: str, participante_b: str, inicio: str | datetime) -> str:
    """Monta o id normalizado do jogo."""
    a = normalizar_selecao(participante_a)
    b = normalizar_selecao(participante_b)
    primeiro, segundo = sorted([a, b])
    quando = arredondar_horario(interpretar_horario(inicio))
    return f"{primeiro}-vs-{segundo}-{quando.strftime('%Y-%m-%dT%H:%M')}"


def forma_comparavel(nome: str) -> str:
    """Todos os pedacos relevantes do nome, em ordem alfabetica.

    A regra do sobrenome sozinha nao resolve sobrenome composto: a casa que
    escreve 'Auger-Aliassime' e a que escreve 'Auger Aliassime' cairiam em
    sobrenomes diferentes. Aqui hifen, barra e espaco viram todos separador,
    entao as duas formas dao 'aliassime-auger'.
    """
    texto = remover_acentos(nome or "").lower()
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    partes = [p for p in texto.split() if len(p) > 1 and p not in _SUFIXOS_IGNORADOS]
    return "-".join(sorted(partes))


def _semelhanca(nome_a: str, nome_b: str) -> float:
    """Nota de 0 a 1, pelo caminho que der o melhor resultado.

    Compara pelo sobrenome (bom para 'J. Sinner' x 'Jannik Sinner') e pela
    forma completa (boa para sobrenome composto), e fica com a maior nota.
    """
    por_sobrenome = (normalizar_selecao(nome_a), normalizar_selecao(nome_b))
    por_completo = (forma_comparavel(nome_a), forma_comparavel(nome_b))

    melhor = 0.0
    for a, b in (por_sobrenome, por_completo):
        if not a or not b:
            continue
        nota = 1.0 if a == b else difflib.SequenceMatcher(None, a, b).ratio()
        melhor = max(melhor, nota)
    return melhor


def parecidos(nome_a: str, nome_b: str, limiar: float = 0.86) -> bool:
    """Comparacao aproximada, usada quando o id exato nao bate.

    Serve para o dia em que entrarem adapters de sites (Fase 3) que escrevem
    os nomes de um jeito que a regra do sobrenome nao resolve.
    """
    return _semelhanca(nome_a, nome_b) >= limiar


def melhor_correspondencia(alvo: str, candidatos: list[str], limiar: float = 0.86) -> str | None:
    """Devolve o candidato mais parecido com o alvo, ou None se nenhum servir."""
    melhor, melhor_nota = None, 0.0
    for candidato in candidatos:
        nota = _semelhanca(alvo, candidato)
        if nota > melhor_nota:
            melhor, melhor_nota = candidato, nota
    return melhor if melhor_nota >= limiar else None
