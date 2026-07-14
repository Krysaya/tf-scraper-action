#!/usr/bin/env python3
"""
TestFlight 每周合集公众号发布脚本
数据来源: scraper.py 的 wechat-weekly 模式生成的 TXT
封面: 固定 TestFlight 炫彩封面（不含日期）
"""

import os
import sys
import json
import time
import re
from pathlib import Path
from io import BytesIO

import requests
import qrcode
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# 微信 API 国内直连，跳过系统代理（避免代理 IP 变化导致白名单失效）
NO_PROXY = {"http": "", "https": ""}

APPID = os.environ.get("WECHAT_APPID", "").strip()
APPSECRET = os.environ.get("WECHAT_APPSECRET", "").strip()

if not APPID:
    # 尝试从 .env 加载
    try:
        from dotenv import load_dotenv
        load_dotenv()
        APPID = os.getenv("WECHAT_APPID", "").strip()
        APPSECRET = os.getenv("WECHAT_APPSECRET", "").strip()
    except ImportError:
        pass

AUTHOR = "卡拉库姆猫"
WORK_DIR = Path(__file__).parent
COVER_PATH = WORK_DIR / "tf_cover.jpg"
BG_PATH = WORK_DIR / "tf_cover_bg.png"

# ========== TXT 解析 ==========
def parse_tf_txt(filepath):
    """
    格式:
        TestFlight合集 第N期
        <空行>
        1. App名称
           https://testflight.apple.com/join/CODE
    """
    path = Path(filepath)
    if not path.exists():
        print(f"❌ 文件不存在: {filepath}")
        sys.exit(1)

    text = path.read_text(encoding="utf-8")
    lines = text.strip().split("\n")

    # 提取期数
    issue = "?"
    m = re.search(r"第(\d+)期", lines[0]) if lines else None
    if m:
        issue = m.group(1)

    apps = []
    i = 1
    while i < len(lines):
        line = lines[i].strip()
        match = re.match(r"^\d+\.\s+(.+)$", line)
        if match:
            name = match.group(1).strip()
            url = ""
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line.startswith("https://testflight.apple.com"):
                    url = next_line
                    i += 1
            i += 1
            apps.append((name, url))
        else:
            i += 1

    print(f"📄 解析: {path.name} | 第{issue}期 | {len(apps)} 款")
    return issue, apps


# ========== 封面 ==========
def generate_tf_cover():
    """生成 TF 周报封面：参考 tf_cover-old.jpg 风格，背景用 tf_cover_bg.png"""

    # ---------- 1. 加载背景 ----------
    if BG_PATH.exists():
        print("📸 使用自定义背景 (tf_cover_bg.png)")
        img = Image.open(BG_PATH).convert("RGBA")
    else:
        print("🎨 程序化生成深色背景...")
        import random
        random.seed(99)
        W, H = 900, 500
        img = Image.new("RGB", (W, H))
        pixels = img.load()
        for y in range(H):
            ratio = y / H
            for x in range(W):
                pixels[x, y] = (int(10 + ratio * 30), int(8 + ratio * 25), int(40 + ratio * 70))

        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow, "RGBA")
        for cx, cy, r, c in [
            (450, 200, 350, (80, 30, 200, 55)), (200, 400, 280, (30, 120, 230, 45)),
            (700, 100, 250, (50, 180, 240, 40)), (100, -50, 300, (200, 80, 180, 35)),
        ]:
            gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
        img = Image.alpha_composite(img.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(60))).convert("RGB")

        grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(grid, "RGBA")
        for x in range(0, W, 35):
            gd.line([(x, 0), (x, H)], fill=(100, 100, 180, 25), width=1)
        for y in range(0, H, 35):
            gd.line([(0, y), (W, y)], fill=(100, 100, 180, 25), width=1)
        img = Image.alpha_composite(img.convert("RGBA"), grid).convert("RGB")
        img.save(BG_PATH, "PNG")
        img = img.convert("RGBA")

    W, H = img.size

    # ---------- 2. 加载字体（PingFang Bold 优先） ----------
    draw = ImageDraw.Draw(img)
    fonts = {}
    for fp in [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
    ]:
        if os.path.exists(fp):
            try:
                fonts["title"] = ImageFont.truetype(fp, 130)
                fonts["big"] = ImageFont.truetype(fp, 38)
                fonts["mid"] = ImageFont.truetype(fp, 28)
                fonts["small"] = ImageFont.truetype(fp, 22)
                break
            except Exception:
                continue
    if not fonts:
        fonts["title"] = fonts["mid"] = fonts["small"] = ImageFont.load_default()

    # ---------- 3. 画文字（白色，无描边） ----------
    COLOR = (255, 255, 255)

    def dc(d, text, font, y, color=COLOR):
        bb = d.textbbox((0, 0), text, font=font)
        d.text(((W - (bb[2] - bb[0])) / 2, y), text, fill=color, font=font)

    # 主标题（最大）
    dc(draw, "TestFlight", fonts["title"], 130)

    # 副标题
    dc(draw, "每周限免合集", fonts["big"], 290)

    # 底部 tagline（下移）
    dc(draw, "限时测试名额 · 手慢无", fonts["mid"], 380)

    # ---------- 4. 保存 ----------
    img.convert("RGB").save(COVER_PATH, "JPEG", quality=95)
    print(f"✅ TestFlight 封面: {COVER_PATH.name}")
    return str(COVER_PATH)


