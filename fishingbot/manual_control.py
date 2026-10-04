"""
Escuta global da tecla ENTER -- o UNICO comando de teclado que o usuario
aciona manualmente durante a automacao, usado pra confirmar "ja peguei e
cortei o peixe, pode pescar de novo".

Usa a biblioteca `keyboard` (ja listada em requirements.txt) porque ela
captura a tecla via hook global do Windows, funcionando mesmo com a janela
do FiveM em primeiro plano -- que e exatamente a situacao normal nesse
momento, ja que o jogador esta interagindo com o jogo (pegando/cortando o
peixe no chao), nao com a janela deste bot.

Importante: o hook fica registrado o tempo todo (uma unica vez, no inicio),
mas so tem QUALQUER efeito enquanto `armed` estiver ligado, o que so
acontece dentro de `wait_for_confirmation()`. Fora disso -- durante o
minigame, calibracao, etc. -- um ENTER apertado (de proposito ou sem
querer) e completamente ignorado, exatamente pra evitar que ele interfira
na automacao em andamento.
"""
from __future__ import annotations

import logging
import threading

try:
    import keyboard
except Exception:  # pragma: no cover - so acontece fora do Windows/sem a lib
    keyboard = None

log = logging.getLogger("fishingbot")

_armed = threading.Event()
_confirmed = threading.Event()
_hook_registered = False
_registration_lock = threading.Lock()


def _on_enter_pressed(_event=None) -> None:
    # So conta se estivermos explicitamente esperando por ela (armed) --
    # qualquer ENTER fora desse momento (durante o minigame, calibrando,
    # etc.) e ignorado de proposito.
    if _armed.is_set():
        _confirmed.set()


def ensure_listener() -> None:
    """Registra o hook global do ENTER uma unica vez (idempotente, thread-
    safe). Chamar cedo, na inicializacao do Controller -- so precisa
    acontecer uma vez pra vida toda do processo."""
    global _hook_registered
    if keyboard is None:
        log.warning(
            "Biblioteca 'keyboard' indisponivel -- a confirmacao manual por "
            "ENTER nao vai funcionar. Reinstale as dependencias "
            "(requirements.txt)."
        )
        return
    with _registration_lock:
        if _hook_registered:
            return
        try:
            keyboard.on_press_key("enter", _on_enter_pressed, suppress=False)
            _hook_registered = True
            log.info("Listener global da tecla ENTER registrado "
                     "(confirmacao manual entre pescarias).")
        except Exception:
            log.exception(
                "Nao foi possivel registrar o listener global de ENTER -- "
                "se o jogo estiver rodando como administrador, tente rodar "
                "o FishingBot tambem como administrador."
            )


def hook_active() -> bool:
    """True se o ENTER global esta registrado (senao so o botao CONTINUAR vale)."""
    return _hook_registered


def confirm() -> bool:
    """Confirmacao pela interface (botao CONTINUAR): mesmo efeito do ENTER,
    tambem so vale enquanto estiver esperando. Retorna se foi aceita."""
    if _armed.is_set():
        _confirmed.set()
        return True
    return False


def arm() -> None:
    """Liga o gatilho: a partir de agora, um ENTER conta como confirmacao.
    Limpa qualquer confirmacao antiga que possa ter sobrado."""
    _confirmed.clear()
    _armed.set()


def disarm() -> None:
    """Desliga o gatilho: ENTER volta a ser ignorado ate a proxima arm()."""
    _armed.clear()
    _confirmed.clear()


def wait_for_confirmation(should_abort, poll_interval: float = 0.05) -> bool:
    """Bloqueia a thread chamadora ate o usuario apertar ENTER (com o
    gatilho armado) ou `should_abort()` retornar True (usuario apertou
    PARAR, fechou o app, ou a janela do jogo sumiu). Retorna True se a
    confirmacao veio de fato do ENTER, False se foi abortado.

    Sempre desarma o gatilho ao sair (sucesso, abortado ou excecao), pra
    nunca deixar um ENTER "pendente" contando em um momento errado depois."""
    arm()
    try:
        while not _confirmed.is_set():
            if should_abort():
                return False
            _confirmed.wait(timeout=poll_interval)
        return True
    finally:
        disarm()
