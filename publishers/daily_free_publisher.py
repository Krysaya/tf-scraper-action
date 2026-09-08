#!/usr/bin/env python3
"""
每日限免内容生成器 —— 只生成，不调微信 API
输入: 每日限免MMDD.txt（含双区价格行 + 可选「外区限免」节）
输出: output_daily/ 目录（cover.jpg + qr_N.png + article.html + article.json）
用法: python daily_free_publisher.py 每日限免0907.txt

修正说明（2026-09-07）：
  - 解析双区价格行（中区:<状态>:<原价> | 美区:<状态>:<原价>）与「外区限免」节标记。
  - 卡片区分中区/美区价格与免费状态；仅美区免费的 App 单独成节并标注「需切区」。
  - 翻译修复：fetch_from_itunes 翻译失败返回 None（不泄露英文）；get_desc 只缓存中文。
"""
import os
import sys
import json
import time
import re
from pathlib import Path
from io import BytesIO
from datetime import datetime, timezone, timedelta
BEIJING = timezone(timedelta(hours=8))

import requests
import qrcode
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ── 翻译：英文简介→中文（复用 tf_translate，无缝降级）──
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    import tf_translate as _tft
    _has_cjk  = _tft.has_cjk
    def _translate(text, **kw):
        # 主用腾讯云 TMT，gtx 兜底；失败返回 None（不泄露英文）
        return _tft.tmt_translate(text, **kw) or _tft.gtx_translate(text, **kw)
except Exception as _e:
    _has_cjk  = lambda s: False
    _translate = lambda s, **kw: None
    print(f"⚠️ tf_translate 未加载，简介不翻译: {_e}")

# ============================================================
# 配置
# ============================================================
AUTHOR = "卡拉库姆猫"

WORK_DIR = Path(__file__).resolve().parent.parent  # 仓库根目录
OUTPUT_DIR = WORK_DIR / "output_daily"
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
# iTunes API
# ============================================================
ITUNES_API = "https://itunes.apple.com/lookup?id={}&country=cn"

def extract_app_id(url):
    if not url:
        return None
    m = re.search(r'/id(\d+)', url)
    return m.group(1) if m else None

