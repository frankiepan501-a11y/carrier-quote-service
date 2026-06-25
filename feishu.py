# -*- coding: utf-8 -*-
"""飞书 API 封装：token / Bitable CRUD / 附件下载 / IM 通知。凭据全走环境变量。"""
import os
import json
import time
import urllib.request
import urllib.error

APP_ID = os.environ.get("FEISHU_APP_ID", "")
APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
BASE = "https://open.feishu.cn/open-apis"

_tok = {"v": None, "exp": 0}


def _req(url, method="GET", body=None, headers=None, raw=False):
    data = body if raw else (json.dumps(body).encode() if body is not None else None)
    h = {} if raw else ({"Content-Type": "application/json"} if body is not None else {})
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        return e.read()


def token():
    if _tok["v"] and time.time() < _tok["exp"]:
        return _tok["v"]
    r = json.loads(_req(BASE + "/auth/v3/tenant_access_token/internal", "POST",
                        {"app_id": APP_ID, "app_secret": APP_SECRET}))
    _tok["v"] = r["tenant_access_token"]
    _tok["exp"] = time.time() + r.get("expire", 7000) - 200
    return _tok["v"]


def H():
    return {"Authorization": "Bearer " + token()}


def list_records(app, table, page_size=200):
    out = []
    pt = ""
    while True:
        u = "%s/bitable/v1/apps/%s/tables/%s/records?page_size=%d%s" % (
            BASE, app, table, page_size, ("&page_token=" + pt if pt else ""))
        d = json.loads(_req(u, "GET", headers=H()))["data"]
        out += d.get("items", [])
        if d.get("has_more"):
            pt = d["page_token"]
        else:
            break
    return out


def batch_create(app, table, records):
    ins = 0
    for i in range(0, len(records), 200):
        r = json.loads(_req("%s/bitable/v1/apps/%s/tables/%s/records/batch_create" % (BASE, app, table),
                            "POST", {"records": records[i:i + 200]}, H()))
        if r.get("code") != 0:
            raise RuntimeError("batch_create fail: " + json.dumps(r, ensure_ascii=False)[:300])
        ins += len(r["data"]["records"])
    return ins


def batch_delete(app, table, ids):
    for i in range(0, len(ids), 200):
        _req("%s/bitable/v1/apps/%s/tables/%s/records/batch_delete" % (BASE, app, table),
             "POST", {"records": ids[i:i + 200]}, H())


def update_record(app, table, rid, fields):
    return json.loads(_req("%s/bitable/v1/apps/%s/tables/%s/records/%s" % (BASE, app, table, rid),
                           "PUT", {"fields": fields}, H()))


def download_media(file_token):
    """下载 Bitable 附件二进制。"""
    u = "%s/drive/v1/medias/%s/download" % (BASE, file_token)
    return _req(u, "GET", headers=H())


def send_text(open_id, text):
    body = {"receive_id": open_id, "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False)}
    return json.loads(_req(BASE + "/im/v1/messages?receive_id_type=open_id", "POST", body, H()))
