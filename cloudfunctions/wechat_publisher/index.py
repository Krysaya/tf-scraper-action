#!/usr/bin/env python3
"""
腾讯云函数 SCF（定时触发）— 微信公众号草稿箱发布
每 1 小时检查 GitHub output/article.json → 拉内容 → 调微信 API → 草稿箱

环境变量:
  WECHAT_APPID     - 微信公众号 AppID
  WECHAT_APPSECRET - 微信公众号 AppSecret
  GITHUB_TOKEN     - 写权限 PAT

仅用 Python 标准库（urllib），零外部依赖
"""

import os
import json
import base64
import urllib.request
import urllib.error

GITHUB_API = "https://api.github.com"
WECHAT_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
WECHAT_MATERIAL_URL = "https://api.weixin.qq.com/cgi-bin/material/add_material"
WECHAT_DRAFT_URL = "https://api.weixin.qq.com/cgi-bin/draft/add"

REPO = os.environ.get("GITHUB_REPO", "Krysaya/tf-scraper-action")
BRANCH = "main"


# ============================================================
# HTTP 工具（仅用 stdlib）
# ============================================================
def _gh_headers(raw=False):
    token = os.environ.get("GITHUB_TOKEN", "")
    accept = "application/vnd.github.v3.raw" if raw else "application/vnd.github.v3+json"
    return {
        "Authorization": f"token {token}",
        "Accept": accept,
        "User-Agent": "wechat-publisher-scf/1.0",
    }


