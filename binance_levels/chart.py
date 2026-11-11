"""Geometry of the mini chart (pure functions, no tkinter): candles, cascade lines and the current price."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .binance_api import Candle
from .levels import Level


@dataclass
class Scene:
    low: float = 0.0
    high: float = 0.0
    candles: list = field(default_factory=list)   # (x, y_high, y_low, y_open, y_close, is_up)
    lines: list = field(default_factory=list)     # (y, price, side, score)
    price_y: float | None = None
    body_width: float = 4.0


def build_scene(
    candles: Sequence[Candle],
    levels: Sequence[Level],
    price: float | None,
    width: float,
    height: float,
    margin_left: float = 8.0,
    margin_right: float = 80.0,
    margin_y: float = 10.0,
) -> Scene:
    """Map candles / levels / price to canvas coordinates (y grows downwards).

    The vertical range covers the candles and the current price (plus 3 % padding); cascades outside it are not drawn."""
    scene = Scene()
    candles = list(candles)
    if not candles or width <= margin_left + margin_right or height <= 2 * margin_y:
        return scene
    low = min(c.low for c in candles)
    high = max(c.high for c in candles)
    if price:
        low, high = min(low, price), max(high, price)
    pad = (high - low) * 0.03 or high * 0.001
    low, high = low - pad, high + pad
    scene.low, scene.high = low, high

    def y_of(value: float) -> float:
        return margin_y + (high - value) / (high - low) * (height - 2 * margin_y)

    slot = (width - margin_left - margin_right) / len(candles)
    scene.body_width = max(1.0, min(slot * 0.7, 12.0))
    for i, c in enumerate(candles):
        x = margin_left + slot * (i + 0.5)
        scene.candles.append((x, y_of(c.high), y_of(c.low), y_of(c.open), y_of(c.close), c.close >= c.open))
    for level in levels:
        if low <= level.price <= high:
            scene.lines.append((y_of(level.price), level.price, level.side, level.score))
    if price:
        scene.price_y = y_of(price)
    return scene
