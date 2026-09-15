"""
Funcoes de visao computacional usadas pelo bot de pesca.
Tudo aqui trabalha em cima de arrays numpy BGR (formato que o mss/opencv usam).
"""
from __future__ import annotations

import numpy as np
import cv2
import mss


def get_monitor(sct: mss.mss, monitor_index: int) -> dict:
    monitors = sct.monitors
    if monitor_index < 0 or monitor_index >= len(monitors):
        raise ValueError(
            f"monitor_index {monitor_index} invalido. Monitores disponiveis: 0..{len(monitors) - 1}"
        )
    return monitors[monitor_index]


def grab(sct: mss.mss, roi: list[int]) -> np.ndarray:
    """Captura uma regiao da tela. roi = [x, y, w, h] em coordenadas absolutas."""
    x, y, w, h = roi
    shot = sct.grab({"left": x, "top": y, "width": w, "height": h})
    frame = np.array(shot)  # BGRA
    return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)


def grab_full(sct: mss.mss, monitor: dict) -> np.ndarray:
    shot = sct.grab(monitor)
    frame = np.array(shot)
    return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)


def hsv_mask(frame_bgr: np.ndarray, lower: list[int], upper: list[int]) -> np.ndarray:
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    lower_np = np.array(lower, dtype=np.uint8)
    upper_np = np.array(upper, dtype=np.uint8)
    return cv2.inRange(hsv, lower_np, upper_np)


def pixel_ratio(mask: np.ndarray) -> float:
    if mask.size == 0:
        return 0.0
    return float(np.count_nonzero(mask)) / float(mask.size)


def largest_blob_centroid(mask: np.ndarray, min_area: int = 10) -> tuple[float, float] | None:
    """Retorna (cx, cy) do maior blob na mascara, em coordenadas relativas ao recorte usado."""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < min_area:
        return None
    m = cv2.moments(largest)
    if m["m00"] == 0:
        return None
    cx = m["m10"] / m["m00"]
    cy = m["m01"] / m["m00"]
    return cx, cy


def bgr_to_hsv_pixel(bgr_pixel) -> tuple[int, int, int]:
    arr = np.uint8([[bgr_pixel]])
    hsv = cv2.cvtColor(arr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[0][0]
    return int(h), int(s), int(v)


def read_distance_text(frame_bgr: np.ndarray, tesseract_cmd: str | None = None) -> int | None:
    """OCR opcional para ler o numero de metros. Retorna None se nao conseguir extrair um inteiro."""
    try:
        import pytesseract
        import re
    except ImportError:
        return None

    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    config = "--psm 7 -c tessedit_char_whitelist=0123456789"
    try:
        text = pytesseract.image_to_string(thresh, config=config)
    except Exception:
        return None

    match = re.search(r"\d+", text)
    if not match:
        return None
    try:
        return int(match.group())
    except ValueError:
        return None