def http_get_text(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def http_get_json(url, headers=None):
    return json.loads(http_get_text(url, headers))


def http_post_json(url, payload, headers=None):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={**(headers or {}), "Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def http_delete_json(url, payload, headers=None):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={**(headers or {}), "Content-Type": "application/json; charset=utf-8"},
        method="DELETE",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def http_post_multipart(url, image_bytes, filename="image.jpg"):
    """构造 multipart/form-data 上传文件"""
    boundary = "----scfBoundary" + os.urandom(16).hex()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="media"; filename="{filename}"\r\n'
        f"Content-Type: image/jpeg\r\n"
        f"\r\n"
    ).encode("utf-8") + image_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


# ============================================================
# GitHub API
# ============================================================
def gh_get_file(path):
    """读取仓库文本文件"""
    url = f"{GITHUB_API}/repos/{REPO}/contents/{path}?ref={BRANCH}"
    try:
        data = http_get_json(url, headers=_gh_headers())
        return base64.b64decode(data["content"]).decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def gh_get_binary(path):
    """读取仓库二进制文件"""
    url = f"{GITHUB_API}/repos/{REPO}/contents/{path}?ref={BRANCH}"
    try:
        return http_get_text(url, headers=_gh_headers(raw=True))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def gh_list_dir(path):
    """列出目录下所有文件路径"""
    url = f"{GITHUB_API}/repos/{REPO}/contents/{path}?ref={BRANCH}"
    try:
        data = http_get_json(url, headers=_gh_headers())
        if isinstance(data, list):
            return [f["path"] for f in data if f["type"] == "file"]
    except urllib.error.HTTPError:
        pass
    return []
    url = f"{GITHUB_API}/repos/{REPO}/contents/{path}?ref={BRANCH}"
    try:
        data = http_get_json(url, headers=_gh_headers())
        return data.get("sha")
    except urllib.error.HTTPError:
        return None


def gh_delete_file(path, sha, message):
    """删除仓库文件"""
    url = f"{GITHUB_API}/repos/{REPO}/contents/{path}"
    try:
        http_delete_json(
            url,
            {"message": message, "sha": sha, "branch": BRANCH},
            headers=_gh_headers(),
        )
        return True
    except Exception:
        return False


# ============================================================
# 微信 API
# ============================================================
def get_access_token(appid, secret):
    url = f"{WECHAT_TOKEN_URL}?grant_type=client_credential&appid={appid}&secret={secret}"
    data = http_get_json(url)
    if "access_token" not in data:
        raise Exception(f"Token 失败: {data}")
    return data["access_token"]


def upload_image(token, image_bytes, filename="image.jpg"):
    """上传图片，返回完整响应 {'media_id': ..., 'url': ...}"""
    url = f"{WECHAT_MATERIAL_URL}?access_token={token}&type=image"
    data = http_post_multipart(url, image_bytes, filename)
    if "url" not in data:
        raise Exception(f"上传图片失败: {data}")
    return data  # {media_id, url} — 封面用 media_id，文中图片用 url


def create_draft(token, article):
    url = f"{WECHAT_DRAFT_URL}?access_token={token}"
    data = http_post_json(url, {"articles": [article]})
    if "media_id" not in data:
        raise Exception(f"创建草稿失败: {data}")
    return data["media_id"]


# ============================================================
# 主流程
# ============================================================
def process_one_pending():
    """处理一篇待发布文章"""
    print("🔍 检查待发布 article.json ...")

    # 1. 读取 article.json
    manifest_text = gh_get_file("output/article.json")
    if manifest_text is None:
        print("📭 没有待发布的 article.json")
        return None

    manifest = json.loads(manifest_text)
    title = manifest.get("title", "(无标题)")
    print(f"📄 找到: {title}")

    # 2. 读取 HTML
    html = gh_get_file("output/article.html")
    if html is None:
        print("❌ article.html 缺失")
        return None

    # 3. 读取封面图
    cover_bytes = gh_get_binary(f"output/{manifest['cover_file']}")
    if cover_bytes is None:
        print(f"❌ {manifest['cover_file']} 缺失")
        return None

    # 4. 读取 QR 码
    images = []
    for i, qr_name in enumerate(manifest.get("qr_files", [])):
        qr_bytes = gh_get_binary(f"output/{qr_name}")
        if qr_bytes:
            images.append({"id": f"qr_{i}", "bytes": qr_bytes})

    # 5. 调微信 API
    appid = os.environ.get("WECHAT_APPID", "")
    appsecret = os.environ.get("WECHAT_APPSECRET", "")
    token = get_access_token(appid, appsecret)
    print("✅ Token OK")

    # 上传封面（用 media_id 作为 thumb_media_id）
    cover_resp = upload_image(token, cover_bytes, "cover.jpg")
    thumb_media_id = cover_resp["media_id"]
    print(f"✅ 封面 media_id: {thumb_media_id[:20]}...")

    # 上传 QR + 替换占位符（用 url 嵌到 HTML 里）
    for img in images:
        img_resp = upload_image(token, img["bytes"], f"{img['id']}.png")
        wx_url = img_resp["url"]
        placeholder = f"{{{{IMG:{img['id']}}}}}"
        html = html.replace(placeholder, wx_url)
    print(f"✅ {len(images)} 张 QR 上传替换完成")

    # 创建草稿
    article = {
        "title": title,
        "author": manifest.get("author", "卡拉库姆猫"),
        "digest": manifest.get("digest", ""),
        "content": html,
        "thumb_media_id": thumb_media_id,
        "need_open_comment": 0,
        "only_fans_can_comment": 1,
    }
    media_id = create_draft(token, article)
    print(f"✅ 草稿创建成功: {media_id}")

    # 清空 output/ 目录（所有文件都通过 GitHub API 删除）
    print("🧹 清理 output/ 目录 ...")
    deleted = 0
    for filepath in gh_list_dir("output"):
        sha = gh_get_sha(filepath)
        if sha:
            gh_delete_file(filepath, sha, f"Cleanup after publish: {title} [skip ci]")
            deleted += 1
    print(f"🗑️ 已清理 {deleted} 个 output 文件")

    return media_id


def main_handler(event, context):
    """
    SCF 定时触发入口
    """
    try:
        media_id = process_one_pending()
        if media_id:
            return {"success": True, "media_id": media_id}
        return {"success": True, "msg": "no pending content"}
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP 错误 [{e.code}]: {e.reason}")
        return {"success": False, "error": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        print(f"❌ 错误: {e}")
        return {"success": False, "error": str(e)}
