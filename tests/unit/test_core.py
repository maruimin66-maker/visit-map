"""visit_map 单元测试：签名、cookie 解析、配置合并、查重逻辑（无网络）。"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL))
import visit_map as vm  # noqa: E402


class TestBizSign(unittest.TestCase):
    def test_sign_format(self):
        s = vm.biz_sign("sec", "a", "b")
        self.assertEqual(len(s), 32)
        self.assertEqual(s, s.upper())

    def test_sign_concat_order(self):
        # 参数值顺序拼接 + @secret → URL编码 → md5大写
        import hashlib
        import urllib.parse
        raw = urllib.parse.quote("v1v2@sec", safe="").encode()
        expect = hashlib.md5(raw).hexdigest().upper()
        self.assertEqual(vm.biz_sign("sec", "v1", "v2"), expect)


class TestLoadCookie(unittest.TestCase):
    def test_env_priority(self):
        with patch.dict(os.environ, {"AMAP_WIA_COOKIE": "a=1; b=2"}):
            self.assertEqual(vm.load_cookie(), "a=1; b=2")

    def test_file_fallback(self):
        data = [{"name": "passport_login", "value": "X"},
                {"name": "tfstk", "value": "Y"}]
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AMAP_WIA_COOKIE", None)
            with patch.object(vm, "COOKIES_FILE") as f:
                f.exists.return_value = True
                f.read_text.return_value = json.dumps(data)
                self.assertEqual(vm.load_cookie(), "passport_login=X; tfstk=Y")

    def test_empty(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AMAP_WIA_COOKIE", None)
            with patch.object(vm, "COOKIES_FILE") as f:
                f.exists.return_value = False
                self.assertEqual(vm.load_cookie(), "")


class FakeSession(vm.SessionAPI):
    """跳过网络初始化，注入假 call 用于测查重/报文。"""

    def __init__(self, cfg, calls):
        self.cfg = cfg
        self._calls = calls
        self.user = {}

    def call(self, ep, body=None):
        return self._calls.pop(0)


def cfg():
    return {"base_url": "https://wia.amap.com", "org_id": "o",
            "work_map_id": "w", "map_id": "m", "dimension_id": "d",
            "colors": {"partner": "#7E97FF,#4265FF", "customer": "#FF6968,#F74746"}}


class TestAddPoint(unittest.TestCase):
    def test_dup_skip(self):
        api = FakeSession(cfg(), [
            {"code": 1, "data": [{"name": "X", "address": "A", "id": "p",
                                  "location": {"lng": "1", "lat": "2"}}]},
            {"code": 1, "data": {"resourceList": [
                {"resourceName": "X", "resourceId": "r1",
                 "pointInfo": {"address": "A"}, "resourceColor": ""}],
                "hasMore": False}},
        ])
        out = api.add_point("partner", "X", "A")
        self.assertTrue(out["skipped"])

    def test_create_payload(self):
        calls = [
            {"code": 1, "data": [{"name": "P", "address": "A", "id": "poi1",
                                  "location": {"lng": "116", "lat": "40"},
                                  "cityname": "北京市", "district": "朝阳区"}]},
            {"code": 1, "data": {"resourceList": [], "hasMore": False}},
            {"code": 1, "data": {"resourceId": "rid9"}},
        ]
        api = FakeSession(cfg(), calls)

        captured = {}
        real_call = api.call

        def spy(ep, body=None):
            captured[ep] = body
            return real_call(ep, body)
        api.call = spy

        out = api.add_point("customer", "T", "A")
        self.assertEqual(out["resourceId"], "rid9")
        body = captured["POST /api/resource/resource/createResource"]
        self.assertEqual(body["color"], "#FF6968,#F74746")
        self.assertEqual(body["title"], "T")
        pi = json.loads(body["pointInfoStr"])
        self.assertEqual(pi["poiid"], "poi1")
        self.assertEqual(pi["lon"], "116")


class TestListFilter(unittest.TestCase):
    def test_kw_and_color_map(self):
        api = FakeSession(cfg(), [
            {"code": 1, "data": {"resourceList": [
                {"resourceName": "卓豪北京", "resourceColor": "#7E97FF,#4265FF",
                 "pointInfo": {"address": "后屯路", "lon": "1", "lat": "2"},
                 "resourceId": "r1"},
                {"resourceName": "茉酸奶", "resourceColor": "#FF6968,#F74746",
                 "pointInfo": {"address": "某路", "lon": "3", "lat": "4"},
                 "resourceId": "r2"}],
                "hasMore": False}},
        ])
        all_pts = api.list_points()
        self.assertEqual({p["type"] for p in all_pts}, {"伙伴", "客户"})
        api._calls = [{"code": 1, "data": {"resourceList": [
            {"resourceName": "卓豪北京", "resourceColor": "#7E97FF,#4265FF",
             "pointInfo": {"address": "后屯路"}, "resourceId": "r1"},
            {"resourceName": "茉酸奶", "resourceColor": "#FF6968,#F74746",
             "pointInfo": {"address": "某路"}, "resourceId": "r2"}],
            "hasMore": False}}]
        self.assertEqual(len(api.list_points(keyword="卓豪")), 1)
        api._calls = [{"code": 1, "data": {"resourceList": [
            {"resourceName": "卓豪北京", "resourceColor": "#7E97FF,#4265FF",
             "pointInfo": {"address": "后屯路"}, "resourceId": "r1"},
            {"resourceName": "茉酸奶", "resourceColor": "#FF6968,#F74746",
             "pointInfo": {"address": "某路"}, "resourceId": "r2"}],
            "hasMore": False}}]
        self.assertEqual(len(api.list_points(typ="customer")), 1)


if __name__ == "__main__":
    unittest.main()
