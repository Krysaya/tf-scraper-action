#!/usr/bin/env python3
"""
腾讯云函数 SCF（定时触发）— 微信公众号草稿箱发布
每 5 分钟自动检查 GitHub 仓库 output/article.json，有就发布到微信草稿箱

环境变量:
  WECHAT_APPID     - 微信公众号 AppID
  WECHAT_APPSECRET - 微信公众号 AppSecret
  GITHUB_TOKEN     - 有写权限的 GitHub PAT，发布成功后删除 marker 用
  GITHUB_REPO      - 仓库 full_name，默认 Krysaya/tf-scraper-action
"""

import os
import json
import base64
import requests

GITHUB_API = "https://api.github.com"
WECHAT_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
WECHAT_MATERIAL_URL = "https://api.weixin.qq.com/cgi-bin/material/add_material"
WECHAT_DRAFT_URL = "https://api.weixin.qq.com/cgi-bin/draft/add"

REPO = os.environ.get("GITHUB_REPO", "Krysaya/tf-scraper-action")
BRANCH = "main"


# ============================================================
# GitHub API
# ============================================================
def _gh_headers(json_content=True):
    token = os.environ.get("GITHUB_TOKEN", "")
    h = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    if not json_content:
        h["Accept"] = "application/vnd.github.v3.raw"
    return h


def github_get_file(path):
    """读取仓库文件（文本），返回字符串；不存在返回 None"""
    url = f"{GITHUB_API}/repos/{REPO}/contents/{path}?ref={BRANCH}"
    resp = requests.get(url, headers=_gh_headers(json_content=True), timeout=15)
    if resp.status_code != 200:
        return None
    data = resp.json()
    return base64.b64decode(data["content"]).decode("utf-8")


def github_get_binary(path):
    """读取仓库文件（二进制），返回 bytes；不存在返回 None"""
    url = f"{GITHUB_API}/repos/{REPO}/contents/{path}?ref={BRANCH}"
    resp = requests.get(url, headers=_gh_headers(json_content=False), timeout=15)
    if resp.status_code != 200:
        return None
    return resp.content


def github_delete_file(path, sha, message):
    """删除仓库文件"""
    url = f"{GITHUB_API}/repos/{REPO}/contents/{path}"
    payload = {"message": message, "sha": sha, "branch": BRANCH}
    resp = requests.delete(url, headers=_gh_headers(), json=payload, timeout=15)
    return resp.status_code == 200


def github_get_sha(path):
    """获取文件 SHA（删除时需要）"""
    url = f"{GITHUB_API}/repos/{REPO}/contents/{path}?ref={BRANCH}"
    resp = requests.get(url, headers=_gh_headers(), timeout=15)
    if resp.status_code != 200:
        return None
    return resp.json().get("sha")


# ============================================================
# 微信 API
# ============================================================
def get_access_token(appid, secret):
    url = f"{WECHAT_TOKEN_URL}?grant_type=client_credential&appid={appid}&secret={secret}"
    resp = requests.get(url, timeout=15)
    data = resp.json()
    if "access_token" not in data:
        raise Exception(
            f"Token 失败 [errcode={data.get('errcode', '?')}] {data.get('errmsg', '?')}"
        )
    return data["access_token"]


def upload_image(token, image_bytes, filename="image.jpg"):
    url = f"{WECHAT_MATERIAL_URL}?access_token={token}&type=image"
    resp = requests.post(
        url,
        files={"media": (filename, image_bytes, "image/jpeg")},
        timeout=30,
    )
    data = resp.json()
    if "url" not in data:
        raise Exception(
            f"上传图片失败 [errcode={data.get('errcode', '?')}] {data.get('errmsg', '?')}"
        )
    return data["url"]


def create_draft(token, article):
    url = f"{WECHAT_DRAFT_URL}?access_token={token}"
    payload = {"articles": [article]}
    resp = requests.post(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=30,
    )
    data = resp.json()
    if "media_id" not in data:
        raise Exception(
            f"创建草稿失败 [errcode={data.get('errcode', '?')}] {data.get('errmsg', '?')}"
        )
    return data["media_id"]


# ============================================================
# 主流程
# ============================================================
def process_one_pending():
    """处理一篇待发布文章，成功返回 media_id；无待发返回 None"""
    print("🔍 检查待发布 article.json ...")

    # 1. 读取 article.json
    manifest_text = github_get_file("output/article.json")
    if manifest_text is None:
        print("📭 没有待发布的 article.json")
        return None

    manifest = json.loads(manifest_text)
    title = manifest.get("title", "(无标题)")
    print(f"📄 找到: {title}")

    # 2. 读取 HTML
    html = github_get_file("output/article.html")
    if html is None:
        print("❌ article.html 缺失")
        return None

    # 3. 读取封面图
    cover_bytes = github_get_binary(f"output/{manifest['cover_file']}")
    if cover_bytes is None:
        print(f"❌ {manifest['cover_file']} 缺失")
        return None

    # 4. 读取 QR 码
    images = []
    qr_files = manifest.get("qr_files", [])
    for i, qr_name in enumerate(qr_files):
        qr_bytes = github_get_binary(f"output/{qr_name}")
        if qr_bytes:
            images.append({"id": f"qr_{i}", "bytes": qr_bytes})

    # 5. 调微信 API
    appid = os.environ.get("WECHAT_APPID", "")
    appsecret = os.environ.get("WECHAT_APPSECRET", "")
    token = get_access_token(appid, appsecret)

    # 上传封面
    print("📤 上传封面 ...")
    thumb_media_id = upload_image(token, cover_bytes, "cover.jpg")

    # 上传 QR + 替换占位符
    print(f"📤 上传 {len(images)} 张 QR 码 ...")
    for img in images:
        wx_url = upload_image(token, img["bytes"], f"{img['id']}.png")
        placeholder = f"{{{{IMG:{img['id']}}}}}"
        html = html.replace(placeholder, wx_url)

    # 创建草稿
    print("📝 创建草稿 ...")
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

    # 6. 删除 article.json marker（防止重复发布）
    sha = github_get_sha("output/article.json")
    if sha:
        github_delete_file(
            "output/article.json",
            sha,
            f"Published {manifest.get('type', '?')}: {title} [skip ci]",
        )
        print("🗑️ 已删除 article.json marker")

    return media_id


def main_handler(event, context):
    """
    SCF 定时触发入口 - 每 5 分钟执行一次
    """
    try:
        media_id = process_one_pending()
        if media_id:
            return {"success": True, "media_id": media_id}
        return {"success": True, "msg": "no pending content"}
    except Exception as e:
        print(f"❌ 错误: {e}")
        return {"success": False, "error": str(e)}
