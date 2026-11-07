"""集成测试：真实 wia.amap.com 会话（需要有效 cookie）。

运行：AMAP_WIA_COOKIE='...' python3 tests/integration/test_live.py
无 cookie 时全部跳过。
"""
import sys
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL))
import visit_map as vm  # noqa: E402


@unittest.skipUnless(vm.load_cookie(), "无 AMAP_WIA_COOKIE 或 cookies.json")
class TestLiveSession(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = vm.SessionAPI(vm.load_config())

    def test_login(self):
        self.assertTrue(self.api.user.get("uid"))

    def test_sug(self):
        cands = self.api.sug("凯旋城C座")
        self.assertTrue(cands)
        self.assertIn("location", cands[0])

    def test_list(self):
        pts = self.api.list_points()
        self.assertGreater(len(pts), 200)
        self.assertTrue(all("resourceId" in p for p in pts))


if __name__ == "__main__":
    unittest.main()
