# 🛫 departures.to TestFlight 抓取器（纯数据采集，不推送）
import re, json, os, time
from urllib.request import urlopen, Request

HOME = "https://departures.to"
SENT_APPS_FILE = "departures_sent_apps.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

def fetch_home():
    req = Request(HOME, headers=HEADERS)
    html = urlopen(req, timeout=30).read().decode("utf-8")
    apps = []
    cards = re.findall(
        r'<a\s+href="https://departures\.to/apps/(\d+)"[^>]*>.*?<img[^>]+alt="([^"]*)"[^>]*>'
        r'.*?<div[^>]*>\s*([^<]+)\s*</div>.*?<p[^>]*>\s*([^<]*?)\s*</p>'
        r'((?:(?!</a>).)*)', html, re.DOTALL)
    for app_id, img_alt, name, desc, rest in cards:
        if len(img_alt) > 50: continue
        name, desc = name.strip(), desc.strip()
        tags = [t.strip() for t in re.findall(r'<span[^>]*>([^<]+)</span>', rest) if t.strip()]
        if name: apps.append({"id": app_id.strip(), "name": name, "desc": desc, "tags": tags})
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
        data = json.loads(sn.group(1))
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
