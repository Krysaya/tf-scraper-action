#!/usr/bin/env python3
"""
TestFlight 二源抓取器 — 只抓取合并，不推送
用法: python tf_scraper.py [daily|weekly]
  daily  → 输出 tf_daily_links.json（全部去重结果）
  weekly → 输出 tf_weekly_links.json + TestFlight合集_第N期.txt
"""

import re, json, os, sys, time
from datetime import datetime, timezone, timedelta
BEIJING = timezone(timedelta(hours=8))
from urllib.request import urlopen, Request

import requests

sys.path.insert(0, os.path.dirname(__file__))

# ========== 配置 ==========
TF_WECHAT_SENT = "tf_wechat_sent.json"
TF_ISSUE_FILE = "tf_issue.txt"

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"}

# ========== 源1：departures.to ==========
import departures_scraper as deps

# ========== 源2：Brave Search ==========
def fetch_from_brave():
    """从 Brave Search 搜索结果中提取 TF code + 真实 App 名称"""
    print("📥 Brave Search (site:testflight.apple.com/join/)...")
    results = []
    params = {"q": "site:testflight.apple.com/join/", "source": "web"}
    brave_headers = dict(HEADERS)
    brave_headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    brave_headers["Accept-Language"] = "zh-CN,zh;q=0.9,en;q=0.5"

    try:
        resp = requests.get("https://search.brave.com/search", params=params,
                          headers=brave_headers, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"   ⚠️ Brave Search 失败: {e}")
        return results

    # 提取所有 join code + 周围 300 字符上下文，尝试找真实 App 名
    codes_seen = set()
    for m in re.finditer(r'testflight\.apple\.com/join/([A-Za-z0-9]+)', resp.text):
        code = m.group(1)
        if code in codes_seen:
            continue
        codes_seen.add(code)

        # 从 code 位置往前找最近的 <a> 或 <h> 标签内的文字当作 App 名
        ctx = resp.text[max(0, m.start()-600):m.start()]
        # 尝试提取链接文字 / 标题
        name = ""
        for p in [
            r'<a[^>]*class="[^"]*snippet[^"]*"[^>]*>\s*(.+?)\s*</a>',
            r'<span[^>]*class="[^"]*title[^"]*"[^>]*>\s*(.+?)\s*</span>',
            r'class="[^"]*result-title[^"]*"[^>]*>(.+?)</',
            r'>([^<]{3,80})</a>',
        ]:
            # 倒序找最后一个匹配（离 code 最近）
            found = re.findall(p, ctx, re.DOTALL)
            if found:
                raw = found[-1]
                name = re.sub(r'<[^>]+>', '', raw).strip()
                if name and len(name) >= 2 and 'testflight' not in name.lower()[:20]:
                    break
                name = ""

        if not name:
            name = f"TF_{code[:6]}"  # fallback: 用 code 简写

        results.append({"name": name, "code": code, "desc": ""})

    print(f"   Brave: {len(results)} 个链接")
    return results


# ========== 工具 ==========
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


# ========== 二源合并 ==========
def merge_all_sources(brave_entries):
    print("📥 departures.to...")
    try:
        deps_apps = deps.fetch_home()
        print(f"   departures: {len(deps_apps)}")
    except Exception as e:
        print(f"   ⚠️ departures 抓取失败: {e}")
        deps_apps = []

    code_meta = {}
    deps_codes = 0
    for a in deps_apps:
        code, status = deps.fetch_tf_code(a["id"])
        if code and status == "open":
            code_meta[code] = {"name": a["name"], "desc": a.get("desc", ""), "tags": a.get("tags", [])}
            deps_codes += 1
            time.sleep(0.3)

    for g in brave_entries:
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

    print(f"📊 二源合并后: {len(merged)} 款 (departures {deps_codes} + brave {len(brave_entries)})")
    return merged


# ========== 主逻辑 ==========
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"
    print(f"🕐 {datetime.now(BEIJING)} 模式: {mode}")

    brave_entries = fetch_from_brave()
    merged = merge_all_sources(brave_entries)

    if not merged:
        print("✅ 无链接")
        return

    if mode == "daily":
        today = datetime.now(BEIJING).strftime("%m%d")
        filename = f"tf_daily_links_{today}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        print(f"📝 已保存: {filename} ({len(merged)} 款)")
        return

    if mode == "weekly":
        # 保存全部合并结果
        with open("tf_weekly_links.json", "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        print(f"📝 已保存: tf_weekly_links.json ({len(merged)} 款)")

        # 生成 TXT 合集（仅新 code，基于 tf_wechat_sent.json）
        w_sent = load_set(TF_WECHAT_SENT)
        new_tf = [e for e in merged if e["code"] not in w_sent]

        if not new_tf:
            print("✅ 无新的 TF 链接（公众号）")
            return

        issue = get_issue() + 1
        set_issue(issue)

        filename = f"TestFlight合集_第{issue}期.txt"
        lines = [f"TestFlight合集 第{issue}期", ""]
        for i, e in enumerate(new_tf, 1):
            lines.append(f"{i}. {e['name']}")
            if e["desc"]: lines.append(f"   简介：{e['desc'][:200]}")
            lines.append(f"   {e['url']}")

        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        for e in new_tf: w_sent.add(e["code"])
        save_set(w_sent, TF_WECHAT_SENT)

        print(f"📝 TXT: {filename} ({len(new_tf)} 款, 第{issue}期)")
        return


if __name__ == "__main__":
    main()
