#!/usr/bin/env python3
"""
TestFlight 三源合并器 — scraper.py + departures_scraper.py + Google 搜索
用法: python tf_merger.py [daily|weekly-wechat]
  daily         → Telegram 推送新增链接（三源合并，Google 24h 内）
  weekly-wechat → 生成 TestFlight合集_第N期.txt（三源合并，Google 7d 内）
"""

import re, json, os, sys, time
from datetime import datetime
from urllib.request import urlopen, Request

import requests

sys.path.insert(0, os.path.dirname(__file__))

# ========== 配置 ==========
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None
CHANNEL = "@ios_collection_ipa"

SENT_FILE = "sent_codes.json"
TF_WECHAT_SENT = "tf_wechat_sent.json"
TF_ISSUE_FILE = "tf_issue.txt"

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"}

# ========== 源1：global-testflight-link ==========
from scraper import fetch_all_y

# ========== 源2：departures.to ==========
import departures_scraper as deps

# ========== 源3：Google 搜索 ==========
def fetch_from_google(time_range=""):
    """搜索 site:testflight.apple.com/join/ 提取 TF 链接
    time_range: ""=全量, "d"=24小时内, "w"=7天内
    """
    label = {"": "全量", "d": "24小时内", "w": "7天内"}
    print(f"📥 Google 搜索 (site:testflight.apple.com/join/ {label.get(time_range,time_range)})...")
    results = []
    search_url = "https://www.google.com/search"
    params = {"q": "site:testflight.apple.com/join/", "hl": "en", "num": "50"}
    if time_range:
        params["tbs"] = f"qdr:{time_range}"

    try:
        resp = requests.get(search_url, params=params, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"   ⚠️ Google 搜索失败: {e}")
        return results

    # Google 搜索结果的 URL 可能藏在多处（按命中率排序）：
    #   1. data-lpage="https://testflight.apple.com/join/XXX"   ← 最常见（landing page）
    #   2. /url?q=https://testflight.apple.com/join/XXX&sa=...   ← 重定向链接
    #   3. <cite>https://testflight.apple.com/join/XXX</cite>    ← 引用样式
    #   4. 文本里直接出现的完整 URL
    pats = [
        re.compile(r'data-lpage="(https?://testflight\.apple\.com/join/[A-Za-z0-9]+)"'),
        re.compile(r'/url\?q=(https?://testflight\.apple\.com/join/[A-Za-z0-9]+)'),
        re.compile(r'<cite[^>]*>https?://testflight\.apple\.com/join/([A-Za-z0-9]+)'),
        re.compile(r'(https?://testflight\.apple\.com/join/[A-Za-z0-9]+)'),
    ]

    found = set()
    for pat in pats:
        for m in pat.finditer(resp.text):
            # 第一个 group 是 URL（模式 1/2/4）或 code（模式 3）
            if pat.pattern.startswith(r'<cite'):
                code = m.group(1)
            else:
                url = m.group(1)
                cm = re.search(r'/join/([A-Za-z0-9]+)', url)
                code = cm.group(1) if cm else None

            if code and code not in found:
                found.add(code)
                results.append({
                    "name": f"Google #{len(results)+1}",
                    "code": code,
                    "desc": "",
                    "url": f"https://testflight.apple.com/join/{code}",
                })

    print(f"   Google: {len(results)} 个链接")
    return results


# ========== 工具函数 ==========
def tg_send(text):
    if not TG_API: return False
    data = json.dumps({"chat_id": CHANNEL, "text": text}).encode("utf-8")
    req = Request(f"{TG_API}/sendMessage", data=data,
                  headers={"Content-Type": "application/json"})
    try:
        resp = urlopen(req, timeout=15)
        return json.loads(resp.read()).get("ok", False)
    except: return False

def load_set(path):
    if os.path.exists(path):
        with open(path) as f: return set(json.load(f))
    return set()

def save_set(s, path):
    with open(path, 'w') as f: json.dump(sorted(list(s)), f)

def get_issue():
    if os.path.exists(TF_ISSUE_FILE):
        with open(TF_ISSUE_FILE) as f:
            try: return int(f.read().strip())
            except: pass
    return 0

def set_issue(n):
    with open(TF_ISSUE_FILE, 'w') as f: f.write(str(n))


