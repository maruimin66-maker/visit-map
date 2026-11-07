#!/usr/bin/env python3
"""visit-map CLI：管理高德工作地图(wia.amap.com)拜访标记。

两种后端：
  openapi —— 官方 wia-openapi (restwia.amap.com)，凭据从 ~/.config/secrets.env 读取：
             AMAP_WIA_KEY / AMAP_WIA_BIZ_TOKEN / AMAP_WIA_BIZ_SECRET / AMAP_WIA_OPEN_ID
             另需 AMAP_KEY（普通 Web服务 key，用于地理编码）
  session —— 无头 Chromium + 已登录会话 cookie（~/.config/visit-map/cookies.json）。
             会话过期时重新人工登录一次并从已登录浏览器导出 cookie。

配置: ~/.config/visit-map/config.json
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

CONF_DIR = Path.home() / ".config" / "visit-map"
CONFIG_FILE = CONF_DIR / "config.json"
COOKIES_FILE = CONF_DIR / "cookies.json"
SECRETS_FILE = Path.home() / ".config" / "secrets.env"

RESTWIA = "https://restwia.amap.com"
AMAP_GEO = "https://restapi.amap.com"

TYPE_NAMES = {"partner": "伙伴", "customer": "客户"}

# 官方接口各自要求参与 bizSign 签名的参数名（按文档顺序）
SIGN_PARAMS = {
    "point/create": ["workMapId"],
    "point/delete": ["workMapId"],
    "point/detail": ["resourceId"],
    "point/update": ["workMapId"],
    "resource/list": ["workMapId", "openId"],
    "map/line/create": ["openId", "bizToken"],
    "category/create": ["workMapId"],
    "category/list": ["workMapId"],
    "account/openUser": ["mobile"],
    "core/info": ["workMapId"],
    "core/list": ["openId", "bizToken"],
    "org/info": ["openId"],
}


SKILL_DIR = Path(__file__).resolve().parent


def load_config():
    """配置优先级：环境变量 > ~/.config/visit-map/config.json > skill 内置 config.json。"""
    cfg = {}
    for f in (SKILL_DIR / "config.json", CONFIG_FILE):
        if f.exists():
            cfg.update(json.loads(f.read_text()))
    if not cfg:
        sys.exit("缺少 config.json（应随 skill 分发或放于 " + str(CONFIG_FILE) + "）")
    env_map = {"AMAP_WIA_ORG_ID": "org_id", "AMAP_WIA_WORK_MAP_ID": "work_map_id",
               "AMAP_WIA_MAP_ID": "map_id", "AMAP_WIA_DIMENSION_ID": "dimension_id",
               "AMAP_WIA_BASE_URL": "base_url",
               "AMAP_WIA_PARTNER_COLOR": "colors.partner",
               "AMAP_WIA_CUSTOMER_COLOR": "colors.customer"}
    for env_k, cfg_k in env_map.items():
        v = os.environ.get(env_k)
        if not v:
            continue
        if "." in cfg_k:
            a, b = cfg_k.split(".")
            cfg.setdefault(a, {})[b] = v
        else:
            cfg[cfg_k] = v
    return cfg


def load_secrets():
    env = {}
    if SECRETS_FILE.exists():
        for line in SECRETS_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def biz_sign(secret, *values):
    raw = "".join(values) + "@" + secret
    return hashlib.md5(urllib.parse.quote(raw, safe="").encode()).hexdigest().upper()


def http_form(url, params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "visit-map/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def http_json(url, params, body):
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(url + "?" + qs, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "visit-map/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


class OpenAPI:
    """官方 wia-openapi 客户端（纯 REST）。"""

    def __init__(self, cfg, secrets):
        self.cfg = cfg
        self.key = secrets.get("AMAP_WIA_KEY") or secrets.get("AMAP_KEY")
        self.geo_key = secrets.get("AMAP_KEY") or self.key
        self.biz_token = secrets.get("AMAP_WIA_BIZ_TOKEN")
        self.biz_secret = secrets.get("AMAP_WIA_BIZ_SECRET")
        self.open_id = secrets.get("AMAP_WIA_OPEN_ID")
        missing = [n for n, v in [("AMAP_WIA_KEY/AMAP_KEY", self.key),
                                  ("AMAP_WIA_BIZ_TOKEN", self.biz_token),
                                  ("AMAP_WIA_BIZ_SECRET", self.biz_secret),
                                  ("AMAP_WIA_OPEN_ID", self.open_id)] if not v]
        if missing:
            sys.exit("缺少凭据：" + ", ".join(missing) +
                     f"\n请在 {SECRETS_FILE} 中配置（获取方式见 SKILL.md）")

    def _query(self, ep):
        """构造 url 参数（含 bizSign）。"""
        q = {"key": self.key, "workMapId": self.cfg["work_map_id"],
             "bizToken": self.biz_token, "openId": self.open_id}
        sign_names = SIGN_PARAMS.get(ep, ["workMapId"])
        q["bizSign"] = biz_sign(self.biz_secret, *[q[n] for n in sign_names])
        return q

    def call(self, ep, body_params=None, json_body=None):
        url = f"{RESTWIA}/api/v1/wia/{ep}"
        q = self._query(ep)
        if json_body is not None:
            return http_json(url, q, json_body)
        return http_form(url, {**q, **(body_params or {})})

    # ---------- 地理编码 ----------
    def geocode(self, address, city=None):
        q = {"key": self.geo_key, "address": address}
        if city:
            q["city"] = city
        r = http_form(AMAP_GEO + "/v3/geocode/geo", q)
        geos = r.get("geocodes") or []
        if not geos:
            return None
        g = geos[0]
        lon, _, lat = g["location"].partition(",")
        return {"lon": lon, "lat": lat,
                "address": g.get("formatted_address", address),
                "name": g.get("formatted_address", address).split("区")[-1] or address,
                "city": g.get("city")}

    # ---------- 标记 ----------
    def list_points(self, keyword=None, city=None, typ=None):
        # 官方列表接口按文件夹分页；简化实现：分页拉全量
        out, page_num = [], 1
        while True:
            r = self.call("resource/list", json_body={
                "resourceTypes": [1],
                "pageNum": page_num, "pageSize": 50,
            })
            data = r.get("data") or {}
            items = data.get("resourceList") or data.get("list") or []
            out.extend(items)
            if len(items) < 50 or page_num >= 20:
                break
            page_num += 1
        res = []
        for it in out:
            pi = it.get("pointInfo") or {}
            color = it.get("color") or it.get("resourceColor", "")
            t = "伙伴" if "BLUE" in color or color == self.cfg["colors"]["partner"] else \
                ("客户" if "RED" in color or color == self.cfg["colors"]["customer"] else "其他")
            rec = {"name": it.get("title") or it.get("resourceName"),
                   "type": t, "address": pi.get("address") or it.get("address"),
                   "city": pi.get("city_name") or pi.get("city"),
                   "lon": pi.get("lon"), "lat": pi.get("lat"),
                   "resourceId": it.get("resourceId")}
            if keyword and keyword not in (rec["name"] or "") and keyword not in (rec["address"] or ""):
                continue
            if city and city not in (rec["city"] or "") and city not in (rec["address"] or ""):
                continue
            if typ and rec["type"] != TYPE_NAMES[typ]:
                continue
            res.append(rec)
        return res

    def add_point(self, typ, title, address=None, desc=""):
        # 官方颜色枚举
        color_enum = {"partner": "BLUE_1", "customer": "RED_2"}[typ]
        point_info = None
        if address:
            g = self.geocode(address)
            if g:
                point_info = {"longitude": g["lon"], "latitude": g["lat"],
                              "lon": g["lon"], "lat": g["lat"],
                              "name": title, "address": g["address"],
                              "originalName": title}
        if not point_info:
            sys.exit(f"地址解析失败：{address}，请提供更详细地址")
        body = {
            "title": title, "desc": desc, "color": color_enum,
            "pointInfoStr": json.dumps(point_info, ensure_ascii=False),
        }
        r = self.call("point/create", body_params=body)
        if r.get("code") != 1:
            sys.exit("创建失败：" + json.dumps(r, ensure_ascii=False)[:400])
        return {"name": title, "type": TYPE_NAMES[typ], "address": point_info["address"],
                "lon": point_info["lon"], "lat": point_info["lat"], "resp": r.get("data")}

    def del_point(self, resource_id):
        r = self.call("point/delete", body_params={"resourceId": resource_id})
        return {"deleted": resource_id, "ok": r.get("code") == 1, "raw": r}


WIA_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
          "AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/131.0.0.0 Safari/537.36")


def load_cookie():
    """cookie 来源：AMAP_WIA_COOKIE 环境变量（Cookie 头原文）> cookies.json。"""
    env = os.environ.get("AMAP_WIA_COOKIE", "").strip()
    if env:
        return env
    if COOKIES_FILE.exists():
        arr = json.loads(COOKIES_FILE.read_text())
        return "; ".join(f"{c['name']}={c['value']}" for c in arr)
    return ""


class SessionAPI:
    """纯 HTTP cookie 会话，调用 wia.amap.com 内部接口（已实测可用，零依赖）。"""

    def __init__(self, cfg, *_):
        self.cfg = cfg
        self.cookie = load_cookie()
        if not self.cookie:
            sys.exit("缺少会话 cookie：\n"
                     "  方式1：环境变量 AMAP_WIA_COOKIE='k1=v1; k2=v2'（云端）\n"
                     "  方式2：" + str(COOKIES_FILE) + "（本机，visit_map.py export-cookie 可生成）\n"
                     "获取：登录 wia.amap.com 后导出 amap.com 域 cookie（需含 passport_login）")
        me = self.call("GET /api/user/getUserInfo")
        if me.get("code") != 1:
            sys.exit("会话已失效（Not login）。请重新登录 wia.amap.com 并更新 cookie")
        self.user = (me.get("profile") or {})

    def call(self, ep, body=None):
        """ep 形如 'POST /api/xxx' 或 'GET /api/xxx'；body 为 args 内层 dict。"""
        method, path = ep.split(" ", 1)
        data = json.dumps({"args": [body]}).encode() if body is not None else None
        last = None
        for _ in range(3):
            req = urllib.request.Request(
                self.cfg["base_url"] + path, data=data, method=method,
                headers={"Content-Type": "application/json",
                         "Cookie": self.cookie,
                         "User-Agent": WIA_UA,
                         "Referer": self.cfg["base_url"] + "/",
                         "Origin": self.cfg["base_url"]})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    out = json.loads(r.read().decode())
            except Exception as e:  # 网络层错误重试
                last = {"code": -1, "message": str(e)}
                continue
            if out.get("code") != 0:  # code:0 = 网络异常（风控未就绪等）
                return out
            last = out
        return last

    def sug(self, words, lon=116.4, lat=39.99):
        r = self.call("POST /api/search/sug",
                      {"words": words, "longitude": lon, "latitude": lat})
        return (r.get("data") or []) if r.get("code") == 1 else []

    def geocode(self, words, city=None):
        q = f"{words} {city}" if city else words
        cands = self.sug(q)
        if not cands:
            return None
        c = cands[0]
        return {"name": c["name"], "address": c["address"],
                "city": c.get("cityname"), "district": c.get("district"),
                "lon": c["location"]["lng"], "lat": c["location"]["lat"],
                "poiid": c["id"]}

    def list_points(self, keyword=None, city=None, typ=None):
        out, page_num, more = [], 1, True
        while more and page_num <= 8:
            r = self.call("POST /api/resource/resourceList/fetchResourceListByCategory", {
                "categoryIds": ["-1"], "memberIds": [], "states": [], "customizeQuery": "",
                "sortType": 0, "principalIds": [],
                "resourceTimeQuery": '{"timeType":1,"beginTime":null,"endTime":null}',
                "mapId": self.cfg["map_id"], "workMapId": self.cfg["work_map_id"],
                "pageNum": page_num, "pageSize": 50,
                "resourceTypeList": [1, 2, 4, 7, 8], "needDefaultIconColorValue": False})
            d = r.get("data") or {}
            out.extend(d.get("resourceList") or [])
            more = d.get("hasMore")
            page_num += 1
        res = []
        for it in out:
            pi = it.get("pointInfo") or {}
            color = it.get("resourceColor", "")
            t = "伙伴" if color == self.cfg["colors"]["partner"] else \
                ("客户" if color == self.cfg["colors"]["customer"] else "其他")
            rec = {"name": it.get("resourceName"), "type": t,
                   "address": pi.get("address"), "city": pi.get("city"),
                   "lon": pi.get("lon"), "lat": pi.get("lat"),
                   "resourceId": it.get("resourceId")}
            if keyword and keyword not in (rec["name"] or "") \
                    and keyword not in (rec["address"] or ""):
                continue
            if city and city not in (rec["city"] or "") \
                    and city not in (rec["address"] or ""):
                continue
            if typ and rec["type"] != TYPE_NAMES[typ]:
                continue
            res.append(rec)
        return res

    def add_point(self, typ, title, address=None, desc=""):
        g = self.geocode(address or title)
        if not g:
            sys.exit(f"POI 搜索无结果：{address or title}，请提供更详细地址")
        dup = [p for p in self.list_points()
               if p["name"] == title or (p["address"] and g["address"] in p["address"])]
        if dup:
            return {"skipped": True, "reason": "已存在同名/同地址标记", "existing": dup}
        color = self.cfg["colors"][typ]
        point_info = {"longitude": g["lon"], "latitude": g["lat"],
                      "lon": g["lon"], "lat": g["lat"],
                      "name": g["name"], "address": g["address"],
                      "originalName": g["name"], "poiid": g.get("poiid", "")}
        r = self.call("POST /api/resource/resource/createResource", {
            "workMapId": self.cfg["work_map_id"], "mapId": self.cfg["map_id"],
            "resourceId": "", "resourceType": 1, "categoryId": "",
            "title": title,
            "address": f"{g.get('city','')}{g.get('district','')}{g['address']}",
            "desc": desc, "color": color, "iconOutline": "1", "iconFiller": "15",
            "iconFillerShowType": 3, "iconFillerValue": "15", "iconFillerId": "15",
            "showImageSwitch": 1, "imgListStr": "[]",
            "dimensionId": self.cfg["dimension_id"],
            "principalIdListJsonString": "[]", "workItemEntitys": "[]",
            "customFieldValueInfo": "",
            "pointInfoStr": json.dumps(point_info, ensure_ascii=False),
            "type": "point", "version": ""})
        if r.get("code") != 1:
            sys.exit("创建失败：" + json.dumps(r, ensure_ascii=False)[:400])
        return {"name": title, "type": TYPE_NAMES[typ],
                "poi": g["name"], "address": g["address"],
                "lon": g["lon"], "lat": g["lat"],
                "resourceId": r["data"]["resourceId"]}

    def del_point(self, resource_id):
        r = self.call("POST /api/resource/resource/deleteResource", {
            "resourceId": resource_id, "workMapId": self.cfg["work_map_id"],
            "mapId": self.cfg["map_id"], "type": "point"})
        return {"deleted": resource_id, "ok": r.get("code") == 1, "raw": r}


def choose_backend(cfg, secrets):
    if all(secrets.get(k) for k in
           ("AMAP_WIA_BIZ_TOKEN", "AMAP_WIA_BIZ_SECRET", "AMAP_WIA_OPEN_ID")) and \
       (secrets.get("AMAP_WIA_KEY") or secrets.get("AMAP_KEY")):
        return OpenAPI(cfg, secrets), "openapi"
    if load_cookie():
        return SessionAPI(cfg), "session"
    sys.exit("无可用后端：\n"
             "1) 会话模式：export AMAP_WIA_COOKIE='k=v; ...' 或写入 " +
             str(COOKIES_FILE) + "\n"
             "2) OpenAPI：在 " + str(SECRETS_FILE) + " 配置 "
             "AMAP_WIA_KEY/AMAP_WIA_BIZ_TOKEN/AMAP_WIA_BIZ_SECRET/AMAP_WIA_OPEN_ID")


def main():
    ap = argparse.ArgumentParser(prog="visit-map")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sp = sub.add_parser("list")
    sp.add_argument("--kw"); sp.add_argument("--city")
    sp.add_argument("--type", choices=["partner", "customer"])
    sp = sub.add_parser("geocode"); sp.add_argument("address"); sp.add_argument("--city")
    sp = sub.add_parser("add")
    sp.add_argument("type", choices=["partner", "customer"])
    sp.add_argument("title"); sp.add_argument("address", nargs="?")
    sp.add_argument("--desc", default="")
    sp = sub.add_parser("del"); sp.add_argument("resource_id")
    sub.add_parser("export-cookie",
                   help="从 cookies.json 生成 AMAP_WIA_COOKIE 环境变量行（供云端粘贴）")
    a = ap.parse_args()

    if a.cmd == "export-cookie":
        ck = load_cookie()
        if not ck:
            sys.exit("无 cookie 可导出：" + str(COOKIES_FILE) + " 不存在")
        print("AMAP_WIA_COOKIE=" + json.dumps(ck, ensure_ascii=False))
        sys.exit(0)

    cfg = load_config()
    secrets = load_secrets()
    api, backend = choose_backend(cfg, secrets)

    if a.cmd == "check":
        out = {"backend": backend, "workMapId": cfg["work_map_id"],
               "login": True,
               "uid": getattr(api, "user", {}).get("uid"),
               "nickname": getattr(api, "user", {}).get("nickname")}
    elif a.cmd == "list":
        out = api.list_points(a.kw, a.city, a.type)
    elif a.cmd == "geocode":
        out = api.geocode(a.address, a.city)
    elif a.cmd == "add":
        out = api.add_point(a.type, a.title, a.address, a.desc)
    elif a.cmd == "del":
        out = api.del_point(a.resource_id)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
