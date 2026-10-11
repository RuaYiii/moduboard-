import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import online_symbols


class FakeFrame:
    def __init__(self, rows):
        self.rows = rows

    def iterrows(self):
        return enumerate(self.rows)


class OnlineSymbolTests(unittest.TestCase):
    def setUp(self):
        online_symbols.clear_caches()

    @staticmethod
    def _rules_frame():
        return FakeFrame([
            {"交易所": "上海期货交易所", "品种": "螺纹钢", "代码": "rb"},
            {"交易所": "上海国际能源交易中心", "品种": "原油", "代码": "sc"},
            {"交易所": "广州期货交易所", "品种": "工业硅", "代码": "si"},
            {"交易所": "中国金融期货交易所", "品种": "沪深300", "代码": "IF"},
        ])

    def test_catalog_is_built_from_online_rules_and_includes_all_asset_shells(self):
        futures_rule = Mock(return_value=self._rules_frame())
        fake_akshare = SimpleNamespace(futures_rule=futures_rule)

        with patch.dict(sys.modules, {"akshare": fake_akshare}):
            result = online_symbols.get_online_catalog(force=True)

        futures = result["tree"]["futures_cn"]["exchanges"]
        self.assertIn("RB", futures["SHFE"]["products"])
        self.assertIn("SC", futures["INE"]["products"])
        self.assertIn("SI", futures["GFEX"]["products"])
        self.assertIn("IF", futures["CFFEX"]["products"])
        self.assertEqual(
            set(result["tree"]["stock_cn"]["exchanges"]),
            {"SSE", "SZSE", "BSE"},
        )
        self.assertEqual(result["source"], "futures_rule")

    def test_contracts_are_actual_realtime_rows_not_guessed_months(self):
        realtime = Mock(return_value=FakeFrame([
            {"exchange": "SHFE", "symbol": "RB2610", "name": "螺纹钢2610"},
            {"exchange": "SHFE", "symbol": "RB2609", "name": "螺纹钢2609"},
            {"exchange": "SHFE", "symbol": "RB0", "name": "螺纹钢连续"},
            {"exchange": "SHFE", "symbol": "RB2610C3000", "name": "螺纹钢期权"},
            {"exchange": "SHFE", "symbol": "HC2610", "name": "热卷2610"},
            {"exchange": "DCE", "symbol": "RB2611", "name": "错误交易所"},
        ]))
        fake_akshare = SimpleNamespace(
            futures_rule=Mock(return_value=self._rules_frame()),
            futures_zh_realtime=realtime,
        )

        with patch.dict(sys.modules, {"akshare": fake_akshare}):
            result = online_symbols.get_online_contracts("shfe", "rb", force=True)

        self.assertEqual([row["sym"] for row in result["contracts"]], ["RB0", "RB2609", "RB2610"])
        self.assertIn("RB2610", [row["sym"] for row in result["contracts"]])
        realtime.assert_called_once_with(symbol="螺纹钢")

    def test_stock_directory_classifies_shenzhen_shanghai_and_beijing(self):
        stock_info = Mock(return_value=FakeFrame([
            {"code": 600519.0, "name": "贵州茅台"},
            {"code": "000001", "name": "平安银行"},
            {"code": "920001", "name": "北交样本"},
        ]))
        fake_akshare = SimpleNamespace(stock_info_a_code_name=stock_info)

        with patch.dict(sys.modules, {"akshare": fake_akshare}):
            shanghai = online_symbols.get_online_stocks("SSE", force=True)
            shenzhen = online_symbols.get_online_stocks("SZSE")
            beijing = online_symbols.get_online_stocks("BSE")

        self.assertEqual(shanghai["stocks"][0]["sym"], "600519")
        self.assertEqual(shenzhen["stocks"][0]["sym"], "000001")
        self.assertEqual(beijing["stocks"][0]["sym"], "920001")
        self.assertEqual(stock_info.call_count, 1)

    def test_empty_rule_name_result_falls_back_to_sina_product_name(self):
        rules = FakeFrame([
            {"交易所": "上海期货交易所", "品种": "螺纹钢期货", "代码": "RB"},
        ])
        realtime = Mock(side_effect=[
            FakeFrame([]),
            FakeFrame([{"exchange": "SHFE", "symbol": "RB2610", "name": "螺纹钢2610"}]),
        ])
        fake_akshare = SimpleNamespace(
            futures_rule=Mock(return_value=rules),
            futures_symbol_mark=Mock(return_value=FakeFrame([
                {"exchange": "SHFE", "symbol": "螺纹钢", "mark": "RB"},
            ])),
            futures_zh_realtime=realtime,
        )

        with patch.dict(sys.modules, {"akshare": fake_akshare}):
            result = online_symbols.get_online_contracts("SHFE", "RB", force=True)

        self.assertEqual(result["contracts"][0]["sym"], "RB2610")
        self.assertEqual(
            [call.kwargs["symbol"] for call in realtime.call_args_list],
            ["螺纹钢期货", "螺纹钢"],
        )


if __name__ == "__main__":
    unittest.main()
