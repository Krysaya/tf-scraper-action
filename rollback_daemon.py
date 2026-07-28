#!/usr/bin/env python3
"""
本地回滚方案 —— 如果腾讯云 SCF 收费了 / 换了新电脑，用此脚本恢复本地自动发布

┌─────────────────────────────────────────────────────┐
│  新电脑使用步骤                                      │
│                                                     │
│  1. 下载代码                                         │
│     git clone https://github.com/Krysaya/tf-scraper-action.git  │
│     cd tf-scraper-action                             │
│                                                     │
│  2. 配置环境变量（必填 3 个）                         │
│     export WECHAT_APPID="wx4767544e0f9b8625"         │
│     export WECHAT_APPSECRET="你的AppSecret"           │
│     export GITHUB_TOKEN="你的GitHub PAT"             │
│                                                     │
│  3. 运行                                             │
│     python3 rollback_daemon.py                       │
│                                                     │
│  4. 后台运行（可选）                                  │
│     nohup python3 rollback_daemon.py > rollback.log 2>&1 &  │
│                                                     │
│  Python 自带即可，零外部依赖。每 10 分钟轮询一次。      │
└─────────────────────────────────────────────────────┘

功能:
  每 10 分钟检查 GitHub 仓库的 output/article.json
  如果有新内容 → 拉取 → 调微信 API → 草稿箱

环境变量:
  WECHAT_APPID      - 微信公众号 AppID
  WECHAT_APPSECRET  - 微信公众号 AppSecret
  GITHUB_TOKEN      - 仓库读写 PAT（发布后删除 marker 用）
"""

import os
import sys
import json
import time
import base64
import urllib.request
import urllib.error
from pathlib import Path

GITHUB_API = "https://api.github.com"
REPO = "Krysaya/tf-scraper-action"
BRANCH = "main"
WECHAT_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
WECHAT_MATERIAL_URL = "https://api.weixin.qq.com/cgi-bin/material/add_material"
WECHAT_DRAFT_URL = "https://api.weixin.qq.com/cgi-bin/draft/add"

CHECK_INTERVAL = 600  # 10 分钟


def _gh_headers(raw=False):
    token = os.environ.get("GITHUB_TOKEN", "")
    accept = "application/vnd.github.v3.raw" if raw else "application/vnd.github.v3+json"
    return {"Authorization": f"token {token}", "Accept": accept, "User-Agent": "rollback-daemon/1.0"}


def gh_get_json(path):
    url = f"{GITHUB_API}/repos/{REPO}/contents/{path}?ref={BRANCH}"
    req = urllib.request.Request(url, headers=_gh_headers())
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError:
        return None


def gh_get_file(path):
    data = gh_get_json(path)
    if data and "content" in data:
        return base64.b64decode(data["content"]).decode("utf-8")
    return None


def gh_get_binary(path):
    url = f"{GITHUB_API}/repos/{REPO}/contents/{path}?ref={BRANCH}"
    req = urllib.request.Request(url, headers=_gh_headers(raw=True))
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read()
    except urllib.error.HTTPError:
        return None


def gh_delete(path, sha):
    url = f"{GITHUB_API}/repos/{REPO}/contents/{path}"
    payload = json.dumps({"message": "Published [rollback]", "sha": sha, "branch": BRANCH}).encode()
    req = urllib.request.Request(url, data=payload, headers={**_gh_headers(), "Content-Type": "application/json"}, method="DELETE")
    try:
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception:
        return False


def wechat_get_token(appid, secret):
    url = f"{WECHAT_TOKEN_URL}?grant_type=client_credential&appid={appid}&secret={secret}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read())
    if "access_token" not in data:
        raise Exception(f"Token 失败: {data}")
    return data["access_token"]


def wechat_upload_image(token, img_bytes, filename="image.jpg"):
    boundary = "----rollback" + os.urandom(16).hex()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="media"; filename="{filename}"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n"
    ).encode() + img_bytes + f"\r\n--{boundary}--\r\n".encode()

    url = f"{WECHAT_MATERIAL_URL}?access_token={token}&type=image"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(body))}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def wechat_create_draft(token, article):
    url = f"{WECHAT_DRAFT_URL}?access_token={token}"
    payload = json.dumps({"articles": [article]}, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def process():
    manifest_text = gh_get_file("output/article.json")
    if manifest_text is None:
        return None

    manifest = json.loads(manifest_text)
    title = manifest["title"]
    print(f"[{time.strftime('%H:%M:%S')}] 📄 {title}")

    html = gh_get_file("output/article.html")
    cover_bytes = gh_get_binary(f"output/{manifest['cover_file']}")
    if html is None or cover_bytes is None:
        print("  ❌ 文件不完整")
        return None

    # 拉 QR
    images = []
    for i, qr_name in enumerate(manifest.get("qr_files", [])):
        qr_bytes = gh_get_binary(f"output/{qr_name}")
        if qr_bytes:
            images.append({"id": f"qr_{i}", "bytes": qr_bytes})

    # 微信 API
    appid = os.environ.get("WECHAT_APPID", "")
    appsecret = os.environ.get("WECHAT_APPSECRET", "")
    token = wechat_get_token(appid, appsecret)

    cover_resp = wechat_upload_image(token, cover_bytes, "cover.jpg")
    thumb_media_id = cover_resp["media_id"]

    for img in images:
        img_resp = wechat_upload_image(token, img["bytes"], f"{img['id']}.png")
        html = html.replace(f"{{{{IMG:{img['id']}}}}}", img_resp["url"])

    article = {
        "title": title,
        "author": manifest.get("author", "卡拉库姆猫"),
        "digest": manifest.get("digest", ""),
        "content": html,
        "thumb_media_id": thumb_media_id,
        "need_open_comment": 0,
        "only_fans_can_comment": 1,
    }
    result = wechat_create_draft(token, article)
    if "media_id" in result:
        print(f"  ✅ 草稿: {result['media_id']}")

        # 删 marker
        article_json = gh_get_json("output/article.json")
        if article_json and "sha" in article_json:
            gh_delete("output/article.json", article_json["sha"])
            print("  🗑️ 已删除 marker")
        return result["media_id"]
    else:
        print(f"  ❌ {result}")
        return None


def main():
    print("=" * 50)
    print("  回滚守护进程（本地发布）")
    print(f"  检查间隔: {CHECK_INTERVAL // 60} 分钟")
    print("  Ctrl+C 停止")
    print("=" * 50)

    while True:
        try:
            result = process()
            if result is None:
                print(f"[{time.strftime('%H:%M:%S')}] 📭 等待中...")
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ❌ {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
