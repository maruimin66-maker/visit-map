---
name: visit-map
description: 拜访地图工具——在高德工作地图(wia.amap.com)上管理客户/伙伴标记与拜访路线。客户=红色、伙伴=蓝色。当用户要求"标记客户/伙伴地址"、"查拜访点"、"规划拜访路线"时使用。
argument-hint: "[add 客户|伙伴 名称 地址 | list | del]"
auto_execution_mode: 3
allowed-tools:
  - exec
  - read
  - write
triggers:
  - user
  - model
---

# visit-map 拜访地图

在高德工作地图（wia.amap.com「ITrocker」）上标记客户/伙伴地址并管理拜访路线。**零 pip 依赖**（只用 Python3 标准库），可在任何有 `python3` + 外网的环境运行：本机、Devin、豆包办公等云端 agent。

## 安装（云端 agent 三步）

```bash
git clone <本仓库> && cd visit-map      # 或拷贝 SKILL.md + visit_map.py + config.json
export AMAP_WIA_COOKIE="passport_login=...; tfstk=..."   # 管理员提供
python3 visit_map.py check             # 应返回 "login": true
```

## 凭据（二选一，自动探测优先级 openapi > session）

### AMAP_WIA_COOKIE（当前主用）

- 已登录 wia.amap.com 会话的 cookie 头原文，必须含 `passport_login`
- 本机：`python3 visit_map.py export-cookie` 从 `~/.config/visit-map/cookies.json` 生成环境变量行
- 云端：由管理员通过密钥管理器/环境变量注入；**禁止写入代码/日志/文档**
- 有效期约 1 年（`passport_login` httpOnly cookie）；失效后需人工重新登录浏览器再导出

### 官方 OpenAPI（长期升级路径）

`~/.config/secrets.env`：`AMAP_WIA_KEY`（高德开放平台 Web服务 key，需企业认证）、`AMAP_WIA_BIZ_TOKEN` / `AMAP_WIA_BIZ_SECRET`（wia.amap.com 组织设置，仅管理员）、`AMAP_WIA_OPEN_ID`。配齐后自动启用，无需 cookie。

## 用法

```bash
python3 visit_map.py check                              # 登录态/后端/uid
python3 visit_map.py add partner  "卓豪北京" "海淀区后屯路28号院1号楼"
python3 visit_map.py add customer "某公司"   "地址或POI名" --desc "备注"
python3 visit_map.py list [--kw 关键词] [--city 北京] [--type customer]
python3 visit_map.py geocode "详细地址" [--city 北京]
python3 visit_map.py del <resourceId>
python3 visit_map.py export-cookie                      # cookies.json → env 行
```

约定：用户发"伙伴/客户：xxx，地址yyy"→ 直接 `add`；地址不清先 `geocode` 给候选确认。输出均为 JSON，便于 agent 消费。

## 颜色与数据约定

- 伙伴蓝 `#7E97FF,#4265FF`、客户红 `#FF6968,#F74746`（config.json `colors`）
- 地图标识：workMapId / 内部 mapId / orgId / dimensionId 均在 `config.json`，可用 `AMAP_WIA_*` 环境变量覆盖（见 `load_config` 的 env_map）
- `add` 自动：POI 搜索定位 → 全量查重（同名/同址跳过）→ 创建 → 返回 resourceId

## 内部接口（实测，body 均包 `args:[{...}]`）

- `GET /api/user/getUserInfo` → `code:1` 已登录 / `code:14` 未登录
- `POST /api/search/sug` `{words, longitude, latitude}` → POI 候选
- `POST /api/resource/resource/createResource` → `{data:{resourceId}}`
- `POST /api/resource/resourceList/fetchResourceListByCategory` → 分页 `resourceList/hasMore`
- `POST /api/resource/resource/deleteResource` `{resourceId, workMapId, mapId, type:'point'}`

## cookie 首次获取（管理员，一次性）

1. 浏览器登录 wia.amap.com（账密需过阿里滑块，真人操作；勾选"下次自动登录"）
2. DevTools 或 playwright `context.cookies()` 导出 `.amap.com` 域 cookie
3. 写入本机 `~/.config/visit-map/cookies.json`（`chmod 600`），或直接组装 `k=v; k=v` 注入 `AMAP_WIA_COOKIE`

**不要尝试账密自动登录**：阿里滑块风控（F019）会拒绝自动化拖动。

## 测试

```bash
python3 tests/unit/test_core.py            # 签名/cookie/查重/报文（无网络）
python3 tests/integration/test_live.py     # 真实会话（需 cookie，无则跳过）
```

## 故障排查

- `code 14 / Not login` → cookie 失效或缺 `passport_login`，重新导出
- `code 0 / 网络异常` → 已自动重试 3 次；持续出现说明风控拦截，换网络或更新 cookie
- `skipped:true` → 已存在同名/同地址标记，属正常去重
- OpenAPI `biz sign error` → 参数值按 `SIGN_PARAMS` 顺序拼接 + `@` + bizSecret → URL编码 → MD5大写

## 拜访路线规划（TODO）

官方 `map/line/create`（pointInfoList + planRoute:true）。流程：`list --city 北京` → 选点 → 建路线，高德 App 地图小程序内查看导航。
