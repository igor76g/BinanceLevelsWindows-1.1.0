import unittest

from binance_levels.analyzer import activity, build_row, split_rows
from binance_levels.binance_api import Candle
from binance_levels.chart import build_scene
from binance_levels.journal import BOUNCED, BROKE, NOT_REACHED, TOUCHED, Journal, evaluate_signal, summarize
from binance_levels.levels import (
    AWAY, CLOSING, FLAT, RESISTANCE, SUPPORT, Level, average_candle_range, cluster, find_levels, find_swings,
    nearest_approach, tolerance_percent_for,
)
from binance_levels.monitor import Monitor
from binance_levels.settings import Settings

MIN = 60_000


def candle(i, high, low, close=None, trades=100, step=MIN):
    close = (high + low) / 2 if close is None else close
    return Candle(i * step, i * step + step - 1, close, high, low, close, 1000.0, trades)


def series_with_highs(peaks, n=60, base=100.0, peak=110.0):
    """Flat series (high base+1) with sharp peaks (high=peak) at the given indexes."""
    out = []
    for i in range(n):
        high = peak if i in peaks else base + 1
        out.append(candle(i, high, base - 1, close=base))
    return out


class SwingTest(unittest.TestCase):
    def test_swing_high_and_low(self):
        candles = series_with_highs({20})
        highs, lows = find_swings(candles, 3)
        self.assertEqual(highs, [(20, 110.0)])

    def test_unconfirmed_last_candles_ignored(self):
        candles = series_with_highs({58})
        highs, _ = find_swings(candles, 3)
        self.assertEqual(highs, [])

    def test_flat_top_counted_once(self):
        candles = [candle(i, 105.0 if i in (20, 21) else 101.0, 99.0) for i in range(40)]
        highs, _ = find_swings(candles, 3)
        self.assertEqual(len(highs), 1)


class ClusterTest(unittest.TestCase):
    def test_groups_within_tolerance(self):
        points = [(1, 100.0), (5, 100.1), (9, 105.0)]
        groups = cluster(points, 0.2, 2)
        self.assertEqual(len(groups), 1)
        self.assertAlmostEqual(groups[0][0], 100.05)
        self.assertEqual(groups[0][1], 2)
        self.assertEqual(groups[0][2], 5)

    def test_single_extreme_is_not_a_cascade(self):
        self.assertEqual(cluster([(1, 100.0), (5, 110.0)], 0.2, 2), [])

    def test_min_count_three(self):
        points = [(1, 100.0), (5, 100.1)]
        self.assertEqual(cluster(points, 0.2, 3), [])


class FindLevelsTest(unittest.TestCase):
    def test_resistance_cascade_found(self):
        candles = series_with_highs({15, 30, 45}, peak=110.0)
        levels = find_levels(candles, 3, 0.2, 2)
        resistances = [l for l in levels if l.side == RESISTANCE]
        self.assertEqual(len(resistances), 1)
        self.assertEqual(resistances[0].touches, 3)
        self.assertAlmostEqual(resistances[0].price, 110.0)

    def test_broken_level_is_dropped(self):
        candles = series_with_highs({15, 30})
        candles[40] = candle(40, 115.0, 100.0, close=114.0)   # closed above the cascade after its last extreme
        levels = find_levels(candles, 3, 0.2, 2)
        self.assertEqual([l for l in levels if l.side == RESISTANCE], [])

    def test_support_cascade_found(self):
        candles = []
        for i in range(60):
            low = 90.0 if i in (15, 35) else 99.0
            candles.append(candle(i, 101.0, low, close=100.0))
        levels = find_levels(candles, 3, 0.2, 2)
        supports = [l for l in levels if l.side == SUPPORT]
        self.assertEqual(len(supports), 1)
        self.assertAlmostEqual(supports[0].price, 90.0)