# ========== API ==========
def get_access_token():
    url = "https://api.weixin.qq.com/cgi-bin/token"
    params = {"grant_type": "client_credential", "appid": APPID, "secret": APPSECRET}
    resp = requests.get(url, params=params, timeout=15, proxies=NO_PROXY)
    data = resp.json()
    if "access_token" not in data:
        print(f"❌ Token 失败: {data}")
        sys.exit(1)
    return data["access_token"]

def upload_cover(token, path):
    url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={token}&type=image"
    with open(path, "rb") as f:
        resp = requests.post(url, files={"media": (os.path.basename(path), f, "image/jpeg")}, timeout=30, proxies=NO_PROXY)
    data = resp.json()
    if "media_id" not in data:
        print(f"❌ 封面上传失败: {data}")
        sys.exit(1)
    return data["media_id"]

def upload_article_image(token, img_bytes, filename="qr.png"):
    url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={token}&type=image"
    resp = requests.post(url, files={"media": (filename, img_bytes, "image/png")}, timeout=30, proxies=NO_PROXY)
    return resp.json().get("url")

def generate_qr(token, tf_url, idx):
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(tf_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#333333", back_color="#ffffff")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    wx_url = upload_article_image(token, buf.getvalue(), f"tf_qr_{idx}.png")
    if wx_url:
        print(f"  ✅ QR #{idx}")
    return wx_url

# ========== HTML ==========
def build_html(apps, qr_urls, issue):
    count = len(apps)
    html = []

    # 头部
    html.append('<section style="text-align:center;padding:24px 16px 14px;">')
    html.append('<section style="display:inline-block;background:linear-gradient(135deg,#6c3ce0,#3c8ce0);padding:6px 20px;border-radius:20px;">')
    html.append(f'<span style="font-size:14px;font-weight:700;color:#ffffff;letter-spacing:1px;">🧪 第 {issue} 期</span>')
    html.append('</section>')
    html.append('<p style="font-size:26px;font-weight:700;color:#2c2c2c;letter-spacing:1px;margin:16px 0 6px;">TestFlight 每周合集</p>')
    html.append('<p style="font-size:13px;color:#999999;margin:0;">限时测试名额 · 长按扫码加入 · 手慢无</p>')
    html.append('</section>')
    html.append('<section style="text-align:center;padding:4px 0 16px;">')
    html.append('<span style="display:inline-block;width:36px;height:3px;background-color:#6c3ce0;border-radius:2px;"></span>')
    html.append('</section>')
    html.append('<section style="text-align:center;padding:4px 0 16px;">')
    html.append(f'<span style="display:inline-block;font-size:14px;font-weight:600;color:#6c3ce0;border:1px dashed #6c3ce0;border-radius:24px;padding:6px 20px;letter-spacing:1px;">🧪 本周 {count} 款 TestFlight 测试 · 长按扫码加入 ⬇</span>')
    html.append('</section>')

    for i, (name, tf_url) in enumerate(apps):
        idx = i + 1
        html.append('<section style="background-color:#ffffff;border:1px solid #e5dff5;border-radius:10px;margin:0 0 14px;padding:0;">')
        html.append('<section style="padding:16px;">')
        html.append('<section style="margin:0 0 10px;">')
        html.append(f'<span style="display:inline-block;width:30px;height:30px;background-color:#f3eefc;color:#6c3ce0;border-radius:8px;text-align:center;line-height:30px;font-size:14px;font-weight:700;vertical-align:middle;">{idx}</span>')
        html.append(f'<span style="font-size:17px;font-weight:700;color:#2c2c2c;vertical-align:middle;margin:0 6px;">🧪 {name}</span>')
        html.append('<span style="display:inline-block;background-color:#e8f0fc;color:#3c7ce0;font-size:12px;font-weight:700;padding:3px 10px;border-radius:12px;margin:0 0 0 4px;vertical-align:middle;">TestFlight</span>')
        html.append('</section>')
        html.append('<section style="margin:0 0 10px;">')
        html.append('<p style="font-size:13px;color:#6b6b6b;line-height:1.6;margin:0 0 0 42px;padding:8px 12px;background-color:#f9f7fe;border-radius:6px;border-left:3px solid #6c3ce0;">限时 TestFlight 测试名额，点击或扫码加入体验。</p>')
        html.append('</section>')
        if i < len(qr_urls) and qr_urls[i]:
            html.append('<section style="text-align:center;margin:0;">')
            html.append(f'<img src="{qr_urls[i]}" style="width:140px;height:140px;display:inline-block;border:1px solid #e5dff5;border-radius:6px;padding:4px;">')
            html.append('<p style="font-size:11px;color:#999999;margin:4px 0 0;">▲ 长按识别二维码，加入 TestFlight 测试</p>')
            html.append('</section>')
        html.append('</section>')
        html.append('</section>')

    html.append('<section style="text-align:center;padding:20px 16px 8px;">')
    html.append('<p style="font-size:12px;color:#999999;margin:0;">数据来源 global-testflight-link / departures.to / Google 搜索</p>')
    html.append('</section>')

    return "".join(html)


def create_draft(token, title, content, thumb_media_id):
    print(f"📝 创建草稿: {title}")
    url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={token}"
    plain = re.sub(r"<[^>]+>", "", content)[:54]
    payload = {"articles": [{
        "title": title, "author": AUTHOR, "digest": plain,
        "content": content, "thumb_media_id": thumb_media_id,
        "need_open_comment": 0, "only_fans_can_comment": 1,
    }]}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    resp = requests.post(url, data=body, headers={"Content-Type": "application/json; charset=utf-8"}, timeout=30, proxies=NO_PROXY)
    data = resp.json()
    if "media_id" not in data:
        print(f"❌ 创建草稿失败 [{data.get('errcode','?')}]: {data.get('errmsg','?')}")
        sys.exit(1)
    print(f"✅ 草稿 OK! media_id: {data['media_id']}")
    return data["media_id"]


def main():
    if len(sys.argv) < 2:
        print("用法: python tf_weekly_publish.py TestFlight合集_第6期.txt")
        sys.exit(1)

    if not APPID or not APPSECRET:
        print("❌ 请设置 WECHAT_APPID / WECHAT_APPSECRET")
        sys.exit(1)

    txt_file = sys.argv[1]
    print("=" * 50)
    print("  🧪 TestFlight 每周合集发布")
    print("=" * 50)

    issue, apps = parse_tf_txt(txt_file)
    if not apps:
        print("❌ 未解析到 App")
        sys.exit(1)

    title = f"【TestFlight合集】第{issue}期"

    token = get_access_token()
    cover = generate_tf_cover()
    thumb_id = upload_cover(token, cover)

    print("📱 上传 QR 码...")
    qr_urls = []
    for i, (_, tf_url) in enumerate(apps):
        qr_urls.append(generate_qr(token, tf_url, i + 1) if tf_url else None)
    print(f"✅ QR: {len([u for u in qr_urls if u])}/{len(apps)}")

    print("🏗️ 构建 HTML...")
    content = build_html(apps, qr_urls, issue)
    print(f"✅ HTML: {len(content)} 字符")

    media_id = create_draft(token, title, content, thumb_id)
    print(f"🎉 完成！media_id: {media_id}")


if __name__ == "__main__":
    main()
