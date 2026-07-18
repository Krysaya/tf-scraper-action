#!/usr/bin/env python3
"""
微信公众号每日限免 CI 发布脚本（供 GitHub Actions 使用）
环境变量: WECHAT_APPID, WECHAT_APPSECRET
用法: python wechat_publish_ci.py 每日限免0710.txt
"""

import os
import sys
import json
import time
import re
import math
import random
from pathlib import Path
from io import BytesIO

import requests
import qrcode
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ============================================================
# 配置（从环境变量读取）
# ============================================================
# 微信 API 国内直连，跳过系统代理（避免代理 IP 变化导致白名单失效）
NO_PROXY = {"http": "", "https": ""}

APPID = os.environ.get("WECHAT_APPID", "").strip()
APPSECRET = os.environ.get("WECHAT_APPSECRET", "").strip()
AUTHOR = "卡拉库姆猫"

WORK_DIR = Path(__file__).parent
COVER_PATH = WORK_DIR / "cover.jpg"
BG_PATH = WORK_DIR / "cover_bg.png"     # 自定义背景图（用户下载，脚本在上面画文字）
TOKEN_CACHE = WORK_DIR / ".token_cache.json"
DESC_PATH = WORK_DIR / "descriptions.json"

CATEGORY_EMOJI = {
    "生活": "🌿", "工具": "🔧", "效率": "📖", "教育": "📚",
    "财务": "🔢", "音乐": "🎭", "天气": "🌦️", "健康": "💊",
    "摄影": "📷", "游戏": "🎮", "社交": "💬", "购物": "🛒",
    "美食": "🍔", "旅游": "✈️", "体育": "⚽", "新闻": "📰",
    "医疗": "🏥", "图书": "📕", "商务": "💼", "娱乐": "🎉",
    "软件开发": "💻", "金融": "💰", "导航": "🗺️", "视频": "🎬",
}
DEFAULT_EMOJI = "📱"

# ============================================================
# iTunes API — 自动获取 App 真实简介
# ============================================================
ITUNES_API = "https://itunes.apple.com/lookup?id={}&country=cn"

def extract_app_id(url):
    """从 App Store URL 提取数字 ID"""
    if not url:
        return None
    m = re.search(r'/id(\d+)', url)
    return m.group(1) if m else None

def fetch_from_itunes(app_id):
    """通过 iTunes API 获取应用简介（截取前 120 字）"""
    try:
        resp = requests.get(
            ITUNES_API.format(app_id),
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
            proxies=NO_PROXY
        )
        data = resp.json()
        if data.get("resultCount", 0) > 0:
            result = data["results"][0]
            desc = result.get("description", "")
            if desc:
                desc = desc[:120].replace("\n", " ") + ("..." if len(desc) > 120 else "")
                return desc
    except Exception:
        pass
    return None

