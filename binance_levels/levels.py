"""Cascades of price levels.

Definitions
  * A swing high (swing low) is a candle whose high (low) is the highest (lowest) among `strength` candles
    on each side of it. Only confirmed swings are used (there must be `strength` candles after it).
  * A CASCADE is a group of at least `min_extremes` swing highs (resistance) or swing lows (support) whose prices
    lie within a tolerance of each other. The level of the cascade is the average price of its extremes.
    The tolerance is either a fixed percent or N "average 1-minute candles" (adapts to the volatility of the coin).
  * A cascade is dropped when the price has already closed beyond it after its last extreme (it was broken).
  * SCORE (0-100) of a cascade = 50 points for the number of extremes (5 or more = full) + 20 points for how long
    the cascade has existed (first to last extreme, relative to the searched history) + 30 points for the volume
    traded on the extreme candles compared with the usual candle volume (3x or more = full).
  * The distance to a cascade is measured from the current price; it is also expressed in "average 1-minute candles",
    where the average 1-minute candle is the mean (high - low) of the last hour of 1-minute candles.
  * The TREND of the approach compares the distance now with the distance a few minutes ago:
    "closing" (getting closer), "away" (moving away from the cascade) or "flat".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from .binance_api import Candle

RESISTANCE = "resistance"
SUPPORT = "support"

CLOSING = "closing"
AWAY = "away"
FLAT = "flat"

MIN_TOLERANCE_PERCENT = 0.05   # limits for the adaptive tolerance, so a quiet or a wild coin cannot break the logic
MAX_TOLERANCE_PERCENT = 2.0


@dataclass
class Level:
    side: str                      # RESISTANCE or SUPPORT
    price: float                   # average price of the extremes
    touches: int                   # number of extremes in the cascade
    last_index: int                # index of the newest extreme
    first_index: int = 0           # index of the oldest extreme
    score: float = 0.0             # 0-100, see the module docstring
    tolerance_percent: float = 0.0  # tolerance that was used to build the cascade


@dataclass
class Approach:
    level: Level
    price: float             # current price
    distance: float          # absolute price distance to the level
    distance_percent: float
    distance_candles: float  # distance / average 1-minute candle range
    trend: str = FLAT        # CLOSING / AWAY / FLAT


def tolerance_percent_for(mode: str, percent: float, candles: float, avg_range: float, price: float) -> float:
    """Cascade tolerance in percent of the price. mode 'percent' = fixed; 'candles' = N average 1-minute candles."""
    if mode == "candles" and avg_range > 0 and price > 0:
        value = candles * avg_range / price * 100.0
        return min(MAX_TOLERANCE_PERCENT, max(MIN_TOLERANCE_PERCENT, value))
    return max(0.0, percent)


def find_swings(candles: Sequence[Candle], strength: int) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Return (swing highs, swing lows) as lists of (candle index, price)."""
    strength = max(1, int(strength))
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    for i in range(strength, len(candles) - strength):
        left = candles[i - strength:i]
        right = candles[i + 1:i + 1 + strength]
        high, low = candles[i].high, candles[i].low
        # strict on the left, non-strict on the right: a flat top is counted once (its first candle)
        if all(high > c.high for c in left) and all(high >= c.high for c in right):
            highs.append((i, high))
        if all(low < c.low for c in left) and all(low <= c.low for c in right):
            lows.append((i, low))
    return highs, lows


def cluster(
    points: Sequence[tuple[int, float]], tolerance_percent: float, min_count: int
) -> list[tuple[float, int, int, list[tuple[int, float]]]]:
    """Group points whose prices are within `tolerance_percent` of the lowest price of the group.
    Returns (average price, count, newest index, members) of every group with at least `min_count` points."""
    ordered = sorted(points, key=lambda p: p[1])
    groups: list[list[tuple[int, float]]] = []
    for point in ordered:
        if groups and point[1] <= groups[-1][0][1] * (1.0 + tolerance_percent / 100.0):
            groups[-1].append(point)
        else:
            groups.append([point])
    result = []
    for group in groups:
        if len(group) >= max(1, min_count):
            result.append((sum(p[1] for p in group) / len(group), len(group), max(p[0] for p in group), group))
    return result


def score_level(touches: int, first: int, last: int, total: int, extreme_volume: float, usual_volume: float) -> float:
    """Strength of a cascade, 0-100 (see the module docstring)."""
    touch_points = min(max(touches, 0), 5) / 5.0 * 50.0
    span_points = 20.0 * (last - first) / max(1, total - 1)
    ratio = extreme_volume / usual_volume if usual_volume > 0 else 0.0
    volume_points = 30.0 * min(max(ratio, 0.0), 3.0) / 3.0
    return round(min(100.0, touch_points + span_points + volume_points), 1)


def find_levels(
    candles: Sequence[Candle], strength: int, tolerance_percent: float, min_extremes: int
) -> list[Level]:
    """All unbroken cascades found in `candles` (closed candles, oldest first)."""
    highs, lows = find_swings(candles, strength)
    levels: list[Level] = []
    tol = tolerance_percent / 100.0
    usual_volume = sum(c.quote_volume for c in candles) / len(candles) if candles else 0.0

    def make(side: str, price: float, count: int, last: int, members: list[tuple[int, float]]) -> Level:
        first = min(p[0] for p in members)
        volume = sum(candles[p[0]].quote_volume for p in members) / len(members)
        score = score_level(count, first, last, len(candles), volume, usual_volume)
        return Level(side, price, count, last, first, score, tolerance_percent)

    for price, count, last, members in cluster(highs, tolerance_percent, min_extremes):
        if all(c.close <= price * (1.0 + tol) for c in candles[last + 1:]):
            levels.append(make(RESISTANCE, price, count, last, members))
    for price, count, last, members in cluster(lows, tolerance_percent, min_extremes):
        if all(c.close >= price * (1.0 - tol) for c in candles[last + 1:]):
            levels.append(make(SUPPORT, price, count, last, members))
    return levels


def average_candle_range(candles_1m: Sequence[Candle], count: int) -> float:
    """Mean (high - low) of the last `count` 1-minute candles (0 if there are none)."""
    recent = list(candles_1m[-max(1, int(count)):])
    if not recent:
        return 0.0
    return sum(c.high - c.low for c in recent) / len(recent)


def distance_to(level: Level, price: float) -> float:
    """Signed distance: positive while the price is on the 'approaching' side of the level."""
    return level.price - price if level.side == RESISTANCE else price - level.price


def nearest_approach(
    levels: Sequence[Level],
    price: float,
    avg_range: float,
    price_before: Optional[float] = None,
    away_tolerance_candles: float = 0.25,
) -> Approach | None:
    """The cascade closest to `price` that the price has not broken through.

    A resistance counts while price <= level (approaching from below); a support while price >= level.
    `price_before` (the price a few minutes ago) is used for the trend: the distance must change by more than
    `away_tolerance_candles` average candles to count as closing / away.
    Returns None if there is no such cascade or the average candle range is unknown."""
    if price <= 0 or avg_range <= 0:
        return None
    best: Approach | None = None
    for level in levels:
        distance = distance_to(level, price)
        if distance < 0:
            continue  # the price is already beyond this level
        if best is None or distance < best.distance:
            trend = FLAT
            if price_before is not None and price_before > 0:
                change = (distance - distance_to(level, price_before)) / avg_range
                if change > away_tolerance_candles:
                    trend = AWAY
                elif change < -away_tolerance_candles:
                    trend = CLOSING
            best = Approach(level, price, distance, distance / price * 100.0, distance / avg_range, trend)
    return best
