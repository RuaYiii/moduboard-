import random
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from modules import sys_kline


class FakeFrame:
    def __init__(self, rows):
        self.rows = rows

    def tail(self, limit):
        return FakeFrame(self.rows[-limit:])

    def iterrows(self):
        return enumerate(self.rows)


class SysKlineTests(unittest.TestCase):
    def setUp(self):
        sys_kline._CANDLE_CACHE.clear()
        sys_kline._FAILURE_CACHE.clear()

    def test_symbol_field_uses_cascading_selector(self):
        symbol_field = next(field for field in sys_kline.META["config_fields"] if field["key"] == "symbol")
        self.assertEqual(symbol_field["type"], "online-symbol-cascading-select")

    def test_parse_symbol_accepts_cascade_and_legacy_values(self):
        self.assertEqual(
            sys_kline._parse_symbol("CZCE.FG2609 玻璃2609"),
            ("CZCE.FG2609", "futures_cn", "CZCE", "FG2609"),
        )
        self.assertEqual(
            sys_kline._parse_symbol("【股】SZSE.002624 完美世界"),
            ("SZSE.002624", "stock_cn", "SZSE", "002624"),
        )
        self.assertEqual(
            sys_kline._parse_symbol("sh600519"),
            ("SSE.600519", "stock_cn", "SSE", "600519"),
        )

    def test_futures_fetch_uses_uppercase_provider_symbol(self):
        futures_daily = Mock(return_value=FakeFrame([
            {"date": "2026-08-20", "open": 3200, "high": 3250, "low": 3180, "close": 3230, "volume": 1234},
        ]))
        fake_akshare = SimpleNamespace(futures_zh_daily_sina=futures_daily)

        with patch.dict(sys.modules, {"akshare": fake_akshare}):
            candles, error, source = sys_kline._try_fetch_candles("SHFE.rb2610 螺纹2610", "daily")

        futures_daily.assert_called_once_with(symbol="RB2610")
        self.assertIsNone(error)
        self.assertEqual(source, "live")
        self.assertEqual(candles[0]["time"], "2026-08-20")

    def test_stock_fetch_uses_stock_api_and_chinese_columns(self):
        stock_daily = Mock(return_value=FakeFrame([
            {"日期": "2026-08-20", "开盘": 1500, "最高": 1520, "最低": 1490, "收盘": 1510, "成交量": 4567},
        ]))
        fake_akshare = SimpleNamespace(stock_zh_a_hist=stock_daily)

        with patch.dict(sys.modules, {"akshare": fake_akshare}):
            candles, error, source = sys_kline._try_fetch_candles("SSE.600519 贵州茅台", "daily")

        kwargs = stock_daily.call_args.kwargs
        self.assertEqual(kwargs["symbol"], "600519")
        self.assertEqual(kwargs["period"], "daily")
        self.assertEqual(kwargs["adjust"], "")
        self.assertIsNone(error)
        self.assertEqual(source, "live")
        self.assertEqual(candles[0]["close"], 1510.0)

    def test_minute_rows_are_sorted_deduplicated_and_timestamped_in_china_timezone(self):
        frame = FakeFrame([
            {"时间": "2026-08-21 09:35:00", "开盘": 11, "最高": 13, "最低": 10, "收盘": 12, "成交量": 20},
            {"时间": "2026-08-21 09:30:00", "开盘": 10, "最高": 12, "最低": 9, "收盘": 11, "成交量": 10},
            {"时间": "2026-08-21 09:35:00", "开盘": 12, "最高": 14, "最低": 11, "收盘": 13, "成交量": 30},
            {"时间": "2026-08-21 09:40:00", "开盘": float("nan"), "最高": 14, "最低": 11, "收盘": 13, "成交量": 30},
            {"时间": "2026-08-21 09:45:00", "开盘": 10, "最高": 9, "最低": 8, "收盘": 11, "成交量": 30},
            {"时间": "2026-08-21 09:50:00", "开盘": 10, "最高": 11, "最低": 9, "收盘": 10, "成交量": -1},
        ])

        candles = sys_kline._frame_to_candles(frame, is_daily=False)

        expected = int(datetime(2026, 8, 21, 9, 30, tzinfo=timezone(timedelta(hours=8))).timestamp())
        self.assertEqual([c["time"] for c in candles], [expected, expected + 300])
        self.assertEqual(candles[-1]["volume"], 30.0)

    def test_mock_generation_does_not_mutate_global_random_state(self):
        before = random.getstate()
        candles = sys_kline._gen_mock_candles(n=500, base_price=100, seed=7, interval=300)
        after = random.getstate()

        self.assertEqual(before, after)
        self.assertEqual(candles[1]["time"] - candles[0]["time"], 300)
        self.assertGreater(min(candle["low"] for candle in candles), 0)

    def test_failed_requests_are_briefly_cached(self):
        futures_daily = Mock(side_effect=RuntimeError("temporary outage"))
        fake_akshare = SimpleNamespace(futures_zh_daily_sina=futures_daily)

        with patch.dict(sys.modules, {"akshare": fake_akshare}):
            first = sys_kline._try_fetch_candles("SHFE.rb2610", "daily")
            second = sys_kline._try_fetch_candles("SHFE.rb2610", "daily")

        self.assertEqual(first[2], "error")
        self.assertEqual(second[2], "error")
        self.assertEqual(futures_daily.call_count, 1)

    def test_period_action_validates_and_returns_config_update(self):
        config = {"symbol": "SHFE.rb2610", "period": "5m"}
        fake_candles = [{"time": "2026-08-20", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10}]
        with patch.object(sys_kline, "_try_fetch_candles", return_value=(fake_candles, None, "live")):
            result = sys_kline.on_action("switch_period", {"period": "not-valid"}, config, {})

        self.assertEqual(result["config"]["period"], "daily")
        self.assertEqual(result["state"]["last_period"], "daily")

    def test_html_escapes_symbol_and_error_tooltip(self):
        candles = [{"time": "2026-08-20", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10}]
        rendered = sys_kline._build_html('<img src=x onerror="boom">', "daily", candles, "mock", 'bad" onmouseover="boom')

        self.assertNotIn("<img src=x", rendered)
        self.assertNotIn('title="bad" onmouseover=', rendered)
        self.assertIn("模拟数据", rendered)


if __name__ == "__main__":
    unittest.main()
