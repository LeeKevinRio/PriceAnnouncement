import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import bot


_BASE_YAML = """\
defaults:
  origin: TPE
  adults: 2
  cabin: ECONOMY
  currency: TWD

watches:
  - name: 大阪
    destination: KIX
    depart_window_days: 180
    stay_days: [4, 5, 6, 7]
    max_price: 15000
"""


class BotCommandsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.watchlist = Path(self.tmp) / "watchlist.yaml"
        self.watchlist.write_text(_BASE_YAML, encoding="utf-8")
        self._patch = mock.patch.object(bot, "_WATCHLIST", self.watchlist)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        shutil.rmtree(self.tmp)

    def test_help_returns_text(self):
        self.assertIn("可用指令", bot._help())

    def test_list_shows_existing_watch(self):
        out = bot._list()
        self.assertIn("大阪", out)
        self.assertIn("KIX", out)

    def test_add_minimal_required_fields(self):
        out = bot._add("name=首爾 dest=ICN price=12000")
        self.assertIn("✅", out)
        self.assertIn("首爾", out)
        # Verify it landed in the file
        data = bot._read_watchlist()
        names = [w["name"] for w in data["watches"]]
        self.assertIn("首爾", names)

    def test_add_with_all_options(self):
        bot._add(
            "name=曼谷 dest=BKK price=12000 stays=4,5,6 origin=TSA "
            "adults=2 airlines=CI,BR direct=yes days=120"
        )
        data = bot._read_watchlist()
        bkk = next(w for w in data["watches"] if w["name"] == "曼谷")
        self.assertEqual(bkk["destination"], "BKK")
        self.assertEqual(bkk["origin"], "TSA")
        self.assertEqual(bkk["stay_days"], [4, 5, 6])
        self.assertEqual(bkk["airlines_allow"], ["CI", "BR"])
        self.assertTrue(bkk["direct_only"])
        self.assertEqual(bkk["depart_window_days"], 120)

    def test_add_rejects_missing_required(self):
        out = bot._add("dest=ICN price=12000")
        self.assertIn("缺少必要欄位", out)

    def test_add_with_existing_name_updates(self):
        bot._add("name=大阪 dest=KIX price=18000")
        data = bot._read_watchlist()
        kix = next(w for w in data["watches"] if w["name"] == "大阪")
        self.assertEqual(kix["max_price"], 18000)

    def test_remove_existing(self):
        out = bot._remove("大阪")
        self.assertIn("✅", out)
        data = bot._read_watchlist()
        self.assertEqual(data["watches"], [])

    def test_remove_nonexistent(self):
        out = bot._remove("不存在")
        self.assertIn("找不到", out)

    def test_setprice(self):
        out = bot._setprice("大阪 18000")
        self.assertIn("18,000", out)
        data = bot._read_watchlist()
        kix = next(w for w in data["watches"] if w["name"] == "大阪")
        self.assertEqual(kix["max_price"], 18000)

    def test_setprice_with_commas_in_input(self):
        bot._setprice("大阪 18,500")
        data = bot._read_watchlist()
        kix = next(w for w in data["watches"] if w["name"] == "大阪")
        self.assertEqual(kix["max_price"], 18500)

    def test_setairlines_set(self):
        bot._setairlines("大阪 CI,BR,JX")
        data = bot._read_watchlist()
        kix = next(w for w in data["watches"] if w["name"] == "大阪")
        self.assertEqual(kix["airlines_allow"], ["CI", "BR", "JX"])

    def test_setairlines_clear(self):
        bot._setairlines("大阪 CI")
        bot._setairlines("大阪 none")
        data = bot._read_watchlist()
        kix = next(w for w in data["watches"] if w["name"] == "大阪")
        self.assertNotIn("airlines_allow", kix)

    def test_setdirect_on(self):
        bot._setdirect("大阪 on")
        data = bot._read_watchlist()
        kix = next(w for w in data["watches"] if w["name"] == "大阪")
        self.assertTrue(kix["direct_only"])

    def test_setdirect_off(self):
        bot._setdirect("大阪 on")
        bot._setdirect("大阪 off")
        data = bot._read_watchlist()
        kix = next(w for w in data["watches"] if w["name"] == "大阪")
        self.assertNotIn("direct_only", kix)

    def test_handle_dispatches_correctly(self):
        out = bot.handle("/list")
        self.assertIn("大阪", out)

    def test_handle_unknown_command(self):
        out = bot.handle("/banana")
        self.assertIn("未知指令", out)


class KvParserTest(unittest.TestCase):
    def test_parse_kv_simple(self):
        self.assertEqual(
            bot._parse_kv_args("name=首爾 dest=ICN price=12000"),
            {"name": "首爾", "dest": "ICN", "price": "12000"},
        )

    def test_parse_kv_with_csv_value(self):
        # Note: comma values in stays= must not contain spaces
        self.assertEqual(
            bot._parse_kv_args("stays=4,5,6 airlines=CI,BR")["airlines"],
            "CI,BR",
        )

    def test_parse_kv_ignores_bare_words(self):
        self.assertEqual(
            bot._parse_kv_args("hello name=X world"),
            {"name": "X"},
        )


if __name__ == "__main__":
    unittest.main()
