#!/usr/bin/env python3
"""
TestFlight 每周合集内容生成器 —— 只生成，不调微信 API
输入: TestFlight合集_第N期.txt
输出: output/ 目录（cover.jpg + qr_N.png + article.html + article.json）
用法: python tf_weekly_publisher.py TestFlight合集_第7期.txt
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

# ============================================================
# 配置
# ============================================================
AUTHOR = "卡拉库姆猫"

WORK_DIR = Path(__file__).resolve().parent.parent  # 仓库根目录
OUTPUT_DIR = WORK_DIR / "output"

# ============================================================
# 字体查找（兼容 Linux GitHub Actions）
# ============================================================
def _find_cjk_fonts():
    """查找可用的 CJK 字体"""
    candidates = []
    for root in ["/usr/share/fonts", "/usr/local/share/fonts"]:
        if not os.path.exists(root):
            continue
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                if "NotoSansCJK" in fn and fn.endswith((".ttc", ".ttf", ".otf")):
                    candidates.append(os.path.join(dirpath, fn))
    candidates.append("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc")
    candidates.append("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
    candidates.append("/System/Library/Fonts/PingFang.ttc")
    candidates.append("/System/Library/Fonts/STHeiti Medium.ttc")
    candidates.append("/System/Library/Fonts/Hiragino Sans GB.ttc")
    return candidates

# ============================================================
# 1. TXT 解析
# ============================================================
def parse_tf_txt(filepath):
    path = Path(filepath)
    if not path.exists():
        print(f"❌ 文件不存在: {filepath}")
        sys.exit(1)

    text = path.read_text(encoding="utf-8")
    lines = text.strip().split("\n")

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
            desc = ""
            # 扫描更多行（延长到 10 行，处理带换行的长简介）
            for j in range(i + 1, min(i + 11, len(lines))):
                stripped = lines[j].strip()
                if stripped.startswith("简介："):
                    desc = stripped[3:].strip()
                if "testflight.apple.com/join/" in stripped:
                    url = stripped
                    i = j
                    break
            i += 1
            apps.append((name, url, desc))
        else:
            i += 1

    print(f"📄 解析: {path.name} | 第{issue}期 | {len(apps)} 款")
    return issue, apps


# ============================================================
# 2. 封面图
# ============================================================
def generate_tf_cover():
    """生成 TF 周报封面"""

    BG_PATH = WORK_DIR / "assets" / "tf_cover_bg.png"
    COVER_PATH = OUTPUT_DIR / "cover.jpg"

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

    W, H = img.size
    draw = ImageDraw.Draw(img)

    # 加载字体
    fonts = {}
    font_sizes = {"title": 130, "big": 38, "mid": 28, "small": 22}
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

    COLOR = (255, 255, 255)

    def dc(d, text, font, y, color=COLOR):
        bb = d.textbbox((0, 0), text, font=font)
        d.text(((W - (bb[2] - bb[0])) / 2, y), text, fill=color, font=font)

    dc(draw, "TestFlight", fonts["title"], 130)
    dc(draw, "每周限免合集", fonts["big"], 290)
    dc(draw, "限时测试名额 · 手慢无", fonts["mid"], 380)

    img.convert("RGB").save(COVER_PATH, "JPEG", quality=95)
    print(f"✅ TestFlight 封面: {COVER_PATH}")
    return str(COVER_PATH)


# ============================================================
# 3. QR 码生成（保存到文件）
# ============================================================
def generate_qr(tf_url, idx):
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    if tf_url:
        qr.add_data(tf_url)
    else:
        qr.add_data("https://testflight.apple.com")
    qr.make(fit=True)
    img = qr.make_image(fill_color="#333333", back_color="#ffffff")
    path = OUTPUT_DIR / f"qr_{idx}.png"
    img.save(path, format="PNG")
    print(f"  {'✅' if tf_url else '⚠️'} QR #{idx}")
    return str(path)


# ============================================================
# 4. 构建 HTML（图片用占位符 {{IMG:qr_N}}）
# ============================================================
def build_html(apps, issue):
    count = len(apps)
    html = []

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

    for i, (name, tf_url, desc) in enumerate(apps):
        idx = i + 1
        html.append('<section style="background-color:#ffffff;border:1px solid #e5dff5;border-radius:10px;margin:0 0 14px;padding:0;">')
        html.append('<section style="padding:16px;">')
        html.append('<section style="margin:0 0 10px;">')
        html.append(f'<span style="display:inline-block;width:30px;height:30px;background-color:#f3eefc;color:#6c3ce0;border-radius:8px;text-align:center;line-height:30px;font-size:14px;font-weight:700;vertical-align:middle;">{idx}</span>')
        html.append(f'<span style="font-size:17px;font-weight:700;color:#2c2c2c;vertical-align:middle;margin:0 6px;">🧪 {name}</span>')
        html.append('<span style="display:inline-block;background-color:#e8f0fc;color:#3c7ce0;font-size:12px;font-weight:700;padding:3px 10px;border-radius:12px;margin:0 0 0 4px;vertical-align:middle;">TestFlight</span>')
        html.append('</section>')
        html.append('<section style="margin:0 0 10px;">')
        if desc:
            html.append(f'<p style="font-size:13px;color:#6b6b6b;line-height:1.6;margin:0 0 0 42px;padding:8px 12px;background-color:#f9f7fe;border-radius:6px;border-left:3px solid #6c3ce0;">{desc}</p>')
        else:
            html.append('<p style="font-size:13px;color:#6b6b6b;line-height:1.6;margin:0 0 0 42px;padding:8px 12px;background-color:#f9f7fe;border-radius:6px;border-left:3px solid #6c3ce0;">限时 TestFlight 测试名额，点击或扫码加入体验。</p>')
        html.append('</section>')

        # QR 码：有链接就生成真 QR，没有就留占位空位
        html.append('<section style="text-align:center;margin:0;">')
        if tf_url:
            html.append(f'<img src="{{{{IMG:qr_{i}}}}}" style="width:140px;height:140px;display:inline-block;border:1px solid #e5dff5;border-radius:6px;padding:4px;">')
            html.append('<p style="font-size:11px;color:#999999;margin:4px 0 0;">▲ 长按识别二维码，加入 TestFlight 测试</p>')
        else:
            html.append('<div style="width:140px;height:140px;display:inline-block;border:1px dashed #d0c8e0;border-radius:6px;background-color:#faf8fd;text-align:center;line-height:140px;color:#b0a8c0;font-size:13px;">🔗 直链失效</div>')
            html.append('<p style="font-size:11px;color:#999999;margin:4px 0 0;">请手动搜索 App 名称加入 TestFlight</p>')
        html.append('</section>')

        html.append('</section>')
        html.append('</section>')

    html.append('<section style="text-align:center;padding:20px 16px 8px;">')
    html.append('<p style="font-size:12px;color:#999999;margin:0;">数据来源 global-testflight-link / departures.to / 搜索</p>')
    html.append('</section>')

    return "".join(html)


# ============================================================
# 5. 保存输出
# ============================================================
def save_output(html_content, issue, count):
    html_path = OUTPUT_DIR / "article.html"
    html_path.write_text(html_content, encoding="utf-8")
    print(f"✅ HTML: {len(html_content)} 字符 → {html_path}")

    title = f"【TestFlight合集】第{issue}期"
    plain = re.sub(r"<[^>]+>", "", html_content)[:54]
    digest = plain if plain else "TestFlight限时测试合集，手慢无！"

    manifest = {
        "title": title,
        "author": AUTHOR,
        "digest": digest,
        "type": "tf_weekly",
        "issue": issue,
        "count": count,
        "cover_file": "cover.jpg",
        "html_file": "article.html",
        "qr_files": [f"qr_{i}.png" for i in range(1, count + 1)],
    }
    manifest_path = OUTPUT_DIR / "article.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 元数据: {manifest_path}")


# ============================================================
# Main
# ============================================================
def main():
    if len(sys.argv) < 2:
        print("用法: python tf_weekly_publisher.py TestFlight合集_第7期.txt")
        sys.exit(1)

    txt_file = sys.argv[1]
    txt_path = Path(txt_file)
    if not txt_path.is_absolute() and not txt_path.exists():
        txt_path = WORK_DIR / txt_file
    if not txt_path.exists():
        print(f"❌ 文件不存在: {txt_file} (也尝试了 {txt_path})")
        sys.exit(1)

    print("=" * 50)
    print("  🧪 TestFlight 每周合集内容生成")
    print("=" * 50)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    issue, apps = parse_tf_txt(str(txt_path))
    if not apps:
        print("❌ 未解析到 App")
        sys.exit(1)

    count = len(apps)

    # 1. 生成封面
    generate_tf_cover()

    # 2. 生成 QR 码（每个 App 都生成，没链接的用占位 QR）
    print("📱 生成 QR 码...")
    qr_paths = []
    for i, (_, tf_url, _) in enumerate(apps):
        qr_paths.append(generate_qr(tf_url, i + 1))
    print(f"✅ QR: {len(qr_paths)}/{count}")

    # 3. 生成 HTML（含占位符）
    print("🏗️ 构建 HTML...")
    html_content = build_html(apps, issue)

    # 4. 保存
    save_output(html_content, issue, count)

    print(f"\n✅ 内容生成完成 → {OUTPUT_DIR}")
    print(f"   封面: cover.jpg")
    print(f"   QR 码: {len(qr_paths)} 张")
    print(f"   HTML: article.html")
    print(f"   元数据: article.json")


if __name__ == "__main__":
    main()
