# -*- coding: utf-8 -*-
"""货代报价单解析器：每家货代一套 sheet/段/列规则，输出标准化单价字典条目。
已在 2026-06 用 6 月真实票 A/B 对账验证（18/24 精确命中）。"""
import re

WH = re.compile(r'^[A-Z]{2,4}\d{1,2}$')   # 仓库代码 ONT8/BHX4/WRO5/YYC4...


def num(x):
    try:
        return float(str(x).strip())
    except Exception:
        return None


def cells(ws, rmax, cmax=16):
    out = []
    for row in ws.iter_rows(min_row=1, max_row=rmax, max_col=cmax, values_only=True):
        out.append([("" if c is None else str(c)).strip() for c in row])
    return out


def cleanwh(s):
    """去括号 + 按 / 拆多仓：'WRO5(02977)' -> ['WRO5']；'DTM2/DTM1' -> ['DTM2','DTM1']"""
    s = re.sub(r'\(.*?\)', '', s).strip()
    return [w.strip() for w in s.split('/') if w.strip()]


def norm_wh(s):
    """规范仓库号：剥掉报价单里的 'Wal-Mart '/'Walmart ' 前缀。
    'Wal-Mart ATL3' -> 'ATL3'；回填侧对物流填的官方仓编码做同样处理保证对得上。"""
    if not s:
        return ""
    return re.sub(r'(?i)^wal-?mart\s+', '', str(s).strip()).strip()


def E(sv, ch, co, wh, unit, low, price, bs, code="", note=""):
    return {"服务商": sv, "渠道": ch, "国家": co, "仓库代码": wh, "计费单位": unit,
            "计费重档下限": low, "单价": price, "包税属性": bs, "渠道代码": code, "备注": note}


def parse_anjun_us(wb):
    out = []
    ws = wb["以星限时达"]
    data = cells(ws, 80)
    # 以星限时达-卡派：仓库 col1 × 档(10/51/351) col3/4/5
    start = None
    for i, r in enumerate(data):
        if r[1].startswith("以星限时达-卡派"):
            start = i
            break
    if start is not None:
        for i in range(start + 2, len(data)):
            r = data[i]
            w = r[1]
            if w in ("理赔标准",) or w.startswith("以星限时达-"):
                break
            if WH.match(w) and num(r[3]) is not None:
                for low, c in [(10, 3), (51, 4), (351, 5)]:
                    if num(r[c]) is not None:
                        out.append(E("安君", "以星限时达-卡派", "美国", w, "KG", low, num(r[c]), "不包税递延", "J-ZK"))
    # 以星限时达-快递派：邮编分区制 (美西/美中/美东 × 12/101/301)，仓库码记 ZONE:美东 等
    inseg = False
    for r in cells(ws, 11):
        if r[1].startswith("以星限时达-快递派"):
            inseg = True
        if inseg and r[1][:2] in ("美西", "美中", "美东"):
            zone = r[1][:2]
            for low, c in [(12, 3), (101, 4), (301, 5)]:
                if num(r[c]) is not None:
                    out.append(E("安君", "以星限时达-快递派", "美国", "ZONE:" + zone, "KG", low, num(r[c]), "不包税递延", "J-ZA", "邮编分区"))
    # COSCO,EMC-卡派
    if "COSCO、EMC " in wb.sheetnames:
        ws2 = wb["COSCO、EMC "]
        cursec = ""
        for r in cells(ws2, 139):
            if r[1].strip() and ("卡派" in r[1] or "快递派" in r[1]):
                cursec = r[1].strip()
            if cursec == "COSCO,EMC-卡派" and WH.match(r[1]) and num(r[3]) is not None:
                for low, c in [(10, 3), (51, 4), (351, 5)]:
                    if num(r[c]) is not None:
                        out.append(E("安君", "COSCO,EMC-卡派", "美国", r[1], "KG", low, num(r[c]), "不包税递延", "J-CK"))
    # 美东极速达：按仓库列价（非分区！）；仓库号含 'Wal-Mart ATL3' 格式 → 剥前缀
    if "美东极速达" in wb.sheetnames:
        ws3 = wb["美东极速达"]
        for r in cells(ws3, 115):
            if num(r[3]) is None or not r[1]:
                continue
            if any(k in r[1] for k in ("极速达", "仓库代码", "理赔")):  # 跳表头/小计行
                continue
            wh = norm_wh(r[1])
            if not wh:
                continue
            for low, c in [(10, 3), (51, 4), (351, 5)]:
                if num(r[c]) is not None:
                    out.append(E("安君", "美东极速达", "美国", wh, "KG", low, num(r[c]), "不包税递延", "J-NK"))
    return out


