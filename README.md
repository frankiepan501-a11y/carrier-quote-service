# carrier-quote-service

货代报价解析服务。物流在飞书「货代报价快照库」自助上传报价单 xlsx → 本服务扫描待解析记录 → 下载附件 → 按货代解析模板抽单价 → 与「货代单价字典」旧版 diff → upsert → 回写解析状态 + 飞书通知物流变动。

## 端点
- `GET /health` — 健康检查 + 已装解析模板
- `POST /parse/scan` — 扫快照库（Header `Authorization: Bearer <BEARER>`）
  - `?force=1` 连已解析也重跑
  - `?dry_run=1` 只算不写库不通知

## 环境变量
`FEISHU_APP_ID` / `FEISHU_APP_SECRET`（聪哥1号）/ `APP_TOKEN`（发货进度管理台 base）/ `SNAP_TABLE`（货代报价快照库）/ `DICT_TABLE`（货代单价字典）/ `BEARER`（端点鉴权）/ `NOTIFY_OID`（物流仓储主管 open_id，变动通知）

## 解析模板（parsers.py，已用 2026-06 真实票 A/B 对账验证）
| 货代 | 线路 | 渠道 |
|---|---|---|
| 安君 | 美国 | 以星限时达-卡派 / 以星限时达-快递派(分区) / COSCO,EMC-卡派 / 美东极速达 |
| 安君 | 加拿大 | 美转加OA定提限时达 卡派 |
| 云驼 | 欧线 | 中英卡航卡派递延 / 中欧卡航卡派递延 / 海卡递延-固定申报 |
| 墨客多 | 墨西哥 | MM3(按方CBM) |

新货代/线路在 `parsers.py` 的 `DISPATCH` + `CHANNELS` 扩展。
