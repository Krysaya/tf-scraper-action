#!/usr/bin/env python3
"""
腾讯云函数 SCF — 微信公众号草稿箱发布
接收 GitHub Actions 发来的文章数据 → 调微信 API → 草稿箱

触发器类型: API 网关
环境变量:
  WECHAT_APPID     - 微信公众号 AppID
  WECHAT_APPSECRET - 微信公众号 AppSecret
  WORKER_SECRET    - 鉴权密钥
"""

import os
import json
import base64
import requests

WECHAT_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
WECHAT_MATERIAL_URL = "https://api.weixin.qq.com/cgi-bin/material/add_material"
WECHAT_DRAFT_URL = "https://api.weixin.qq.com/cgi-bin/draft/add"


def get_access_token(appid, secret):
    url = f"{WECHAT_TOKEN_URL}?grant_type=client_credential&appid={appid}&secret={secret}"
    resp = requests.get(url, timeout=15)
    data = resp.json()
    if "access_token" not in data:
        raise Exception(f"Token 失败 [{data.get('errcode', '?')}]: {data.get('errmsg', '?')}")
    return data["access_token"]


def upload_image(token, image_base64, filename="image.jpg"):
    """上传图片到微信素材库"""
    url = f"{WECHAT_MATERIAL_URL}?access_token={token}&type=image"
    image_bytes = base64.b64decode(image_base64)
    resp = requests.post(
        url,
        files={"media": (filename, image_bytes, "image/jpeg")},
        timeout=30,
    )
    data = resp.json()
    if "url" not in data:
        raise Exception(f"上传图片失败 [{data.get('errcode', '?')}]: {data.get('errmsg', '?')}")
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
        raise Exception(f"创建草稿失败 [{data.get('errcode', '?')}]: {data.get('errmsg', '?')}")
    return data["media_id"]


def main_handler(event, context):
    """
    API 网关触发器入口
    event.body: JSON string
    """
    # 1. 鉴权
    headers = event.get("headers", {})
    # API 网关会把 header key 转小写
    secret = (
        headers.get("x-worker-secret")
        or headers.get("X-Worker-Secret")
        or ""
    )
    expected = os.environ.get("WORKER_SECRET", "")
    if secret != expected:
        return {
            "statusCode": 401,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Unauthorized"}, ensure_ascii=False),
        }

    # 2. 解析请求
    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Invalid JSON body"}, ensure_ascii=False),
        }

    title = body.get("title", "")
    author = body.get("author", "卡拉库姆猫")
    digest = body.get("digest", "")
    content = body.get("content", "")
    cover_base64 = body.get("cover_base64", "")
    images = body.get("images", [])

    if not title or not content or not cover_base64:
        return {
            "statusCode": 400,
            "body": json.dumps(
                {"error": "Missing fields: title, content, cover_base64"},
                ensure_ascii=False,
            ),
        }

    try:
        # 3. 获取 access_token
        appid = os.environ.get("WECHAT_APPID", "")
        appsecret = os.environ.get("WECHAT_APPSECRET", "")
        token = get_access_token(appid, appsecret)

        # 4. 上传封面
        thumb_media_id = upload_image(token, cover_base64, "cover.jpg")

        # 5. 上传文中图片、替换占位符
        html = content
        for img in images:
            wx_url = upload_image(token, img["base64"], f"{img['id']}.png")
            placeholder = f"{{{{IMG:{img['id']}}}}}"
            html = html.replace(placeholder, wx_url)

        # 6. 创建草稿
        article = {
            "title": title,
            "author": author,
            "digest": digest,
            "content": html,
            "thumb_media_id": thumb_media_id,
            "need_open_comment": 0,
            "only_fans_can_comment": 1,
        }
        media_id = create_draft(token, article)

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(
                {"success": True, "media_id": media_id}, ensure_ascii=False
            ),
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(
                {"success": False, "error": str(e)}, ensure_ascii=False
            ),
        }
