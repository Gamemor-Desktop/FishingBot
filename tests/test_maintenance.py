"""Fase 4: log rotativo, teto da pasta debug, nome de processo e versoes fixas."""
from __future__ import annotations

import logging
import logging.handlers
import os
import re
import sys
import time
from pathlib import Path

import pytest

import main
from fishingbot import debug_tools
from fishingbot.window_detect import _get_process_name

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def clean_logging():
    root = logging.getLogger()
    saved = (root.handlers[:], root.level)
    for h in root.handlers[:]:
        root.removeHandler(h)
    yield
    for h in root.handlers[:]:
        root.removeHandler(h)
        h.close()
    for h in saved[0]:
        root.addHandler(h)
    root.setLevel(saved[1])


# -- log rotativo ----------------------------------------------------------------------

def test_log_e_rotativo_com_teto(tmp_path, monkeypatch, clean_logging):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    main._setup_logging(debug=False)
    handlers = [h for h in logging.getLogger().handlers
                if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert len(handlers) == 1
    assert handlers[0].maxBytes == main.LOG_MAX_BYTES and handlers[0].backupCount == main.LOG_BACKUPS


def test_log_gira_o_arquivo_quando_passa_do_teto(tmp_path, monkeypatch, clean_logging):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(main, "LOG_MAX_BYTES", 2000)
    main._setup_logging(debug=False)
    log = logging.getLogger("fishingbot")
    for i in range(200):
        log.info("linha de teste %d %s", i, "x" * 40)
    folder = tmp_path / "FishingBot"
    names = sorted(p.name for p in folder.glob("fishingbot.log*"))
    assert "fishingbot.log.1" in names
    assert len(names) <= 1 + main.LOG_BACKUPS
    assert all(p.stat().st_size < 4000 for p in folder.glob("fishingbot.log*"))


def test_sem_poder_abrir_o_log_o_bot_ainda_inicia(monkeypatch, clean_logging):
    def boom(*_a, **_k):
        raise PermissionError("pasta somente leitura")
    monkeypatch.setattr(main.logging.handlers, "RotatingFileHandler", boom)
    monkeypatch.setattr(main.sys, "stdout", None)        # como no .exe --windowed
    main._setup_logging(debug=False)                     # nao pode levantar
    logging.getLogger("fishingbot").info("ok")


# -- teto da pasta debug -----------------------------------------------------------------

@pytest.fixture
def debug_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    d = debug_tools.debug_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _png(folder: Path, name: str, size: int, age_days: float = 0.0) -> Path:
    p = folder / name
    p.write_bytes(b"0" * size)
    t = time.time() - age_days * 86400
    os.utime(p, (t, t))
    return p


def test_prune_apaga_o_que_passou_da_idade(debug_folder):
    velho = _png(debug_folder, "a_000001.png", 100, age_days=10)
    novo = _png(debug_folder, "b_000002.png", 100, age_days=1)
    assert debug_tools.prune_files(max_age_days=7, max_bytes=10_000) == 1
    assert not velho.exists() and novo.exists()


def test_prune_respeita_o_teto_apagando_os_mais_antigos_primeiro(debug_folder):
    files = [_png(debug_folder, f"f_{i:06d}.png", 1000, age_days=5 - i * 0.1) for i in range(10)]
    removed = debug_tools.prune_files(max_age_days=30, max_bytes=3500)
    assert removed == 7
    assert [p.exists() for p in files] == [False] * 7 + [True] * 3, "ficam os 3 mais novos"


def test_prune_nao_toca_em_outros_arquivos(debug_folder):
    outro = debug_folder / "anotacao.txt"
    outro.write_text("meu")
    _png(debug_folder, "x_000001.png", 5000, age_days=20)
    debug_tools.prune_files(max_age_days=7, max_bytes=1)
    assert outro.exists()


def test_save_roi_confere_o_teto_periodicamente(debug_folder, monkeypatch):
    import numpy as np
    chamadas = []
    monkeypatch.setattr(debug_tools, "prune_files", lambda *a, **k: chamadas.append(1) or 0)
    monkeypatch.setattr(debug_tools, "PRUNE_EVERY_SAVES", 3)
    monkeypatch.setattr(debug_tools, "_enabled", True)
    monkeypatch.setattr(debug_tools, "_saves_since_prune", 0)
    monkeypatch.setattr(debug_tools, "SAVE_INTERVAL_SECONDS", 0.0)
    frame = np.zeros((4, 4, 3), np.uint8)
    for i in range(7):
        debug_tools._last_event.clear()
        debug_tools.save_roi(f"n{i}", frame)
    assert len(chamadas) == 2          # nos saves 3 e 6


# -- nome do processo ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="so Windows")
def test_nome_do_processo_de_uma_janela_real():
    import win32gui
    found = []
    win32gui.EnumWindows(
        lambda h, _: found.append(h) if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h) else None,
        None)
    assert found, "precisa de ao menos uma janela visivel pra testar"
    nomes = [_get_process_name(h) for h in found]
    assert any(n.lower().endswith(".exe") for n in nomes)


def test_nome_do_processo_de_janela_inexistente_e_vazio():
    assert _get_process_name(0xDEADBEEF) == ""


# -- dependencias fixas -------------------------------------------------------------------------

@pytest.mark.parametrize("arquivo", ["requirements.txt", "requirements-dev.txt"])
def test_dependencias_com_versao_fixa(arquivo):
    for linha in (ROOT / arquivo).read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith(("#", "-r")):
            continue
        assert re.fullmatch(r"[A-Za-z0-9_.\-]+==[0-9][0-9A-Za-z.]*", linha), f"sem versao fixa: {linha!r}"


def test_codigo_morto_removido():
    from fishingbot import vision
    for nome in ("read_distance_text", "grab_full", "get_monitor", "largest_blob_centroid",
                 "bgr_to_hsv_pixel"):
        assert not hasattr(vision, nome), nome
