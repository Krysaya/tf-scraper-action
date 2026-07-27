#!/usr/bin/env python3
"""
打包 output/ 目录 → HTTP POST 到 Cloudflare Worker
环境变量: CF_WORKER_URL, CF_WORKER_SECRET
用法: python send_to_worker.py
"""

import os
import sys
import json
import base64
from pathlib import Path

import requests

# ============================================================
# 配置
# ============================================================
WORK_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = WORK_DIR / "output"

WORKER_URL = os.environ.get("CF_WORKER_URL", "").strip().rstrip("/")
WORKER_SECRET = os.environ.get("CF_WORKER_SECRET", "").strip()

if not WORKER_URL:
    print("❌ 请设置环境变量 CF_WORKER_URL")
    sys.exit(1)
if not WORKER_SECRET:
    print("❌ 请设置环境变量 CF_WORKER_SECRET")
    sys.exit(1)

# ============================================================
# 主流程
# ============================================================
def main():
    print("=" * 50)
    print("  📤 发送到 Cloudflare Worker")
    print("=" * 50)

    # 1. 读取元数据
    manifest_path = OUTPUT_DIR / "article.json"
    if not manifest_path.exists():
        print("❌ 找不到 output/article.json，请先运行 publisher 脚本")
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(f"📋 {manifest['title']}")
    print(f"   类型: {manifest.get('type', '?')}")

    # 2. 读取 HTML
    html_path = OUTPUT_DIR / manifest["html_file"]
    if not html_path.exists():
        print(f"❌ 找不到 {html_path}")
        sys.exit(1)
    html_content = html_path.read_text(encoding="utf-8")
    print(f"📄 HTML: {len(html_content)} 字符")

    # 3. 编码封面图
    cover_path = OUTPUT_DIR / manifest["cover_file"]
    if not cover_path.exists():
        print(f"❌ 找不到 {cover_path}")
        sys.exit(1)
    cover_base64 = base64.b64encode(cover_path.read_bytes()).decode("utf-8")
    print(f"🖼️ 封面: {cover_path} ({len(cover_base64)} base64 字符)")

    # 4. 编码 QR 码
    images = []
    for qr_name in manifest.get("qr_files", []):
        qr_path = OUTPUT_DIR / qr_name
        if not qr_path.exists():
            print(f"⚠️ 跳过缺失: {qr_name}")
            continue
        img_b64 = base64.b64encode(qr_path.read_bytes()).decode("utf-8")
        img_id = qr_name.replace(".png", "").replace("_", "")  # qr_1 → qr1
        images.append({
            "id": f"qr_{int(img_id.replace('qr', '')) - 1}",  # qr1 → qr_0 (匹配 HTML 占位符索引)
            "base64": img_b64,
        })
        print(f"  📱 {qr_name}: {len(img_b64)} base64 字符")

    # 修正图片 ID，使其匹配 HTML 中的 {{IMG:qr_0}} 占位符
    # qr_files = ["qr_1.png", "qr_2.png", ...]
    # HTML 占位符 = {{IMG:qr_0}}, {{IMG:qr_1}}, ...（从 0 开始）
    for i, img in enumerate(images):
        img["id"] = f"qr_{i}"

    # 5. 构建请求体
    payload = {
        "title": manifest["title"],
        "author": manifest.get("author", "卡拉库姆猫"),
        "digest": manifest.get("digest", ""),
        "content": html_content,
        "cover_base64": cover_base64,
        "images": images,
    }

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    body_size_mb = len(body) / (1024 * 1024)
    print(f"\n📦 请求体大小: {body_size_mb:.1f} MB")

    if body_size_mb > 100:
        print("⚠️ 请求体超过 100MB，可能超出 Worker 限制")
        # 仍然尝试发送

    # 6. 发送
    print(f"\n🚀 POST {WORKER_URL}/publish")
    try:
        resp = requests.post(
            f"{WORKER_URL}/publish",
            data=body,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-Worker-Secret": WORKER_SECRET,
            },
            timeout=60,
        )
        print(f"   状态码: {resp.status_code}")

        if resp.status_code == 200:
            result = resp.json()
            print(f"✅ 发布成功! media_id: {result.get('media_id', '?')}")
            print(f"\n🎉 去 mp.weixin.qq.com → 草稿箱 查看")
        else:
            print(f"❌ HTTP {resp.status_code}: {resp.text[:500]}")
            sys.exit(1)

    except requests.exceptions.Timeout:
        print("❌ 请求超时（60s），可能是图片太大或 Worker 处理慢")
        sys.exit(1)
    except requests.exceptions.ConnectionError as e:
        print(f"❌ 连接失败: {e}")
        print("   检查 CF_WORKER_URL 是否正确，Worker 是否已部署")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 发送失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
