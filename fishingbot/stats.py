"""
Resultado de cada lance e estatisticas da sessao.

Antes um lance so devolvia True/False, entao nao havia como saber POR QUE
falhou (nem quantas vezes) sem dar grep no log. Agora cada lance termina com
um CastOutcome; o SessionStats conta quantos de cada tipo, quantas falhas
seguidas houve (base do disjuntor no controller) e monta o resumo mostrado na
interface e no log.
"""
from __future__ import annotations

from collections import Counter
from enum import Enum, auto


class CastOutcome(Enum):
    CAPTURED = auto()       # puxou ate o painel sumir (peixe capturado/perdido)
    NO_BITE = auto()        # nenhuma mordida dentro de bite_timeout_seconds
    HIT_TIMEOUT = auto()    # mordeu, mas o peixe nunca alinhou pra fisgar
    NO_PANEL = auto()       # apertou ESPACO, mas o painel de puxar nunca apareceu
    PULL_TIMEOUT = auto()   # painel apareceu, mas nunca sumiu (timeout de puxar)
    CAPTURE_ERROR = auto()  # a captura de tela falhou (monitor mudou, bloqueio...)
    STOPPED = auto()        # usuario/panico/watchdog interromperam: nao e falha

    @property
    def completed(self) -> bool:
        return self is CastOutcome.CAPTURED

    @property
    def is_failure(self) -> bool:
        return self not in (CastOutcome.CAPTURED, CastOutcome.STOPPED)


OUTCOME_LABELS = {
    CastOutcome.CAPTURED: "capturado",
    CastOutcome.NO_BITE: "sem mordida",
    CastOutcome.HIT_TIMEOUT: "nao fisgou a tempo",
    CastOutcome.NO_PANEL: "painel de puxar nao apareceu",
    CastOutcome.PULL_TIMEOUT: "timeout ao puxar",
    CastOutcome.CAPTURE_ERROR: "erro de captura de tela",
    CastOutcome.STOPPED: "interrompido",
}


class SessionStats:
    def __init__(self) -> None:
        self.counts: Counter[CastOutcome] = Counter()
        self.consecutive_failures = 0

    def record(self, outcome: CastOutcome) -> None:
        """Interrupcoes (STOPPED) nao contam: nao sao sucesso nem falha."""
        if outcome is CastOutcome.STOPPED:
            return
        self.counts[outcome] += 1
        if outcome.is_failure:
            self.consecutive_failures += 1
        else:
            self.consecutive_failures = 0

    @property
    def attempts(self) -> int:
        return sum(self.counts.values())

    @property
    def captured(self) -> int:
        return self.counts[CastOutcome.CAPTURED]

    def success_rate(self) -> float:
        return self.captured / self.attempts if self.attempts else 0.0

    def summary(self) -> str:
        if not self.attempts:
            return "Lances: 0"
        text = (f"Lances: {self.attempts} | Capturas: {self.captured} "
                f"({self.success_rate():.0%})")
        if self.consecutive_failures:
            text += f" | Falhas seguidas: {self.consecutive_failures}"
        return text

    def breakdown(self) -> str:
        """Falhas por motivo, mais frequentes primeiro (vazio se nao houve)."""
        fails = [(o, n) for o, n in self.counts.most_common() if o.is_failure]
        return ", ".join(f"{OUTCOME_LABELS[o]}: {n}" for o, n in fails)
