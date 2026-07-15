# 📱 mergeek.com 限免抓取器（纯数据采集，不推送）
# 只负责 fetch_apps() + search_app_id() + resolve_url()
# TG 推送由 tg_push.py 处理

import re, json, os, time
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.parse import quote

# ========== 配置 ==========
SITE = "https://mergeek.com/free/apps"
SENT_FILE = "mergeek_sent.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# ========== Apple Search API ==========
def search_app_id(name):
    """用 Apple Search API 查找 App Store ID"""
    try:
        url = f"https://itunes.apple.com/search?term={quote(name)}&country=cn&entity=software&limit=3"
        req = Request(url, headers=HEADERS)
        resp = urlopen(req, timeout=10)
        data = json.loads(resp.read())
        if data["resultCount"] > 0:
            return data["results"][0]["trackId"]
    except Exception:
        pass
    return None

# ========== CN App Store URL ==========
def resolve_url(app_id):
    """优先国区，失败回退通用链接"""
    cn_url = f"https://apps.apple.com/cn/app/id{app_id}"
    try:
        req = Request(cn_url, headers=HEADERS)
        resp = urlopen(req, timeout=8)
        if resp.getcode() < 400:
            resp.close()
            return cn_url
    except Exception:
        pass
    return f"https://apps.apple.com/app/id{app_id}"

# ========== 页面抓取 ==========
def fetch_apps():
    """抓取 mergeek 限免页面，返回 [{slug, name, price, category, rating, type}]"""
    req = Request(SITE, headers=HEADERS)
    html = urlopen(req, timeout=30).read().decode("utf-8")
    results = []

    # 1. 有原价的 FREE 应用
    slug_pattern = re.compile(
        r'onclick=toDetail\(&#39;([^&]+)&#39;\)[^>]*>\s*([^<]+?)\s*</a>'
    )
    seen = set()
    for slug, name in slug_pattern.findall(html):
        short_slug = slug.split("/")[-1]
        name = name.strip()
        if len(name) > 40 or short_slug in seen:
            continue
        seen.add(short_slug)
        idx = html.find(slug)
        if idx == -1:
            continue
        context = html[max(0, idx - 600):min(len(html), idx + 2500)]
        if "selected_freezing" in context or "FREE" not in context:
            continue
        price = None
        pm = re.search(r"(\d+(?:\.\d+)?)\s*(?:&#20803;|元)", context)
        if pm:
            price = pm.group(1)
        cat, rating = "", ""
        cm = re.search(r'class="[^"]*meta-category[^"]*"[^>]*>.*?<a[^>]*>\s*([^<]+?)\s*</a>', context, re.DOTALL)
        if cm: cat = cm.group(1).strip()
        rm = re.search(r'(\d+\.?\d*)\s*·\s*(\d+)\s*(?:&#20010;&#35780;&#20998;|个评分)', context)
        if rm: rating = f"⭐{rm.group(1)} ({rm.group(2)}评)"
        results.append({"slug": short_slug, "name": name, "price": price, "category": cat, "rating": rating, "type": "限免"})

    # 2. 长期免费应用
    free_titles = re.findall(r'class="[^"]*selected-free-title[^"]*"[^>]*>\s*([^<]+?)\s*</', html)
    free_tags = re.findall(r'class="[^"]*selected-free-tag[^"]*"[^>]*>\s*#([^<]+?)\s*</', html)
    for name in free_titles:
        name = name.strip()
        if not name or name in seen: continue
        seen.add(name)
        free_count = len([r for r in results if r["type"] == "免费"])
        tag = free_tags[free_count] if free_count < len(free_tags) else ""
        results.append({"slug": name, "name": name, "price": None, "category": tag[:8] if tag else "", "rating": "", "type": "免费"})
    return results


def load_sent():
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_sent(s):
    with open(SENT_FILE, "w") as f:
        json.dump(sorted(list(s)), f)