def parse_anjun_ca(wb):
    out = []
    ws = wb["加拿大卡派"]
    # 美转加OA定提限时达 卡派 = OAK含税列 col8/9/10 (21/51/101KG)
    for r in cells(ws, 40):
        if WH.match(r[1]) and num(r[8]) is not None:
            for low, c in [(21, 8), (51, 9), (101, 10)]:
                if num(r[c]) is not None:
                    out.append(E("安君", "美转加OA定提限时达 卡派", "加拿大", r[1], "KG", low, num(r[c]), "包税", "L-OAK"))
    return out


def parse_yuntuo(wb):
    out = []
    # 英国卡航 - 卡航卡派递延
    ws = wb["英国卡航"]
    inseg = False
    for r in cells(ws, 25):
        if r[0].startswith("卡航卡派递延"):
            inseg = True
        if r[0].startswith("卡航卡派包税"):
            inseg = False
        if inseg and WH.match(r[2]) and num(r[3]) is not None:
            for low, c in [(21, 3), (51, 4), (100, 5)]:
                if num(r[c]) is not None:
                    out.append(E("云驼", "中英卡航卡派递延", "英国", r[2], "KG", low, num(r[c]), "不包税递延"))
    # 欧盟卡航 - 卡航卡派递延 (仓库 col2，去括号/拆)
    ws2 = wb["欧盟卡航"]
    inseg = False
    for r in cells(ws2, 90):
        if r[0].startswith("卡航卡派递延"):
            inseg = True
        if r[0].startswith("卡航卡派包税"):
            inseg = False
        if inseg:
            for wh in cleanwh(r[2]):
                if WH.match(wh) and num(r[3]) is not None:
                    for low, c in [(21, 3), (51, 4), (100, 5)]:
                        if num(r[c]) is not None:
                            out.append(E("云驼", "中欧卡航卡派递延", "", wh, "KG", low, num(r[c]), "不包税递延"))
    # 欧洲海运递延-固定申报 - 海卡递延-固定申报
    ws3 = wb["欧洲海运递延-固定申报"]
    inseg = False
    for r in cells(ws3, 40):
        if r[0].startswith("海卡递延-固定申报"):
            inseg = True
        elif r[0].startswith("产品名称"):
            inseg = False
        if inseg:
            for wh in cleanwh(r[2]):
                if WH.match(wh) and num(r[3]) is not None:
                    for low, c in [(21, 3), (51, 4), (100, 5)]:
                        if num(r[c]) is not None:
                            out.append(E("云驼", "海卡递延-固定申报", "德国", wh, "KG", low, num(r[c]), "不包税递延"))
    return out


def parse_moke(wb):
    out = []
    ws = wb["美转墨大货 （DDP)"]
    for r in cells(ws, 12, 5):
        if r[1] == "MM3":
            m = re.search(r'([\d.]+)', r[2])
            if m:
                out.append(E("墨客多", "MM3", "墨西哥", "", "CBM", 1, float(m.group(1)), "包税", "MM3", "3C电子B类·按方"))
    return out


# (货代, 线路) -> 解析函数；新货代/线路在此扩展
DISPATCH = {
    ("安君", "美国"): parse_anjun_us,
    ("安君", "加拿大"): parse_anjun_ca,
    ("云驼", "欧线"): parse_yuntuo,
    ("墨客多", "墨西哥"): parse_moke,
}

# 该 (货代,线路) 解析会覆盖哪些 (服务商,渠道) — 用于 upsert 前清旧
CHANNELS = {
    ("安君", "美国"): [("安君", "以星限时达-卡派"), ("安君", "以星限时达-快递派"),
                    ("安君", "COSCO,EMC-卡派"), ("安君", "美东极速达")],
    ("安君", "加拿大"): [("安君", "美转加OA定提限时达 卡派")],
    ("云驼", "欧线"): [("云驼", "中英卡航卡派递延"), ("云驼", "中欧卡航卡派递延"),
                   ("云驼", "海卡递延-固定申报")],
    ("墨客多", "墨西哥"): [("墨客多", "MM3")],
}


def parse(wb, vendor, line):
    fn = DISPATCH.get((vendor, line))
    if not fn:
        return None
    return fn(wb)
