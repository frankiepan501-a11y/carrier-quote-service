# -*- coding: utf-8 -*-
"""货代报价解析服务 (Zeabur)。
物流在飞书「货代报价快照库」自助上传报价单 → 本服务扫描待解析记录 →
下载附件 → 按货代解析模板抽单价 → 与「货代单价字典」旧版 diff → upsert →
回写解析状态 + 飞书通知物流变动。"""
import os
import io
import json
import time

import openpyxl
from fastapi import FastAPI, Header, HTTPException, Query

import feishu
import parsers

APP_TOKEN = os.environ.get("APP_TOKEN", "")
SNAP_TABLE = os.environ.get("SNAP_TABLE", "")
DICT_TABLE = os.environ.get("DICT_TABLE", "")
BEARER = os.environ.get("BEARER", "")
NOTIFY_OID = os.environ.get("NOTIFY_OID", "")   # 物流仓储主管 张灿煊 (聪哥1号 namespace)

app = FastAPI(title="carrier-quote-service")


def nz(v):
    if isinstance(v, list):
        return "".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in v)
    if isinstance(v, dict):
        return v.get("text", "")
    return v if v is not None else ""


def _key(e):
    return (e["服务商"], e["渠道"], e.get("仓库代码", ""), e["计费重档下限"])


def _check_auth(authorization):
    if not BEARER:
        return
    if authorization != "Bearer " + BEARER:
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/health")
def health():
    return {"ok": True, "snap": SNAP_TABLE, "dict": DICT_TABLE,
            "templates": ["|".join(k) for k in parsers.DISPATCH.keys()]}


@app.post("/parse/scan")
def scan(authorization: str = Header(None),
         force: int = Query(0, description="1=连已解析也重跑"),
         dry_run: int = Query(0, description="1=只算不写库不通知")):
    _check_auth(authorization)
    now = int(time.time() * 1000)
    snaps = feishu.list_records(APP_TOKEN, SNAP_TABLE)
    # 预读全字典一次，按 (服务商,渠道) 索引
    dict_rows = feishu.list_records(APP_TOKEN, DICT_TABLE)
    by_channel = {}
    for it in dict_rows:
        f = it["fields"]
        ck = (nz(f.get("服务商")), nz(f.get("渠道")))
        by_channel.setdefault(ck, []).append(it)

    results = []
    for snap in snaps:
        f = snap["fields"]
        ven = nz(f.get("货代"))
        line = nz(f.get("线路"))
        status = nz(f.get("解析状态"))
        # 物流新上传时解析状态为空；空 或 待解析 都处理，已解析/失败/归档则跳过(除非 force)
        if status not in ("", "待解析") and not force:
            continue
        rid = snap["record_id"]
        att = f.get("报价单附件") or []
        if not att:
            _mark(rid, "解析失败", now, "无附件", dry_run)
            results.append({"snap": rid, "ven": ven, "line": line, "status": "解析失败", "reason": "无附件"})
            continue
        try:
            blob = feishu.download_media(att[0]["file_token"])
            wb = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
            ents = parsers.parse(wb, ven, line)
            wb.close()
        except Exception as e:
            _mark(rid, "解析失败", now, "解析异常:" + str(e)[:80], dry_run)
            results.append({"snap": rid, "ven": ven, "line": line, "status": "解析失败", "reason": str(e)[:120]})
            continue
        if not ents:
            _mark(rid, "解析失败", now, "无模板/0条", dry_run)
            results.append({"snap": rid, "ven": ven, "line": line, "status": "解析失败", "reason": "无模板或0条"})
            continue

        channels = parsers.CHANNELS.get((ven, line), [])
        old = {}
        old_rids = []
        for ck in channels:
            for it in by_channel.get(ck, []):
                of = it["fields"]
                old[(nz(of.get("服务商")), nz(of.get("渠道")), nz(of.get("仓库代码")),
                     float(nz(of.get("计费重档下限")) or 0))] = float(nz(of.get("单价")) or 0)
                old_rids.append(it["record_id"])
        new = {_key(e): e["单价"] for e in ents}
        added = [k for k in new if k not in old]
        removed = [k for k in old if k not in new]
        changed = [(k, old[k], new[k]) for k in new if k in old and abs(old[k] - new[k]) > 0.001]
        summary = "新增%d 删除%d 改价%d 条目%d" % (len(added), len(removed), len(changed), len(ents))
        if changed:
            ex = changed[:5]
            summary += " | 改价示例:" + "; ".join("%s/%s %s→%s" % (k[1], k[2], a, b) for k, a, b in ex)

        if not dry_run:
            # 全替换该(货代,线路)的渠道：删旧 + 插新
            if old_rids:
                feishu.batch_delete(APP_TOKEN, DICT_TABLE, old_rids)
            recs = []
            for e in ents:
                rec = {k: v for k, v in e.items() if v not in (None, "")}
                rec["生效日期"] = f.get("生效日期") or now
                rec["来源快照"] = [rid]
                recs.append({"fields": rec})
            feishu.batch_create(APP_TOKEN, DICT_TABLE, recs)
            _mark(rid, "已解析", now, summary, dry_run)

        results.append({"snap": rid, "ven": ven, "line": line, "status": "已解析",
                        "entries": len(ents), "added": len(added), "removed": len(removed),
                        "changed": len(changed), "summary": summary})

    # 通知物流（有变动且非 dry_run）
    notes = [r for r in results if r.get("status") == "已解析" and
             (r.get("added") or r.get("removed") or r.get("changed"))]
    if notes and not dry_run and NOTIFY_OID:
        msg = "📦 货代报价单已自动解析进单价字典：\n\n" + "\n".join(
            "• %s/%s：%s" % (r["ven"], r["line"], r["summary"]) for r in notes)
        feishu.send_text(NOTIFY_OID, msg)

    return {"scanned": len(snaps), "processed": len(results), "results": results}


def _mark(rid, status, now, summary, dry_run):
    if dry_run:
        return
    # 单选独立 PUT，防清空
    feishu.update_record(APP_TOKEN, SNAP_TABLE, rid, {"解析状态": status})
    feishu.update_record(APP_TOKEN, SNAP_TABLE, rid, {"解析时间": now, "变动摘要": summary[:480]})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