def save_descriptions(desc_map):
    """持久化简介缓存到 descriptions.json"""
    try:
        DESC_PATH.write_text(json.dumps(desc_map, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

# ============================================================
# 1. 文件解析
# ============================================================
def parse_txt_file(filepath):
    path = Path(filepath)
    if not path.exists():
        print(f"❌ 文件不存在: {filepath}")
        sys.exit(1)

    text = path.read_text(encoding="utf-8")
    lines = text.strip().split("\n")

    date_match = re.search(r"(\d{2})/(\d{2})", lines[0]) if lines else None
    month = day = "??"
    if date_match:
        month, day = date_match.group(1), date_match.group(2)
    date_str = f"{month} / {day}"

    apps = []
    i = 1
    while i < len(lines):
        line = lines[i].strip()
        match = re.match(r"^\d+\.\s+(.+)$", line)
        if match:
            name = match.group(1).strip()
            price, category, url = "?", "", ""
            if i + 1 < len(lines):
                price_line = lines[i + 1].strip()
                pm = re.match(r"原价\s*¥(\d+)\s*→\s*免费\s*(?:\|\s*(.+))?", price_line)
                if pm:
                    price = f"¥{pm.group(1)}"
                    category = pm.group(2) or ""
                if i + 2 < len(lines):
                    url_line = lines[i + 2].strip()
                    if url_line.startswith("https://apps.apple.com"):
                        url = url_line
                        i += 1
                i += 1
            i += 1
            apps.append((name, category, price, url))
        else:
            i += 1

    print(f"📄 解析: {path.name} | {date_str} | {len(apps)} 款")
    return date_str, apps

# ============================================================
# 2. 描述管理
# ============================================================
def load_descriptions():
    if DESC_PATH.exists():
        try:
            return json.loads(DESC_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def get_desc(name, category, url, desc_map):
    if name in desc_map:
        return desc_map[name]

    # 尝试从 iTunes API 获取真实简介
    app_id = extract_app_id(url)
    if app_id:
        desc = fetch_from_itunes(app_id)
        if desc:
            desc_map[name] = desc
            save_descriptions(desc_map)
            time.sleep(0.3)  # 避免请求过快
            return desc

    # iTunes API 失败，用模板兜底（不破坏现有流程）
    fallback = {
        "生活": "实用生活工具，让日常更智能便捷。",
        "工具": "高效实用工具，解决具体需求。",
        "效率": "提升工作学习效率的利器。",
        "教育": "寓教于乐，随时随地学习新知识。",
        "财务": "财务管理好帮手，数据清晰一目了然。",
        "音乐": "音乐爱好者的随身宝库。",
        "天气": "精准天气预报，出行必备。",
        "健康": "健康管理应用，关注你的身体状况。",
        "摄影": "摄影修图工具，记录精彩瞬间。",
        "游戏": "休闲娱乐游戏，放松心情的好选择。",
    }
    desc = fallback.get(category, f"精品{category}类应用，限时免费中。")
    desc_map[name] = desc
    return desc

# ============================================================
# 3. access_token
# ============================================================
def get_access_token():
    print("🔑 获取 access_token...")
    url = "https://api.weixin.qq.com/cgi-bin/token"
    params = {"grant_type": "client_credential", "appid": APPID, "secret": APPSECRET}
    resp = requests.get(url, params=params, timeout=15, proxies=NO_PROXY)
    data = resp.json()

    if "access_token" not in data:
        print(f"❌ Token 失败 [{data.get('errcode','?')}]: {data.get('errmsg','?')}")
        sys.exit(1)

    print(f"✅ Token OK (有效期 {data.get('expires_in', 7200)}s)")
    return data["access_token"]

# ============================================================
# 4. 封面图
# ============================================================
def generate_cover(date_str, count, total):
    """生成封面：参考 cover-old.jpg 设计风格，背景用 cover_bg.png"""

    # ---------- 1. 加载背景 ----------
    if BG_PATH.exists():
        print("📸 使用自定义背景 (cover_bg.png)")
        img = Image.open(BG_PATH).convert("RGBA")
    else:
        print("🎨 程序化生成深色背景...")
        random.seed(42)
        W, H = 900, 500
        img = Image.new("RGB", (W, H))
        pixels = img.load()
        for y in range(H):
            ratio = y / H
            r, g, b = int(8 + ratio * 25), int(5 + ratio * 20), int(30 + ratio * 60)
            for x in range(W):
                pixels[x, y] = (r, g, b)

        glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow_layer, "RGBA")
        for cx, cy, r, c in [
            (700, -80, 340, (120, 30, 200, 45)), (80, 400, 300, (20, 120, 220, 50)),
            (-60, -60, 280, (200, 50, 100, 35)), (850, 350, 250, (30, 180, 160, 40)),
        ]:
            gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
        img = Image.alpha_composite(img.convert("RGBA"), glow_layer.filter(ImageFilter.GaussianBlur(60))).convert("RGB")

    W, H = img.size

    # ---------- 2. 加载字体（PingFang Bold 优先） ----------
    draw = ImageDraw.Draw(img)
    fonts = {}
    font_candidates_bold = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
    ]
    for fp in font_candidates_bold:
        if os.path.exists(fp):
            try:
                fonts["title"] = ImageFont.truetype(fp, 90)      # App Store 每日限免（最大）
                fonts["mid"] = ImageFont.truetype(fp, 36)        # 日期
                fonts["mid2"] = ImageFont.truetype(fp, 30)       # 数量
                fonts["small"] = ImageFont.truetype(fp, 22)      # 副标题
                fonts["hint"] = ImageFont.truetype(fp, 20)       # 底部
                fonts["tag"] = ImageFont.truetype(fp, 26)        # 顶部 tag
                break
            except Exception:
                continue
    if not fonts:
        fonts["title"] = fonts["mid"] = fonts["small"] = ImageFont.load_default()

    # ---------- 3. 画文字（统一深灰蓝色，无描边） ----------
    COLOR = (87, 140, 186)  # #578CB0
    COLOR2 = (87, 147, 196)  # 标题以下文字（日期/数量/水印）

    def dc(d, text, font, y, color=COLOR):
        """居中绘制"""
        bb = d.textbbox((0, 0), text, font=font)
        d.text(((W - (bb[2] - bb[0])) / 2, y), text, fill=color, font=font)

    def draw_watermark(d, text, font, y_offset=10, x_offset=20):
        """右下角水印（不居中）"""
        bb = d.textbbox((0, 0), text, font=font)
        text_w = bb[2] - bb[0]
        text_h = bb[3] - bb[1]
        d.text((W - text_w - x_offset, H - text_h - y_offset), text, fill=COLOR2, font=font)

    # 主标题（最大，靠上）
    dc(draw, "App Store 每日限免", fonts["title"], 120)

    # 日期（中间）
    dc(draw, date_str, fonts["mid"], 270, color=COLOR2)

    # 数量和价值（中间偏下）
    dc(draw, f"今日 {count} 款  ·  总价值 ¥{total}", fonts.get("mid2", fonts["small"]), 360, color=COLOR2)

    # 右下角水印
    draw_watermark(draw, "卡拉库姆猫", fonts["small"])

    # ---------- 4. 保存 ----------
    img.convert("RGB").save(COVER_PATH, "JPEG", quality=100)
    print(f"✅ 封面: {COVER_PATH.name}")
    return str(COVER_PATH)

# ============================================================
# 5. 上传
# ============================================================
def upload_cover(token, cover_path):
    print("📤 上传封面...")
    url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={token}&type=image"
    with open(cover_path, "rb") as f:
        resp = requests.post(url, files={"media": (os.path.basename(cover_path), f, "image/jpeg")}, timeout=30, proxies=NO_PROXY)
    data = resp.json()
    if "media_id" not in data:
        print(f"❌ 封面上传失败: {data.get('errmsg', data)}")
        sys.exit(1)
    print(f"✅ 封面 OK, media_id: {data['media_id']}")
    return data["media_id"]

def upload_article_image(token, img_bytes, filename="qr.png"):
    """上传文章内图片 → 返回可嵌入 HTML 的 URL（用 material/add_material，不走 uploadimg 额度）"""
    url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={token}&type=image"
    resp = requests.post(url, files={"media": (filename, img_bytes, "image/png")}, timeout=30, proxies=NO_PROXY)
    data = resp.json()
    return data.get("url")

def generate_and_upload_qr(token, app_url, idx):
    """生成 QR 码并通过 material/add_material 上传"""
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(app_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#333333", back_color="#ffffff")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    wx_url = upload_article_image(token, buf.getvalue(), f"qr_{idx}.png")
    if wx_url:
        print(f"  ✅ QR #{idx}")
    return wx_url

# ============================================================
# 6. 构建 HTML（模板风格：TestFlight合集_预览.html）
# ============================================================
def build_html(apps, qr_urls, date_str):
    total_value = sum(int(p.replace("¥", "")) for _, _, p, _ in apps if p != "?" and p.replace("¥", "").isdigit())
    count = len(apps)
    desc_map = load_descriptions()

    # 橙色系配色常量
    C_PRIMARY = "#e8724a"
    C_GRAD_START = "#ff7b3d"
    C_GRAD_END = "#e05a2a"
    C_BG_LIGHT = "#fdf0ea"
    C_BG_CARD = "#f9f7f4"
    C_BORDER = "#e8e3db"

    html = []
    # ── 头部 ──
    html.append('<section style="text-align:center;padding:24px 16px 14px;">')
    html.append(f'<section style="display:inline-block;background:linear-gradient(135deg,{C_GRAD_START},{C_GRAD_END});padding:6px 20px;border-radius:20px;">')
    html.append(f'<span style="font-size:14px;font-weight:700;color:#ffffff;letter-spacing:1px;">{date_str}</span>')
    html.append('</section>')
    html.append('<p style="font-size:26px;font-weight:700;color:#2c2c2c;letter-spacing:1px;margin:16px 0 6px;">App Store 每日限免白嫖</p>')
    html.append('<p style="font-size:13px;color:#999999;margin:0;">iOS限免随时结束 · 长按扫码下载 · 手慢无</p>')
    html.append('</section>')

    # ── 分隔线 ──
    html.append('<section style="text-align:center;padding:4px 0 16px;">')
    html.append(f'<span style="display:inline-block;width:36px;height:3px;background-color:{C_PRIMARY};border-radius:2px;"></span>')
    html.append('</section>')

    # ── 统计标签 ──
    html.append('<section style="text-align:center;padding:4px 0 16px;">')
    html.append(f'<span style="display:inline-block;font-size:14px;font-weight:600;color:{C_PRIMARY};border:1px dashed {C_PRIMARY};border-radius:24px;padding:6px 20px;letter-spacing:1px;">⬇ 今日 {count} 款限免 · 长按扫码下载 ⬇</span>')
    html.append('</section>')

    html.append('<section style="text-align:center;padding:0 0 20px;">')
    html.append(f'<span style="display:inline-block;font-size:12px;color:#6b6b6b;background-color:#ffffff;border:1px solid {C_BORDER};border-radius:14px;padding:4px 12px;margin:2px 3px;">💰 总价值 <strong style="color:#2c2c2c;">¥{total_value}</strong></span>')
    html.append(f'<span style="display:inline-block;font-size:12px;color:#6b6b6b;background-color:#ffffff;border:1px solid {C_BORDER};border-radius:14px;padding:4px 12px;margin:2px 3px;">🆓 今日全免 <strong style="color:#2c2c2c;">{count}</strong> 款</span>')
    html.append('<span style="display:inline-block;font-size:12px;color:#6b6b6b;background-color:#ffffff;border:1px solid #e8e3db;border-radius:14px;padding:4px 12px;margin:2px 3px;">⏰ 限时有效</span>')
    html.append('</section>')

    # ── App 卡片 ──
    for i, (name, category, price, url) in enumerate(apps):
        idx = i + 1
        saved = price.replace("¥", "")
        fire = "🔥 " if saved.isdigit() and int(saved) >= 50 else ""
        emoji = CATEGORY_EMOJI.get(category, DEFAULT_EMOJI)
        desc = get_desc(name, category, url, desc_map)

        html.append(f'<section style="background-color:#ffffff;border:1px solid {C_BORDER};border-radius:10px;margin:0 0 14px;padding:0;">')
        html.append('<section style="padding:16px;">')

        # 编号 + 名称 + 标签
        html.append('<section style="margin:0 0 10px;">')
        html.append(f'<span style="display:inline-block;width:30px;height:30px;background-color:{C_BG_LIGHT};color:{C_PRIMARY};border-radius:8px;text-align:center;line-height:30px;font-size:14px;font-weight:700;vertical-align:middle;">{idx}</span>')
        html.append(f'<span style="font-size:17px;font-weight:700;color:#2c2c2c;vertical-align:middle;margin:0 6px;">{emoji} {name}</span>')
        html.append('<span style="display:inline-block;background-color:#e8f7f1;color:#07a776;font-size:12px;font-weight:700;padding:3px 10px;border-radius:12px;margin:0 0 0 4px;vertical-align:middle;">限免中</span>')
        if category:
            html.append(f'<span style="display:inline-block;background-color:#e8f0fc;color:#3c7ce0;font-size:12px;font-weight:500;padding:3px 10px;border-radius:12px;margin:0 0 0 4px;vertical-align:middle;">{category}</span>')
        html.append('</section>')

        # 简介
        html.append('<section style="margin:0 0 10px;">')
        html.append(f'<p style="font-size:13px;color:#6b6b6b;line-height:1.6;margin:0 0 0 42px;padding:8px 12px;background-color:{C_BG_CARD};border-radius:6px;border-left:3px solid {C_PRIMARY};">{desc}</p>')
        html.append('</section>')

        # 价格
        html.append('<section style="margin:0 0 10px;">')
        if price != "?":
            html.append(f'<span style="text-decoration:line-through;color:#999999;font-size:14px;">{price}</span>')
            html.append('<span style="color:#999999;font-size:12px;margin:0 4px;">→</span>')
        html.append('<span style="color:#07a776;font-weight:700;font-size:16px;">免费</span>')
        if price != "?":
            html.append(f'<span style="display:inline-block;background-color:#fff0ed;color:{C_PRIMARY};font-size:11px;font-weight:600;padding:2px 8px;border-radius:8px;margin:0 0 0 6px;">{fire}省 {price}</span>')
        html.append('</section>')

        # QR 码
        if i < len(qr_urls) and qr_urls[i]:
            html.append('<section style="text-align:center;margin:0;">')
            html.append(f'<img src="{qr_urls[i]}" style="width:140px;height:140px;display:inline-block;border:1px solid {C_BORDER};border-radius:6px;padding:4px;">')
            html.append('<p style="font-size:11px;color:#999999;margin:4px 0 0;">▲ 长按识别二维码，跳转 App Store 下载</p>')
            html.append('</section>')

        html.append('</section>')
        html.append('</section>')

    # ── 底部 ──
    today = time.strftime("%Y-%m-%d")
    html.append('<section style="text-align:center;padding:20px 16px 8px;">')
    html.append(f'<p style="font-size:12px;color:#999999;line-height:1.8;margin:0;"><span style="color:{C_PRIMARY};">●</span> 限免价格随时可能恢复 · 下载前请确认最终价格 <span style="color:{C_PRIMARY};">●</span></p>')
    html.append(f'<p style="font-size:11px;color:#999999;margin:6px 0 0;">数据来源 App Store · 更新于 {today}</p>')
    html.append('</section>')
    return "".join(html)

# ============================================================
# 7. 创建草稿
# ============================================================
def create_draft(token, title, content, thumb_media_id):
    print(f"📝 创建草稿: {title}")
    url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={token}"
    plain = re.sub(r"<[^>]+>", "", content).replace(" ", "").replace("\n", "")
    digest = plain[:54] if plain else "今日限免App合集，手慢无！"
    payload = {
        "articles": [{
            "title": title, "author": AUTHOR, "digest": digest,
            "content": content, "thumb_media_id": thumb_media_id,
            "need_open_comment": 0, "only_fans_can_comment": 1,
        }]
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    resp = requests.post(url, data=body, headers={"Content-Type": "application/json; charset=utf-8"}, timeout=30, proxies=NO_PROXY)
    data = resp.json()
    if "media_id" not in data:
        print(f"❌ 创建草稿失败 [{data.get('errcode','?')}]: {data.get('errmsg','?')}")
        sys.exit(1)
    print(f"✅ 草稿 OK! media_id: {data['media_id']}")
    return data["media_id"]

# ============================================================
# Main
# ============================================================
def main():
    if len(sys.argv) < 2:
        print("用法: python wechat_publish_ci.py 每日限免0710.txt")
        sys.exit(1)

    if not APPID or not APPSECRET:
        print("❌ 请设置环境变量 WECHAT_APPID 和 WECHAT_APPSECRET")
        sys.exit(1)

    txt_file = sys.argv[1]
    print("=" * 50)
    print("  🚀 公众号 CI 发布")
    print("=" * 50)

    date_str, apps = parse_txt_file(txt_file)
    if not apps:
        print("❌ 未解析到 App 数据")
        sys.exit(1)

    count = len(apps)
    total = sum(int(p.replace("¥", "")) for _, _, p, _ in apps if p != "?" and p.replace("¥", "").isdigit())
    title = f"App Store 每日限免 · {date_str.replace(' / ', '/')}"

    token = get_access_token()
    cover_path = generate_cover(date_str, count, total)
    thumb_media_id = upload_cover(token, cover_path)

    print("📱 上传 QR 码...")
    qr_urls = []
    for i, (_, _, _, url) in enumerate(apps):
        qr_urls.append(generate_and_upload_qr(token, url, i + 1) if url else None)
    ok = len([u for u in qr_urls if u])
    print(f"✅ QR: {ok}/{count}")

    print("🏗️ 构建 HTML...")
    content = build_html(apps, qr_urls, date_str)
    print(f"✅ HTML: {len(content)} 字符")

    media_id = create_draft(token, title, content, thumb_media_id)
    print(f"\n🎉 完成！去 mp.weixin.qq.com → 草稿箱 查看")
    print(f"   media_id: {media_id}")

if __name__ == "__main__":
    main()