# ========== 合并全部三个源 ==========
def merge_all_sources(google_entries):
    """三源合并：以 scraper 为主，departures 和 Google 补全"""

    # 1. scraper (global-testflight-link)
    print("📥 scraper.py (global-testflight-link)...")
    scraper_entries = fetch_all_y()
    print(f"   scraper: {len(scraper_entries)}")

    # 2. departures.to
    print("📥 departures_scraper (departures.to)...")
    try:
        deps_apps = deps.fetch_home()
        print(f"   departures: {len(deps_apps)}")
    except Exception as e:
        print(f"   ⚠️ departures 抓取失败: {e}")
        deps_apps = []

    # 3. 建立 code → 元数据索引（名字、简介）
    code_meta = {}

    # scraper 的数据
    for name, code in scraper_entries:
        if code not in code_meta:
            code_meta[code] = {"name": name, "desc": "", "tags": []}

    # departures 的数据（需先获取 code）
    deps_codes = 0
    for a in deps_apps:
        code, status = deps.fetch_tf_code(a["id"])
        if code and status == "open":
            if code not in code_meta:
                code_meta[code] = {"name": a["name"], "desc": a.get("desc", ""), "tags": a.get("tags", [])}
            deps_codes += 1
            time.sleep(0.3)
    print(f"   departures codes: {deps_codes}")

    # Google 的数据
    for g in google_entries:
        if g["code"] not in code_meta:
            code_meta[g["code"]] = {"name": g["name"], "desc": "", "tags": []}

    merged = []
    for code, meta in code_meta.items():
        merged.append({
            "name": meta["name"],
            "code": code,
            "desc": meta.get("desc", ""),
            "url": f"https://testflight.apple.com/join/{code}",
        })

    print(f"📊 三源合并后: {len(merged)} 款 (scraper {len(scraper_entries)} + departures {deps_codes} + google {len(google_entries)})")
    return merged


# ========== 主逻辑 ==========
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"
    print(f"🕐 {datetime.now()} 模式: {mode}")

    # 先抓 Google（按模式决定时间范围）
    time_rng = "d" if mode == "daily" else "w"
    google_entries = fetch_from_google(time_rng)

    # 三源合并
    merged = merge_all_sources(google_entries)

    if not merged:
        print("✅ 无链接")
        return

    # ===== 模式：每日 Telegram =====
    if mode == "daily":
        sent = load_set(SENT_FILE)
        new = [e for e in merged if e["code"] not in sent]
        for e in new: sent.add(e["code"])

        if not new:
            print("✅ 无新增")
            save_set(sent, SENT_FILE)
            return

        if len(new) > 100: new = new[:100]
        print(f"🆕 {len(new)} 条新增")

        for start in range(0, len(new), 10):
            batch = new[start:start+10]
            now = datetime.now().strftime("%m/%d")
            lines = [f"🧪 TestFlight 新链接 ({now})", ""]
            for i, e in enumerate(batch, start+1):
                line = f"{i}. {e['name']}"
                if e["desc"]: line += f"\n   {e['desc'][:80]}"
                line += f"\n   {e['url']}"
                lines.append(line)
            msg = "\n".join(lines)
            ok = tg_send(msg)
            print(f"  {'✅' if ok else '❌'} batch {start//10+1}")

        save_set(sent, SENT_FILE)
        print("🏁 完成")
        return

    # ===== 模式：每周 WeChat =====
    if mode == "weekly-wechat":
        if BOT_TOKEN:
            for start in range(0, len(merged), 10):
                batch = merged[start:start+10]
                now = datetime.now().strftime("%m/%d")
                lines = [f"🧪 TestFlight 周报 ({now})", ""]
                for i, e in enumerate(batch, start+1):
                    line = f"{i}. {e['name']}"
                    if e["desc"]: line += f"\n   {e['desc'][:80]}"
                    line += f"\n   {e['url']}"
                    lines.append(line)
                msg = "\n".join(lines)
                ok = tg_send(msg)
                print(f"  {'✅' if ok else '❌'} TG batch {start//10+1}")

        w_sent = load_set(TF_WECHAT_SENT)
        new_tf = [e for e in merged if e["code"] not in w_sent]

        if not new_tf:
            print("✅ 无新的 TestFlight 链接")
            return

        issue = get_issue() + 1
        set_issue(issue)

        filename = f"TestFlight合集_第{issue}期.txt"
        lines = [f"TestFlight合集 第{issue}期", ""]
        for i, e in enumerate(new_tf, 1):
            lines.append(f"{i}. {e['name']}")
            if e["desc"]: lines.append(f"   简介：{e['desc'][:200]}")
            lines.append(f"   https://testflight.apple.com/join/{e['code']}")

        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        for e in new_tf: w_sent.add(e["code"])
        save_set(w_sent, TF_WECHAT_SENT)

        print(f"📝 TXT: {filename} ({len(new_tf)} 款, 第{issue}期)")
        print("🏁 完成")
        return


if __name__ == "__main__":
    main()