class ApproachTest(unittest.TestCase):
    def test_average_range(self):
        candles = [candle(i, 101.0, 99.0) for i in range(10)]
        self.assertAlmostEqual(average_candle_range(candles, 60), 2.0)
        self.assertEqual(average_candle_range([], 60), 0.0)

    def test_nearest_resistance_and_support(self):
        levels = [Level(RESISTANCE, 110.0, 2, 5), Level(SUPPORT, 95.0, 2, 5)]
        a = nearest_approach(levels, 108.0, avg_range=1.0)
        self.assertEqual(a.level.side, RESISTANCE)
        self.assertAlmostEqual(a.distance, 2.0)
        self.assertAlmostEqual(a.distance_candles, 2.0)
        self.assertAlmostEqual(a.distance_percent, 2.0 / 108.0 * 100)
        b = nearest_approach(levels, 96.0, avg_range=1.0)
        self.assertEqual(b.level.side, SUPPORT)

    def test_level_already_passed_is_ignored(self):
        levels = [Level(RESISTANCE, 110.0, 2, 5)]
        self.assertIsNone(nearest_approach(levels, 111.0, 1.0))

    def test_unknown_range(self):
        self.assertIsNone(nearest_approach([Level(RESISTANCE, 110.0, 2, 5)], 100.0, 0.0))


class RowsTest(unittest.TestCase):
    def setUp(self):
        self.candles = [candle(i, 101.0, 99.0, close=100.0, trades=100) for i in range(61)]
        self.levels = [Level(RESISTANCE, 102.0, 2, 5)]

    def test_activity(self):
        natr, trades = activity(self.candles, 15)
        self.assertEqual(trades, 1500)
        self.assertAlmostEqual(natr, 2.0)

    def test_row_built_and_distance_in_candles(self):
        row = build_row(Settings(), "AAAUSDT", 100.0, 50e6, self.candles, self.levels)
        self.assertAlmostEqual(row.distance_candles, 1.0)   # distance 2 / average range 2
        self.assertEqual(row.key, "AAAUSDT:resistance")

    def test_filters(self):
        s = Settings()
        self.assertIsNone(build_row(s, "A", 100.0, 20e6, self.candles, self.levels))       # volume too low
        s2 = Settings(min_natr=5.0)
        self.assertIsNone(build_row(s2, "A", 100.0, 50e6, self.candles, self.levels))      # NATR too low
        s3 = Settings(min_trades=5000)
        self.assertIsNone(build_row(s3, "A", 100.0, 50e6, self.candles, self.levels))      # too few trades

    def test_defaults_match_request(self):
        s = Settings()
        self.assertEqual((s.min_volume_million, s.min_natr, s.min_trades, s.min_extremes), (30.0, 0.0, 0, 2))

    def test_split(self):
        s = Settings(approach_candles=1.0, closest_count=2)
        rows = [build_row(s, n, p, 50e6, self.candles, self.levels) for n, p in (("A", 100.0), ("B", 101.5), ("C", 97.0))]
        near, closest = split_rows(s, rows)
        self.assertEqual([r.symbol for r in near], ["B", "A"])
        self.assertEqual([r.symbol for r in closest], ["B", "A"])


class FakeApi:
    def __init__(self):
        self.calls = []

    def usdt_perpetual_symbols(self):
        return {"AAAUSDT", "SMALLUSDT"}

    def tickers(self):
        return {"AAAUSDT": (50e6, 108.5), "SMALLUSDT": (1e6, 108.5)}

    def klines(self, symbol, limit, start_time=None, interval="1m"):
        self.calls.append((symbol, interval))
        if interval == "1m":
            return [candle(i, 108.5, 107.5, close=108.0) for i in range(61 + 5)]   # price rising towards 110
        return [c._replace(open_time=c.open_time * 5, close_time=c.close_time * 5 + 4 * MIN)
                for c in series_with_highs({15, 30, 45}, n=80, peak=110.0)]


