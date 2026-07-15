# 📱 oodata.net 今日限免抓取器（纯数据采集，不推送）
# 只负责 fetch_apps() + resolve_appstore_url()
# TG 推送由 tg_push.py 处理

import re, json, os
from datetime import datetime
from urllib.request import urlopen, Request

# ========== 配置 ==========
SITE = "https://apps.oodata.net"
SENT_FILE = "oodata_sent.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; oodata-bot/1.0)"}

def fetch_apps():
    """抓取 oodata.net 今日限免，返回 [{post_id, name, desc, tag, app_id, country}]"""
    req = Request(SITE, headers=HEADERS)
    html = urlopen(req, timeout=30).read().decode("utf-8")
    results = []
    sections = html.split('<header class="')
    for sec in sections:
        pid_match = re.search(r'/posts/(\d+)', sec)
        if not pid_match: continue
        post_id = pid_match.group(1)
        content_match = re.search(r'<div\s+class="[^"]*content[^"]*">(.*?)</div>', sec, re.DOTALL)
        if not content_match: continue
        content = content_match.group(1).strip()
        if content.startswith('<'): continue
        name_match = re.search(r'^\s*([^<]+)', content)
        if not name_match: continue
        name = name_match.group(1).strip()
        if 'Limited-Time Free' in name or 'oodata' in name.lower(): continue
        if '【' in name and '】' in name and 'apps.apple.com' not in content: continue
        app_id, country = "", ""
        app_match = re.search(r'apps\.apple\.com/(?:([a-z]{2})/)?app/id(\d+)', content)
        if app_match:
            country = app_match.group(1) or ""
            app_id = app_match.group(2)
        if not app_id: continue
        desc = ""
        parts = re.split(r'<br[^>]*>', content, maxsplit=3)
        if len(parts) >= 2:
            desc_raw = parts[1].strip()
            desc = re.sub(r'<[^>]+>', '', desc_raw).strip()
            desc = re.sub(r'\s*#.*', '', desc).strip()
        tag = ""
        tag_match = re.search(r'>#([^<]+)</a>', content)
        if tag_match: tag = "#" + tag_match.group(1).strip()
        results.append({'post_id': post_id, 'name': name, 'desc': desc, 'tag': tag, 'app_id': app_id, 'country': country})
    return results

def resolve_appstore_url(app_id, original_country):
    """优先国区 /cn/app/id，失败回退原始"""
    cn_url = f"https://apps.apple.com/cn/app/id{app_id}"
    try:
        req = Request(cn_url, headers=HEADERS)
        resp = urlopen(req, timeout=10)
        if resp.getcode() < 400:
            resp.close()
            return cn_url
    except Exception: pass
    prefix = f"{original_country}/" if original_country else ""
    return f"https://apps.apple.com/{prefix}app/id{app_id}"

def load_sent():
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE, 'r') as f:
            return set(json.load(f))
    return set()

def save_sent(s):
    with open(SENT_FILE, 'w') as f:
        json.dump(sorted(list(s)), f)
