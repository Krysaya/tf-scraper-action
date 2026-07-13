# 🛫 departures.to TestFlight 实时流抓取器
# 与 GitHub scraper 共享 sent_codes.json 去重

import re, json, os, time
from datetime import datetime
from urllib.request import urlopen, Request

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("环境变量 TELEGRAM_BOT_TOKEN 未设置")
CHANNEL = "@ios_collection_ipa"
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

HOME = "https://departures.to"
SENT_FILE = "sent_codes.json"
SENT_APPS_FILE = "departures_sent_apps.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

# ========== 页面抓取 ==========

def fetch_home():
    """抓取 departures.to 首页，提取所有应用卡片"""
    req = Request(HOME, headers=HEADERS)
    html = urlopen(req, timeout=30).read().decode("utf-8")

    card_pat = re.compile(
        r'<a\s+href="https://departures\.to/apps/(\d+)\?ref=homepage">\s*(.*?)\s*</a>',
        re.DOTALL,
    )

    apps = []
    for app_id, card in card_pat.findall(html):
        name = ""
        nm = re.search(r"<h3[^>]*>\s*(.*?)(?:<span|</h3)", card, re.DOTALL)
        if nm:
            name = nm.group(1).strip()

        time_ago = ""
        tm = re.search(r"·\s*([^<]+)\s*<", card)
        if tm:
            time_ago = tm.group(1).strip()

        desc = ""
        dm = re.search(
            r'<p[^>]*class="[^"]*text-md[^"]*"[^>]*>(.*?)</p>', card, re.DOTALL
        )
        if dm:
            desc = re.sub(r"<[^>]+>", "", dm.group(1)).strip()
            desc = re.sub(r"\s+", " ", desc)[:150]

        tags = []
        for tm in re.finditer(
            r"<span[^>]*>[^<]*</span>\s*([^<\s][^<]{1,30})</span>", card
        ):
            t = tm.group(1).strip()
            if t and t not in tags:
                tags.append(t)

        if name:
            apps.append({
                "id": app_id,
                "name": name,
                "time": time_ago,
                "desc": desc,
                "tags": tags,
            })

    return apps


def fetch_tf_code(app_id):
    """访问详情页，从 Livewire snapshot 提取 TF join code 和状态"""
    url = f"{HOME}/apps/{app_id}"
    try:
        req = Request(url, headers=HEADERS)
        html = urlopen(req, timeout=15).read().decode("utf-8")
    except Exception:
        return None, "error"

    sn = re.search(r'wire:snapshot="([^"]*)"', html)
    if not sn:
        return None, "unknown"

    try:
        data = json.loads(sn.group(1))
        inner = data.get("data", {})
        status = inner.get("status", "unknown")
        tf_url = inner.get("url", "")
    except Exception:
        return None, "parse_error"

    code = ""
    cm = re.search(r"join/([A-Za-z0-9]+)", tf_url)
    if cm:
        code = cm.group(1)

    return code, status


def resolve_url(join_code):
    """优先国区，验证失败回退"""
    cn = f"https://testflight.apple.com/join/{join_code}"
    try:
        # 尝试 cn 前缀（TestFlight 不支持 /cn/join，直接用原始链接）
        return cn
    except Exception:
        pass
    return cn


# ========== 去重 ==========

def load_json(path):
    if os.path.exists(path):
        with open(path, "r") as f:
            return set(json.load(f))
    return set()


def save_json(s, path):
    with open(path, "w") as f:
        json.dump(sorted(list(s)), f)


# ========== Telegram ==========

def tg_send(text):
    data = json.dumps({"chat_id": CHANNEL, "text": text}).encode("utf-8")
    req = Request(
        f"{TG_API}/sendMessage",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = urlopen(req, timeout=15)
        return json.loads(resp.read()).get("ok", False)
    except Exception:
        return False


# ========== 主逻辑 ==========

def main():
    print(f"🕐 {datetime.now()} 抓取 departures.to...")

    sent_codes = load_json(SENT_FILE)
    sent_apps = load_json(SENT_APPS_FILE)

    apps = fetch_home()
    print(f"📊 首页共 {len(apps)} 个应用")

    new_entries = []

    for a in apps:
        # 跳过已访问过的 app（避免重复请求详情页）
        if a["id"] in sent_apps:
            continue

        # 跳过太旧的（超过 7 天）
        if "d ago" in a["time"]:
            try:
                days = int(a["time"].split("d")[0])
                if days > 7:
                    sent_apps.add(a["id"])
                    continue
            except Exception:
                pass

        # 访问详情页获取 TF code
        code, status = fetch_tf_code(a["id"])
        sent_apps.add(a["id"])

        if not code:
            print(f"  ⚠️ 无 TF 链接: {a['name'][:30]} ({status})")
            continue

        if status != "open":
            print(f"  🔒 {status}: {a['name'][:30]}")
            continue

        # 去重（与 GitHub scraper 共用 sent_codes）
        if code in sent_codes:
            continue

        sent_codes.add(code)

        url = f"https://testflight.apple.com/join/{code}"

        entry = {
            "name": a["name"],
            "code": code,
            "url": url,
            "desc": a["desc"],
            "tags": a["tags"],
            "time": a["time"],
        }
        new_entries.append(entry)
        print(f"  ✅ {a['name'][:30]} ({a['time']}) → {code}")

        time.sleep(0.3)  # 礼貌限速

    if not new_entries:
        print("✅ 没有新增链接")
        save_json(sent_codes, SENT_FILE)
        save_json(sent_apps, SENT_APPS_FILE)
        return

    print(f"🆕 {len(new_entries)} 条新增")

    for start in range(0, len(new_entries), 10):
        batch = new_entries[start:start + 10]
        now = datetime.now().strftime("%m/%d")
        lines = [f"🛫 TestFlight · departures.to ({now})", ""]
        for i, e in enumerate(batch, start + 1):
            line = f"{i}. {e['name']}"
            if e["desc"]:
                line += f"\n   {e['desc'][:120]}"
            if e["tags"]:
                line += f"\n   {' · '.join(e['tags'][:4])}"
            line += f"\n   {e['url']}"
            lines.append(line)

        msg = "\n".join(lines)
        ok = tg_send(msg)
        print(f"  {'✅' if ok else '❌'} batch {start // 10 + 1}")

    save_json(sent_codes, SENT_FILE)
    save_json(sent_apps, SENT_APPS_FILE)
    print("🏁 完成")


if __name__ == "__main__":
    main()