class MonitorTest(unittest.TestCase):
    def test_cycle_alerts_once_and_respects_cooldown(self):
        alerts, results = [], []
        settings = Settings(approach_candles=3.0)
        mon = Monitor(FakeApi(), lambda: settings, lambda *a: results.append(a), lambda row, s: alerts.append(row),
                      lambda t: None, lambda t: None)
        now = 80 * 5 * MIN / 1000 + 10_000   # all synthetic candles are in the past
        mon.cycle(settings, now)
        self.assertEqual(len(alerts), 1)
        near, closest, since, _ = results[-1]
        self.assertEqual([r.symbol for r in near], ["AAAUSDT"])
        self.assertEqual(alerts[0].side, RESISTANCE)
        mon.cycle(settings, now + 60)                     # still in the list, but cooldown is active
        self.assertEqual(len(alerts), 1)
        self.assertNotIn("SMALLUSDT", [c[0] for c in mon.api.calls])  # low-volume coin is never downloaded

    def test_levels_cached_between_cycles(self):
        settings = Settings(approach_candles=3.0)
        api = FakeApi()
        mon = Monitor(api, lambda: settings, lambda *a: None, lambda row, s: None, lambda t: None, lambda t: None)
        now = 80 * 5 * MIN / 1000 + 10_000
        mon.cycle(settings, now)
        mon.cycle(settings, now + 60)
        self.assertEqual(sum(1 for c in api.calls if c[1] == "5m"), 1)


class ScoreAndToleranceTest(unittest.TestCase):
    def test_score_more_extremes_is_higher(self):
        two = find_levels(series_with_highs({15, 30}), 3, 0.2, 2)[0]
        four = find_levels(series_with_highs({10, 20, 30, 40}), 3, 0.2, 2)[0]
        self.assertGreater(four.score, two.score)
        self.assertLessEqual(four.score, 100.0)

    def test_score_volume_counts(self):
        candles = series_with_highs({15, 30})
        base = find_levels(candles, 3, 0.2, 2)[0].score
        loud = [c._replace(quote_volume=5000.0) if i in (15, 30) else c for i, c in enumerate(candles)]
        self.assertGreater(find_levels(loud, 3, 0.2, 2)[0].score, base)

    def test_tolerance_adapts_to_volatility(self):
        quiet = tolerance_percent_for("candles", 0.2, 3.0, avg_range=0.01, price=100.0)
        wild = tolerance_percent_for("candles", 0.2, 3.0, avg_range=0.5, price=100.0)
        self.assertLess(quiet, wild)
        self.assertEqual(tolerance_percent_for("percent", 0.2, 3.0, 0.5, 100.0), 0.2)
        self.assertEqual(tolerance_percent_for("candles", 0.2, 3.0, 0.0, 100.0), 0.2)   # unknown range -> fixed percent
        self.assertGreaterEqual(quiet, 0.05)

    def test_min_score_filter(self):
        candles = [candle(i, 101.0, 99.0, close=100.0) for i in range(61)]
        weak = [Level(RESISTANCE, 102.0, 2, 5, score=10.0)]
        self.assertIsNone(build_row(Settings(min_level_score=30.0), "A", 100.0, 50e6, candles, weak))
        self.assertIsNotNone(build_row(Settings(min_level_score=5.0), "A", 100.0, 50e6, candles, weak))


class TrendTest(unittest.TestCase):
    LEVELS = [Level(RESISTANCE, 110.0, 2, 5)]

    def test_closing_away_flat(self):
        self.assertEqual(nearest_approach(self.LEVELS, 108.0, 1.0, price_before=106.0).trend, CLOSING)
        self.assertEqual(nearest_approach(self.LEVELS, 108.0, 1.0, price_before=109.5).trend, AWAY)
        self.assertEqual(nearest_approach(self.LEVELS, 108.0, 1.0, price_before=108.1).trend, FLAT)
        self.assertEqual(nearest_approach(self.LEVELS, 108.0, 1.0).trend, FLAT)

    def test_away_coin_is_not_in_near_list(self):
        s = Settings(approach_candles=3.0, approach_lookback_minutes=3)
        # price 3 minutes ago was 109.5, now 108 -> moving away from 110
        candles = [candle(i, 109.9, 107.9, close=109.5 if i >= 57 else 108.0) for i in range(61)]
        row = build_row(s, "A", 108.0, 50e6, candles, self.LEVELS)
        self.assertEqual(row.trend, AWAY)
        near, closest = split_rows(s, [row])
        self.assertEqual(near, [])
        self.assertEqual(len(closest), 1)       # still shown in the "closest" list
        near_off, _ = split_rows(Settings(approach_candles=3.0, approach_filter_enabled=False), [row])
        self.assertEqual(len(near_off), 1)


