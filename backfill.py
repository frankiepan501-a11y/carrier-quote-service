# -*- coding: utf-8 -*-
"""头程发货任务台 统一回填 + 对账（服务内嵌版）。
串 5 张配置表：货代单价字典 / 仓库分区表 / 票级附加费规则表 / 申报比例表 / 海关编码字典。
票首行(票级): 物流单价(字典按计费重落档,快递派经分区表换ZONE) / 报关费 / 清关费 = 对账型(空补/已填对账不覆盖)
每SKU行     : 申报金额(USD)=平台售价×数量×申报比例×汇率 / 税金=申报×税率×税金固定比例 = 计算型(始终重算覆盖)
"""
import os
from collections import OrderedDict

import feishu

APP = os.environ.get("APP_TOKEN", "")
T = "tblk0v4khUngviEE"      # 头程发货任务台
DICT = "tbl7ZHpEJ9p3euB0"   # 货代单价字典
ZT = "tblHrl611u1vp93z"     # 仓库分区表
ST = "tbl2Tro5HgBWElna"     # 票级附加费规则表
RT = "tblr2MUEuHsJzgfP"     # 申报比例表
HS = "tbl0dWGE6o4OV0rb"     # 海关编码字典
TAX_COUNTRIES = ("英国", "德国", "日本")
TOL = 0.01


def nz(v):
    if isinstance(v, list):
        return "".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in v)
    if isinstance(v, dict):
        return v.get("text", "")
    return v if v is not None else ""


def fnum(v):
    try:
        return float(nz(v))
    except Exception:
        return None


def run(dry_run=False, all_rows=False):
    DICTE = [{"sv": nz(x["fields"].get("服务商")), "ch": nz(x["fields"].get("渠道")),
              "wh": nz(x["fields"].get("仓库代码")), "low": fnum(x["fields"].get("计费重档下限")),
              "price": fnum(x["fields"].get("单价"))} for x in feishu.list_records(APP, DICT)]
    ZONEMAP = {nz(x["fields"].get("仓库代码")): nz(x["fields"].get("分区")) for x in feishu.list_records(APP, ZT)}
    SURCH = {}
    for x in feishu.list_records(APP, ST):
        f = x["fields"]
        SURCH[nz(f.get("规则名"))] = {"报关费": fnum(f.get("报关费(元/票)")), "清关费": fnum(f.get("清关费(元/票)"))}
    RATIO = {}
    for x in feishu.list_records(APP, RT):
        f = x["fields"]
        RATIO[nz(f.get("国家"))] = {"r": fnum(f.get("申报比例")), "fx": fnum(f.get("汇率到USD"))}
    TAXRATE = {}
    for x in feishu.list_records(APP, HS):
        f = x["fields"]
        code = nz(f.get("海关编码")); co = nz(f.get("国家")); rate = fnum(f.get("税率"))
        coef = fnum(f.get("税金固定比例"))
        if code and co and rate is not None:
            TAXRATE[(code, co)] = (rate, coef if coef is not None else 1.0)

    def freight_price(sv, ch, wh, w):
        cand = [e for e in DICTE if e["sv"] == sv and e["ch"] == ch and e["wh"] == wh]
        if not cand and sv == "墨客多":
            cand = [e for e in DICTE if e["sv"] == "墨客多" and e["ch"] == ch]
        if not cand:
            zone = ZONEMAP.get(wh)
            if zone:
                cand = [e for e in DICTE if e["sv"] == sv and e["ch"] == ch and e["wh"] == "ZONE:" + zone]
        if not cand:
            return None
        if sv == "墨客多":
            return cand[0]["price"]
        if w is None:
            return None
        tiers = sorted(set(e["low"] for e in cand))
        pick = tiers[0]
        for t in tiers:
            if w >= t:
                pick = t
        for e in cand:
            if e["low"] == pick:
                return e["price"]
        return None

    def surcharge(sv, co):
        if sv == "安君" and co == "加拿大": k = "安君-加拿大OA卡派"
        elif sv == "安君": k = "安君-美国卡派/快递派"
        elif sv == "云驼": k = "云驼-欧线/英国卡航递延"
        elif sv == "墨客多": k = "墨客多-MM3(DDP)"
        else: return None, None
        r = SURCH.get(k, {})
        return r.get("报关费"), r.get("清关费")

    def ratio(co):
        d = RATIO.get(co) or RATIO.get("默认") or {}
        r = d.get("r") if d.get("r") is not None else 0.3
        fx = d.get("fx") if d.get("fx") is not None else 1.0
        return r, fx

    rows = feishu.list_records(APP, T)
    if not all_rows:
        rows = [it for it in rows if "旧表迁入" in str(it["fields"].get("备注", ""))]
    groups = OrderedDict()
    for it in rows:
        groups.setdefault(nz(it["fields"].get("货件编号")), []).append(it)

    updates = OrderedDict()   # rid -> fields
    rep = {"补": 0, "对账✓": 0, "对账❗": 0, "缺": 0, "重算": 0}
    diffs = []

    def plan(rid, field, newv, oldv, label):
        if newv is None:
            rep["缺"] += 1; return
        newv = round(newv, 2)
        if oldv in (None, "", []) or fnum(oldv) is None:
            rep["补"] += 1; updates.setdefault(rid, {})[field] = newv
        elif abs(fnum(oldv) - newv) <= TOL:
            rep["对账✓"] += 1
        else:
            rep["对账❗"] += 1
            diffs.append("%s %s: 已填%s vs 算%s" % (label, field, fnum(oldv), newv))

    def plan_compute(rid, field, newv, oldv, label):
        if newv is None:
            return
        newv = round(newv, 2)
        ov = fnum(oldv)
        if ov is not None and abs(ov - newv) <= TOL:
            rep["对账✓"] += 1; return
        rep["补" if ov is None else "重算"] += 1
        updates.setdefault(rid, {})[field] = newv

    for sn, rs in groups.items():
        hf = rs[0]["fields"]
        sv = nz(hf.get("服务商")); ch = nz(hf.get("发货渠道")).strip()
        wh = nz(hf.get("官方仓编码(FBA/FULL/WFS)")); co = nz(hf.get("国家"))
        w = fnum(hf.get("计费重(KG/CBM)"))
        plan(rs[0]["record_id"], "物流单价", freight_price(sv, ch, wh, w), hf.get("物流单价"), sn)
        bg, qg = surcharge(sv, co)
        plan(rs[0]["record_id"], "报关费", bg, hf.get("报关费"), sn)
        plan(rs[0]["record_id"], "清关费", qg, hf.get("清关费"), sn)
        for it in rs:
            f = it["fields"]
            psp = fnum(f.get("平台售价")); qty = fnum(f.get("发货数量"))
            cono = nz(f.get("国家")) or co
            declare = None
            if psp is not None and qty is not None:
                r, fx = ratio(cono)
                declare = psp * qty * r * fx
                plan_compute(it["record_id"], "申报金额", declare, f.get("申报金额"), sn)
            if cono in TAX_COUNTRIES:
                code = nz(f.get("海关编码"))
                if declare is not None and code and (code, cono) in TAXRATE:
                    rate, coef = TAXRATE[(code, cono)]
                    plan_compute(it["record_id"], "税金", declare * rate * coef, f.get("税金"), sn)

    written = 0
    if not dry_run:
        for rid, fields in updates.items():
            feishu.update_record(APP, T, rid, fields)
            written += 1

    return {"票数": len(groups), "report": rep, "待写入": len(updates),
            "已写入": written, "dry_run": dry_run, "差异": diffs[:20]}
