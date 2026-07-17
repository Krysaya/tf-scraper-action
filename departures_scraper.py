# 🛫 departures.to TestFlight 抓取器（纯数据采集，不推送）
import re, json, os, time
from html import unescape as html_unescape
from urllib.request import urlopen, Request

HOME = "https://departures.to"
SENT_APPS_FILE = "departures_sent_apps.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"}

def fetch_home():
    """抓取 departures.to 首页 app 列表（2025-07 新版 HTML 结构）"""
    req = Request(HOME, headers=HEADERS)
    html = urlopen(req, timeout=30).read().decode("utf-8")
    apps = []

    # 匹配每个 app 卡片: <a href="...apps/N?ref=...">...</a>
    blocks = re.findall(
        r'<a\s+href="https://departures\.to/apps/(\d+)[^"]*"[^>]*>(.*?)</a>',
        html, re.DOTALL)

    for app_id, body in blocks:
        # 名字: <h3>Name<span>· time</span></h3>
        name_m = re.search(r'<h3[^>]*>\s*([^<]+)', body)
        name = name_m.group(1).strip() if name_m else ""

        # 描述: <p>...</p>
        desc_m = re.search(r'<p[^>]*>\s*(.*?)\s*</p>', body, re.DOTALL)
        desc = desc_m.group(1).strip() if desc_m else ""

        # 标签: 在 tag area div 中，outer span 含内嵌 span（emoji）
        tags = []
        ta = re.search(
            r'<div class="mt-2 flex flex-wrap[^"]*">(.*?)</div>\s*</div>',
            body, re.DOTALL)
        if ta:
            # strip 所有 HTML，换行分割，emoji 行跳过，取文字行
            raw = re.sub(r'<[^>]+>', '\n', ta.group(1))
            lines = [html_unescape(l.strip()) for l in
                     re.sub(r'\n+', '\n', raw).strip().split('\n') if l.strip()]
            skip_emoji = re.compile(r'^[^\w\u4e00-\u9fff@#&]')
            for line in lines:
                if not skip_emoji.match(line):
                    tags.append(line)

        if name:
            apps.append({
                "id": app_id.strip(),
                "name": name,
                "desc": desc,
                "tags": tags,
            })

    return apps

def fetch_tf_code(app_id):
    url = f"{HOME}/apps/{app_id}"
    try:
        req = Request(url, headers=HEADERS)
        html = urlopen(req, timeout=15).read().decode("utf-8")
    except Exception: return None, "error"
    sn = re.search(r'wire:snapshot="([^"]*)"', html)
    if not sn: return None, "unknown"
    try:
        # 解码 HTML 实体 (departures.to 用 &quot; 等包裹 JSON)
        raw = sn.group(1).replace('&quot;', '"').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        data = json.loads(raw)
        inner = data.get("data", {})
        status = inner.get("status", "unknown")
        tf_url = inner.get("url", "")
    except Exception: return None, "parse_error"
    cm = re.search(r"join/([A-Za-z0-9]+)", tf_url)
    return (cm.group(1) if cm else "", status)

def load_json(path):
    if os.path.exists(path):
        with open(path, "r") as f: return set(json.load(f))
    return set()

def save_json(s, path):
    with open(path, "w") as f: json.dump(sorted(list(s)), f)