class JournalTest(unittest.TestCase):
    ENTRY = {"side": "resistance", "level": 110.0, "avg_range": 1.0, "tolerance_abs": 0.3}

    def c(self, i, high, low, close):
        return candle(i, high, low, close=close)

    def test_bounced(self):
        candles = [self.c(0, 109.5, 108.5, 109.0), self.c(1, 110.0, 108.0, 109.0), self.c(2, 109.0, 107.0, 107.5)]
        self.assertEqual(evaluate_signal(self.ENTRY, candles), BOUNCED)

    def test_broke(self):
        candles = [self.c(0, 110.2, 109.0, 110.0), self.c(1, 111.5, 110.0, 111.0)]
        self.assertEqual(evaluate_signal(self.ENTRY, candles), BROKE)

    def test_touched_and_not_reached(self):
        self.assertEqual(evaluate_signal(self.ENTRY, [self.c(0, 110.0, 109.2, 109.6)]), TOUCHED)
        self.assertEqual(evaluate_signal(self.ENTRY, [self.c(0, 108.0, 107.0, 107.5)]), NOT_REACHED)

    def test_support_side(self):
        entry = dict(self.ENTRY, side="support", level=100.0)
        candles = [self.c(0, 101.0, 100.0, 100.5), self.c(1, 103.0, 100.5, 102.8)]
        self.assertEqual(evaluate_signal(entry, candles), BOUNCED)

    def test_journal_store_and_summary(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "journal.json")
            j = Journal(path)
            j.add({"id": "A:1", "ts": 1000.0, "symbol": "AAAUSDT", "side": "resistance", "level": 110.0, "price": 109.0,
                   "score": 55.0, "trend": "closing", "check_minutes": 30})
            self.assertEqual(j.pending(1000.0 + 10), [])                       # too early
            self.assertEqual(len(j.pending(1000.0 + 32 * 60)), 1)              # evaluation period is over
            j.set_outcome("A:1", BOUNCED, 5000.0)
            self.assertEqual(j.pending(1000.0 + 40 * 60), [])
            self.assertEqual(Journal(path).entries()[0]["outcome"], BOUNCED)    # saved on disk
            stats = summarize(j.entries())
            self.assertEqual(stats["all"][BOUNCED], 1)
            self.assertEqual(stats["all"]["bounce_rate"], 100.0)
            csv_path = os.path.join(d, "out.csv")
            self.assertEqual(j.export_csv(csv_path), 1)
            with open(csv_path, encoding="utf-8-sig") as f:
                self.assertIn("AAAUSDT", f.read())

    def test_monitor_records_and_evaluates_signal(self):
        journal = Journal(None)
        settings = Settings(approach_candles=3.0, journal_check_minutes=1)
        api = FakeApi()
        mon = Monitor(api, lambda: settings, lambda *a: None, lambda row, s: None, lambda t: None, lambda t: None,
                      journal=journal)
        now = 80 * 5 * MIN / 1000 + 10_000
        mon.cycle(settings, now)
        self.assertEqual(len(journal.entries()), 1)
        self.assertEqual(journal.entries()[0]["symbol"], "AAAUSDT")
        self.assertGreater(journal.entries()[0]["score"], 0)


class ChartSceneTest(unittest.TestCase):
    def test_scene_maps_prices_to_canvas(self):
        candles = [candle(i, 101.0, 99.0, close=100.0) for i in range(10)]
        scene = build_scene(candles, [Level(RESISTANCE, 100.5, 2, 5, score=60.0), Level(SUPPORT, 500.0, 2, 5)], 100.0, 400, 300)
        self.assertEqual(len(scene.candles), 10)
        self.assertEqual(len(scene.lines), 1)                 # the far level is outside the view
        self.assertLess(scene.lines[0][0], scene.price_y)      # a higher price is drawn higher (smaller y)
        x_values = [c[0] for c in scene.candles]
        self.assertEqual(x_values, sorted(x_values))

    def test_empty_scene(self):
        self.assertEqual(build_scene([], [], None, 400, 300).candles, [])


class ToleranceInMonitorTest(unittest.TestCase):
    def test_defaults(self):
        s = Settings()
        self.assertEqual(s.tolerance_mode, "candles")
        self.assertTrue(s.approach_filter_enabled)
        self.assertTrue(s.minimize_to_tray)


if __name__ == "__main__":
    unittest.main()