def fetch_from_itunes(app_id):
    """取国区官方简介并中文化。翻译失败返回 None（不泄露英文），交给 fallback。"""
    try:
        resp = requests.get(
            ITUNES_API.format(app_id),
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        data = resp.json()
        if data.get("resultCount", 0) > 0:
            result = data["results"][0]
            desc = result.get("description", "")
            if desc:
                desc = desc.replace("\n", " ").strip()
                # 英文简介 → 翻译成中文
                if not _has_cjk(desc):
                    zh = _translate(desc[:300])
                    if zh and _has_cjk(zh):
                        desc = zh
                    else:
                        return None  # 翻译失败：不返回英文，交 fallback
                desc = desc[:120] + ("..." if len(desc) > 120 else "")
                return desc
    except Exception:
        pass
    return None

def load_descriptions():
    if DESC_PATH.exists():
        try:
            return json.loads(DESC_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def save_descriptions(desc_map):
    try:
        DESC_PATH.write_text(json.dumps(desc_map, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def get_desc(name, category, url, desc_map):
    """返回中文简介。只缓存中文结果；英文脏缓存视为未命中，重译/回退。"""
    if name in desc_map and desc_map[name]:
        cached = desc_map[name]
        if _has_cjk(cached):
            return cached
        # 英文脏缓存 → 忽略，下面重取

    app_id = extract_app_id(url)
    if app_id:
        desc = fetch_from_itunes(app_id)
        if desc:
            if _has_cjk(desc):
                desc_map[name] = desc
                save_descriptions(desc_map)
            time.sleep(0.3)
            return desc

    # fallback：通用中文占位（仍为中文，可接受；不缓存以便未来取到真实简介）
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
    if _has_cjk(desc):
        desc_map[name] = desc
        save_descriptions(desc_map)
    return desc

# ============================================================
# 1. 文件解析（双区 + 外区节）
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

    main_apps = []
    external_apps = []
    current = main_apps
    i = 1
    while i < len(lines):
        line = lines[i].strip()
        # 「外区限免」节标记 → 切换目标列表
        if line.startswith("【外区限免"):
            current = external_apps
            i += 1
            continue
        match = re.match(r"^\d+\.\s+(.+)$", line)
        if match:
            name = match.group(1).strip()
            cn_status = cn_orig = us_status = us_orig = category = ""
            price = "?"
            url = ""
            if i + 1 < len(lines):
                price_line = lines[i + 1].strip()
                pm = re.match(
                    r"中区:(\S+):(\S+)\s*\|\s*美区:(\S+):(\S+)(?:\s*\|\s*(.+))?",
                    price_line,
                )
                if pm:
                    cn_status, cn_orig, us_status, us_orig = pm.group(1), pm.group(2), pm.group(3), pm.group(4)
                    category = (pm.group(5) or "").strip()
                if i + 2 < len(lines):
                    url_line = lines[i + 2].strip()
                    if url_line.startswith("https://apps.apple.com"):
                        url = url_line
                        i += 1
                i += 1
            i += 1
            current.append({
                "name": name, "category": category, "price": price, "url": url,
                "cn_status": cn_status, "cn_orig": cn_orig,
                "us_status": us_status, "us_orig": us_orig,
            })
        else:
            i += 1

    print(f"📄 解析: {path.name} | {date_str} | 中区 {len(main_apps)} 款 / 外区 {len(external_apps)} 款")
    return date_str, main_apps, external_apps

# ============================================================
# 2. 封面图（兼容 Linux GitHub Actions 字体）
# ============================================================
def _find_cjk_fonts():
    """查找可用的 CJK 字体，Linux 优先 Noto，macOS 优先 PingFang"""
    candidates = []
    # Linux (GitHub Actions)
    for root in ["/usr/share/fonts", "/usr/local/share/fonts"]:
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                if "NotoSansCJK" in fn and ("Bold" in fn or "bold" in fn) and fn.endswith((".ttc", ".ttf", ".otf")):
                    candidates.append(os.path.join(dirpath, fn))
    # Generic fallback fonts on Linux
    candidates.append("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc")
    candidates.append("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
    # macOS
    candidates.append("/System/Library/Fonts/PingFang.ttc")
    candidates.append("/System/Library/Fonts/STHeiti Medium.ttc")
    candidates.append("/System/Library/Fonts/Hiragino Sans GB.ttc")
    return candidates

def generate_cover(date_str, count, total, external_count=0):
    """生成封面图"""

    BG_PATH = WORK_DIR / "assets" / "cover_bg.png"
    COVER_PATH = OUTPUT_DIR / "cover.jpg"

    if BG_PATH.exists():
        print("📸 使用自定义背景 (cover_bg.png)")
        img = Image.open(BG_PATH).convert("RGBA")
    else:
        print("🎨 程序化生成深色背景...")
        import random
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
    draw = ImageDraw.Draw(img)

    # 加载字体
    fonts = {}
    font_sizes = {"title": 90, "mid": 36, "mid2": 30, "small": 22, "hint": 20, "tag": 26}
    for fp in _find_cjk_fonts():
        if os.path.exists(fp):
            try:
                for key, size in font_sizes.items():
                    fonts[key] = ImageFont.truetype(fp, size)
                print(f"✅ 字体: {fp}")
                break
            except Exception:
                continue

    if not fonts:
        for key, size in font_sizes.items():
            fonts[key] = ImageFont.load_default()
        print("⚠️ 使用默认字体")

    COLOR = (87, 140, 186)
    COLOR2 = (87, 147, 196)

    def dc(d, text, font, y, color=COLOR):
        bb = d.textbbox((0, 0), text, font=font)
        d.text(((W - (bb[2] - bb[0])) / 2, y), text, fill=color, font=font)

    def draw_watermark(d, text, font, y_offset=10, x_offset=20):
        bb = d.textbbox((0, 0), text, font=font)
        text_w = bb[2] - bb[0]
        text_h = bb[3] - bb[1]
        d.text((W - text_w - x_offset, H - text_h - y_offset), text, fill=COLOR2, font=font)

    dc(draw, "App Store 每日限免", fonts["title"], 120)
    dc(draw, date_str, fonts["mid"], 270, color=COLOR2)
    sub = f"中区 {count} 款  ·  总价值 ¥{total}"
    if external_count:
        sub += f"  (＋外区 {external_count} 款)"
    dc(draw, sub, fonts.get("mid2", fonts["small"]), 360, color=COLOR2)
    draw_watermark(draw, "卡拉库姆猫", fonts["small"])

    img.convert("RGB").save(COVER_PATH, "JPEG", quality=100)
    print(f"✅ 封面: {COVER_PATH}")
    return str(COVER_PATH)

# ============================================================
# 3. QR 码生成（保存到文件，不上传微信）
# ============================================================
def generate_qr(app_url, idx):
    """生成 QR 码保存到 output_daily/qr_{idx}.png，返回文件路径"""
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(app_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#333333", back_color="#ffffff")
    path = OUTPUT_DIR / f"qr_{idx}.png"
    img.save(path, format="PNG")
    print(f"  ✅ QR #{idx}")
    return str(path)

# ============================================================
# 4. 构建 HTML（图片用占位符 {{IMG:qr_N}}）
# ============================================================
def _region_html(a, is_external):
    """返回该 App 的区域价格区块 HTML。"""
    C_PRIMARY = "#e8724a"
    C_BORDER = "#e8e3db"
    parts = []

    if is_external:
        # 仅美区免费
        parts.append('<section style="margin:0 0 10px;">')
        parts.append('<span style="display:inline-block;background-color:#e8f0fc;color:#3c7ce0;font-size:12px;font-weight:700;padding:3px 10px;border-radius:12px;margin:0 0 6px 0;vertical-align:middle;">仅美区免费 · 需切区</span>')
        parts.append('<br>')
        parts.append('<span style="color:#07a776;font-weight:700;font-size:16px;">美区 免费</span>')
        if a["us_orig"] != "?":
            parts.append(f'<span style="text-decoration:line-through;color:#999999;font-size:13px;margin:0 4px;">原价 {a["us_orig"]}</span>')
        parts.append('</section>')
        parts.append('<section style="margin:0 0 10px;">')
        parts.append(f'<span style="font-size:12px;color:#6b6b6b;">中区：原价 {a["cn_orig"]}（未限免）</span>')
        parts.append('</section>')
    else:
        # 中区免费（正文）
        parts.append('<section style="margin:0 0 10px;">')
        parts.append('<span style="color:#07a776;font-weight:700;font-size:16px;">中区 免费</span>')
        if a["cn_orig"] != "?":
            parts.append(f'<span style="text-decoration:line-through;color:#999999;font-size:13px;margin:0 4px;">原价 {a["cn_orig"]}</span>')
            parts.append(f'<span style="display:inline-block;background-color:#fff0ed;color:{C_PRIMARY};font-size:11px;font-weight:600;padding:2px 8px;border-radius:8px;margin:0 0 0 6px;">省 {a["cn_orig"]}</span>')
        parts.append('</section>')
        # 美区状态
        parts.append('<section style="margin:0 0 10px;">')
        if a["us_status"] == "免费":
            us_txt = "美区 免费" + (f"（原价 {a['us_orig']}）" if a["us_orig"] != "?" else "")
        else:
            us_txt = f"美区 原价 {a['us_orig']}（未限免）" if a["us_orig"] != "?" else "美区 状态未知"
        parts.append(f'<span style="font-size:12px;color:#6b6b6b;">{us_txt}</span>')
        parts.append('</section>')
    return "".join(parts)


def build_html(main_apps, external_apps, date_str):
    total_value = 0
    for a in main_apps:
        o = a.get("cn_orig", "?")
        if o.startswith("¥") and o[1:].isdigit():
            total_value += int(o[1:])
    count = len(main_apps)
    ext_count = len(external_apps)
    desc_map = load_descriptions()

    C_PRIMARY = "#e8724a"
    C_GRAD_START = "#ff7b3d"
    C_GRAD_END = "#e05a2a"
    C_BG_LIGHT = "#fdf0ea"
    C_BG_CARD = "#f9f7f4"
    C_BORDER = "#e8e3db"

    html = []

    html.append('<section style="text-align:center;padding:24px 16px 14px;">')
    html.append(f'<section style="display:inline-block;background:linear-gradient(135deg,{C_GRAD_START},{C_GRAD_END});padding:6px 20px;border-radius:20px;">')
    html.append(f'<span style="font-size:14px;font-weight:700;color:#ffffff;letter-spacing:1px;">{date_str}</span>')
    html.append('</section>')
    html.append('<p style="font-size:26px;font-weight:700;color:#2c2c2c;letter-spacing:1px;margin:16px 0 6px;">App Store 每日限免白嫖</p>')
    html.append('<p style="font-size:13px;color:#999999;margin:0;">iOS限免随时结束 · 长按扫码下载 · 手慢无</p>')
    html.append('</section>')

    html.append('<section style="text-align:center;padding:4px 0 16px;">')
    html.append(f'<span style="display:inline-block;width:36px;height:3px;background-color:{C_PRIMARY};border-radius:2px;"></span>')
    html.append('</section>')

    html.append('<section style="text-align:center;padding:4px 0 16px;">')
    html.append(f'<span style="display:inline-block;font-size:14px;font-weight:600;color:{C_PRIMARY};border:1px dashed {C_PRIMARY};border-radius:24px;padding:6px 20px;letter-spacing:1px;">⬇ 中区 {count} 款限免 · 长按扫码下载 ⬇</span>')
    html.append('</section>')

    html.append('<section style="text-align:center;padding:0 0 20px;">')
    html.append(f'<span style="display:inline-block;font-size:12px;color:#6b6b6b;background-color:#ffffff;border:1px solid {C_BORDER};border-radius:14px;padding:4px 12px;margin:2px 3px;">💰 总价值 <strong style="color:#2c2c2c;">¥{total_value}</strong></span>')
    html.append(f'<span style="display:inline-block;font-size:12px;color:#6b6b6b;background-color:#ffffff;border:1px solid {C_BORDER};border-radius:14px;padding:4px 12px;margin:2px 3px;">🆓 中区全免 <strong style="color:#2c2c2c;">{count}</strong> 款</span>')
    if ext_count:
        html.append(f'<span style="display:inline-block;font-size:12px;color:#3c7ce0;background-color:#ffffff;border:1px solid #cfe0f7;border-radius:14px;padding:4px 12px;margin:2px 3px;">🌏 外区限免 <strong style="color:#3c7ce0;">{ext_count}</strong> 款</span>')
    html.append('<span style="display:inline-block;font-size:12px;color:#6b6b6b;background-color:#ffffff;border:1px solid #e8e3db;border-radius:14px;padding:4px 12px;margin:2px 3px;">⏰ 限时有效</span>')
    html.append('</section>')

    # ── 正文：中区免费 ──
    qr_idx = 0
    for i, a in enumerate(main_apps):
        idx = i + 1
        emoji = CATEGORY_EMOJI.get(a["category"], DEFAULT_EMOJI)
        desc = get_desc(a["name"], a["category"], a["url"], desc_map)

        html.append(f'<section style="background-color:#ffffff;border:1px solid {C_BORDER};border-radius:10px;margin:0 0 14px;padding:0;">')
        html.append('<section style="padding:16px;">')

        html.append('<section style="margin:0 0 10px;">')
        html.append(f'<span style="display:inline-block;width:30px;height:30px;background-color:{C_BG_LIGHT};color:{C_PRIMARY};border-radius:8px;text-align:center;line-height:30px;font-size:14px;font-weight:700;vertical-align:middle;">{idx}</span>')
        html.append(f'<span style="font-size:17px;font-weight:700;color:#2c2c2c;vertical-align:middle;margin:0 6px;">{emoji} {a["name"]}</span>')
        html.append('<span style="display:inline-block;background-color:#e8f7f1;color:#07a776;font-size:12px;font-weight:700;padding:3px 10px;border-radius:12px;margin:0 0 0 4px;vertical-align:middle;">限免中</span>')
        if a["category"]:
            html.append(f'<span style="display:inline-block;background-color:#e8f0fc;color:#3c7ce0;font-size:12px;font-weight:500;padding:3px 10px;border-radius:12px;margin:0 0 0 4px;vertical-align:middle;">{a["category"]}</span>')
        html.append('</section>')

        html.append('<section style="margin:0 0 10px;">')
        html.append(f'<p style="font-size:13px;color:#6b6b6b;line-height:1.6;margin:0 0 0 42px;padding:8px 12px;background-color:{C_BG_CARD};border-radius:6px;border-left:3px solid {C_PRIMARY};">{desc}</p>')
        html.append('</section>')

        html.append(_region_html(a, is_external=False))

        # 占位符：Worker 上传后替换为真实微信图片 URL
        if a["url"]:
            qr_idx += 1
            html.append('<section style="text-align:center;margin:0;">')
            html.append(f'<img src="{{{{IMG:qr_{qr_idx-1}}}}}" style="width:140px;height:140px;display:inline-block;border:1px solid {C_BORDER};border-radius:6px;padding:4px;">')
            html.append('<p style="font-size:11px;color:#999999;margin:4px 0 0;">▲ 长按识别二维码，跳转 App Store 下载</p>')
            html.append('</section>')

        html.append('</section>')
        html.append('</section>')

    # ── 外区限免节 ──
    if external_apps:
        html.append('<section style="text-align:center;padding:20px 16px 4px;">')
        html.append(f'<span style="display:inline-block;font-size:15px;font-weight:700;color:#3c7ce0;border:1px dashed #3c7ce0;border-radius:20px;padding:6px 18px;letter-spacing:1px;">🌏 外区限免 · 需切换 Apple ID 地区后下载</span>')
        html.append('</section>')
        html.append('<section style="text-align:center;padding:0 16px 10px;">')
        html.append('<p style="font-size:12px;color:#999999;margin:6px 0 0;">以下 App 仅美区免费，国区仍为付费。请在 App Store 切换至美区账号后扫码下载。</p>')
        html.append('</section>')

        for i, a in enumerate(external_apps):
            idx = i + 1
            emoji = CATEGORY_EMOJI.get(a["category"], DEFAULT_EMOJI)
            desc = get_desc(a["name"], a["category"], a["url"], desc_map)

            html.append(f'<section style="background-color:#ffffff;border:1px solid #cfe0f7;border-radius:10px;margin:0 0 14px;padding:0;">')
            html.append('<section style="padding:16px;">')

            html.append('<section style="margin:0 0 10px;">')
            html.append(f'<span style="display:inline-block;width:30px;height:30px;background-color:#e8f0fc;color:#3c7ce0;border-radius:8px;text-align:center;line-height:30px;font-size:14px;font-weight:700;vertical-align:middle;">{idx}</span>')
            html.append(f'<span style="font-size:17px;font-weight:700;color:#2c2c2c;vertical-align:middle;margin:0 6px;">{emoji} {a["name"]}</span>')
            if a["category"]:
                html.append(f'<span style="display:inline-block;background-color:#e8f0fc;color:#3c7ce0;font-size:12px;font-weight:500;padding:3px 10px;border-radius:12px;margin:0 0 0 4px;vertical-align:middle;">{a["category"]}</span>')
            html.append('</section>')

            html.append('<section style="margin:0 0 10px;">')
            html.append(f'<p style="font-size:13px;color:#6b6b6b;line-height:1.6;margin:0 0 0 42px;padding:8px 12px;background-color:{C_BG_CARD};border-radius:6px;border-left:3px solid #3c7ce0;">{desc}</p>')
            html.append('</section>')

            html.append(_region_html(a, is_external=True))

            if a["url"]:
                qr_idx += 1
                html.append('<section style="text-align:center;margin:0;">')
                html.append(f'<img src="{{{{IMG:qr_{qr_idx-1}}}}}" style="width:140px;height:140px;display:inline-block;border:1px solid {C_BORDER};border-radius:6px;padding:4px;">')
                html.append('<p style="font-size:11px;color:#999999;margin:4px 0 0;">▲ 长按识别二维码，跳转美区 App Store 下载</p>')
                html.append('</section>')

            html.append('</section>')
            html.append('</section>')

    today = datetime.now(BEIJING).strftime("%Y-%m-%d")
    html.append('<section style="text-align:center;padding:20px 16px 8px;">')
    html.append(f'<p style="font-size:12px;color:#999999;line-height:1.8;margin:0;"><span style="color:{C_PRIMARY};">●</span> 限免价格随时可能恢复 · 下载前请确认最终价格 <span style="color:{C_PRIMARY};">●</span></p>')
    html.append(f'<p style="font-size:11px;color:#999999;margin:6px 0 0;">数据来源 App Store · 更新于 {today}</p>')
    html.append('</section>')

    return "".join(html), qr_idx

# ============================================================
# 5. 保存输出
# ============================================================
def save_output(html_content, qr_paths, date_str, count, total, ext_count):
    """保存 HTML 和元数据到 output_daily/"""

    # 保存 HTML
    html_path = OUTPUT_DIR / "article.html"
    html_path.write_text(html_content, encoding="utf-8")
    print(f"✅ HTML: {len(html_content)} 字符 → {html_path}")

    # 保存元数据
    title = f"App Store 每日限免 · {date_str.replace(' / ', '/')}"
    plain = re.sub(r"<[^>]+>", "", html_content).replace(" ", "").replace("\n", "")
    digest = plain[:54] if plain else "今日限免App合集，手慢无！"

    manifest = {
        "title": title,
        "author": AUTHOR,
        "digest": digest,
        "type": "daily_free",
        "date": date_str,
        "count": count,
        "external_count": ext_count,
        "total_value": total,
        "cover_file": "cover.jpg",
        "html_file": "article.html",
        "qr_files": [f"qr_{i}.png" for i in range(1, len(qr_paths) + 1)],
    }
    manifest_path = OUTPUT_DIR / "article.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 元数据: {manifest_path}")

# ============================================================
# Main
# ============================================================
def main():
    if len(sys.argv) < 2:
        print("用法: python daily_free_publisher.py 每日限免0907.txt")
        sys.exit(1)

    txt_file = sys.argv[1]

    # 如果参数是相对路径，相对于仓库根目录
    txt_path = Path(txt_file)
    if not txt_path.is_absolute() and not txt_path.exists():
        txt_path = WORK_DIR / txt_file
    if not txt_path.exists():
        print(f"❌ 文件不存在: {txt_file} (也尝试了 {txt_path})")
        sys.exit(1)

    print("=" * 50)
    print("  📱 每日限免内容生成")
    print("=" * 50)

    # 创建输出目录
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    date_str, main_apps, external_apps = parse_txt_file(str(txt_path))
    if not main_apps and not external_apps:
        print("❌ 未解析到 App 数据")
        sys.exit(1)

    count = len(main_apps)
    ext_count = len(external_apps)
    total = 0
    for a in main_apps:
        o = a.get("cn_orig", "?")
        if o.startswith("¥") and o[1:].isdigit():
            total += int(o[1:])

    # 1. 生成封面
    generate_cover(date_str, count, total, ext_count)

    # 2. 生成 QR 码（按 HTML 出现顺序：中区 + 外区）
    all_apps = main_apps + external_apps
    print("📱 生成 QR 码...")
    qr_paths = []
    for a in all_apps:
        qr_paths.append(generate_qr(a["url"], len(qr_paths) + 1) if a["url"] else None)
    ok = len([p for p in qr_paths if p])
    print(f"✅ QR: {ok}/{len(all_apps)}")

    # 3. 生成 HTML（含占位符）
    print("🏗️ 构建 HTML...")
    html_content, _ = build_html(main_apps, external_apps, date_str)

    # 4. 保存所有输出
    save_output(html_content, qr_paths, date_str, count, total, ext_count)

    print(f"\n✅ 内容生成完成 → {OUTPUT_DIR}")
    print(f"   中区: {count} 款 | 外区: {ext_count} 款")
    print(f"   封面: cover.jpg")
    print(f"   QR 码: {ok} 张")
    print(f"   HTML: article.html")
    print(f"   元数据: article.json")


if __name__ == "__main__":
    main()
