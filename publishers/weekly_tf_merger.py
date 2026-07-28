#!/usr/bin/env python3
"""
每周 TF 合集聚合器 — 从最近 7 天的 daily JSON 合并去重
替代 tf_scraper.py weekly 的单次抓取模式

用法: python weekly_tf_merger.py
产出: TestFlight合集_第N期.txt
"""

import json
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

BEIJING = timezone(timedelta(hours=8))

WORK_DIR = Path(__file__).resolve().parent.parent
TF_WECHAT_SENT = WORK_DIR / "tf_wechat_sent.json"
TF_ISSUE_FILE = WORK_DIR / "tf_issue.txt"
WEEKLY_LINKS = WORK_DIR / "tf_weekly_links.json"


# ============================================================
# TestFlight 页面抓取（获取真实 App 名称 + 验证链接是否有效）
# ============================================================
def fetch_tf_page_info(code):
    """
    访问 testflight.apple.com/join/{code}，获取真实 App 名称和链接状态

    返回: (app_name, is_active)
      app_name: str — 真实名称；失败返回 None
      is_active: bool — 链接是否仍然可用
    """
    url = f"https://testflight.apple.com/join/{code}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            # 检查是否被重定向（重定向通常意味着链接失效）
            final_url = resp.geturl()
            if final_url != url and "join" not in final_url:
                return None, False

            html = resp.read().decode("utf-8", errors="ignore")

            # 检测失效标志
            if any(kw in html for kw in [
                "isn't accepting",
                "no longer available",
                "has been removed",
                "This beta is full",
                "doesn't exist",
            ]):
                return None, False

            # 提取 App 名称（按优先级尝试多种模式）
            name = None
            patterns = [
                # meta og:title: "Join the <name> beta"
                r'<meta[^>]+property="og:title"[^>]+content="Join the (.+?) beta',
                r'<meta[^>]+content="Join the (.+?) beta[^"]*"[^>]+property="og:title"',
                # title: "Join the <name> beta — TestFlight — Apple"
                r'<title>Join the (.+?) beta',
                # h1/h2 with app name class
                r'class="[^"]*app-name[^"]*"[^>]*>([^<]+)',
                # beta name in text
                r'<span[^>]*class="[^"]*beta-name[^"]*"[^>]*>([^<]+)',
                # fallback: any h1
                r'<h1[^>]*>([^<]+)</h1>',
            ]
            for pattern in patterns:
                m = re.search(pattern, html)
                if m:
                    name = m.group(1).strip()
                    if name and len(name) >= 2 and "TestFlight" not in name:
                        break
                    name = None

            return name, True

    except urllib.error.HTTPError as e:
        # 404/403/500 → 链接失效
        return None, False
    except Exception:
        # 网络错误 → 状态未知
        return None, None


def enrich_and_validate(apps, skip_existing_names=True):
    """
    对 App 列表进行名称补全和链接验证

    skip_existing_names: True = 只补全占位名（TF_XXXX），跳过已有真名的
    """
    enriched = []
    expired = []
    skipped = 0

    for entry in apps:
        name = entry.get("name", "")
        code = entry.get("code", "")

        # 是否需要补全名称？
        needs_name = not name or name.startswith("TF_") or len(name) <= 8
        if skip_existing_names and not needs_name:
            enriched.append(entry)
            skipped += 1
            continue

        print(f"  🔍 {code[:8]}...", end=" ")
        real_name, is_active = fetch_tf_page_info(code)

        if is_active is False:
            print("❌ 已失效")
            expired.append(code)
            continue

        if real_name:
            entry["name"] = real_name
            print(f"→ {real_name[:30]}")
        else:
            print(f"→ (名称获取失败)")

        enriched.append(entry)
        time.sleep(0.5)  # 避免请求过快被苹果限流

    if skipped:
        print(f"  ⏭️ 跳过 {skipped} 个已有真名")
    if expired:
        print(f"  ❌ 过滤 {len(expired)} 个失效链接")
    return enriched, expired


def load_json(path):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_json(data, path):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_issue():
    if TF_ISSUE_FILE.exists():
        try:
            return int(TF_ISSUE_FILE.read_text().strip())
        except Exception:
            pass
    return 0


def set_issue(n):
    TF_ISSUE_FILE.write_text(str(n))


def get_daily_filenames():
    """返回最近 7 天的 daily JSON 文件名列表"""
    today = datetime.now(BEIJING).date()
    files = []
    for i in range(7):
        d = today - timedelta(days=i)
        fname = f"tf_daily_links_{d.strftime('%m%d')}.json"
        files.append((fname, d.strftime("%m/%d")))
    return files


def merge_daily():
    """聚合 7 天 daily JSON，按 code 去重"""
    code_map = {}  # code → entry

    daily_files = get_daily_filenames()
    found_any = False

    for fname, date_str in daily_files:
        fpath = WORK_DIR / fname
        if not fpath.exists():
            continue
        entries = load_json(fpath)
        for entry in entries:
            code = entry.get("code", "")
            if not code:
                continue
            if code not in code_map:
                code_map[code] = entry
            else:
                # 保留有简介的版本
                if entry.get("desc") and not code_map[code].get("desc"):
                    code_map[code] = entry
        print(f"  {date_str} {fname}: {len(entries)} 条")
        found_any = True

    if not found_any:
        print("❌ 没找到任何 daily TF 文件")
        return []

    merged = list(code_map.values())
    print(f"\n📊 7 天合并: {len(merged)} 条（去重后）")
    return merged


def generate_weekly_txt(new_apps, sent_codes):
    """生成 TestFlight合集_第N期.txt（仅新 code）"""
    new_tf = [a for a in new_apps if a["code"] not in sent_codes]
    if not new_tf:
        return None

    issue = get_issue() + 1
    set_issue(issue)

    fname = f"TestFlight合集_第{issue}期.txt"
    lines = [f"TestFlight合集 第{issue}期", ""]
    for i, entry in enumerate(new_tf, 1):
        lines.append(f"{i}. {entry['name']}")
        if entry.get("desc"):
            lines.append(f"   简介：{entry['desc'][:200]}")
        lines.append(f"   {entry['url']}")

    (WORK_DIR / fname).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return fname, issue, new_tf


def main():
    print(f"🕐 {datetime.now(BEIJING)}")
    print("=" * 50)
    print("  🧪 每周 TF 合集聚合（7天 daily 数据）")
    print("=" * 50)

    # 1. 聚合 7 天 daily 数据
    merged = merge_daily()
    if not merged:
        print("✅ 无数据")
        return

    # 2. 补全名称 + 过滤失效链接
    print(f"\n🔍 验证链接并补全名称 ...")
    merged, expired = enrich_and_validate(merged)
    if not merged:
        print("✅ 所有链接均已失效，无需生成")
        return

    # 3. 保存全部合并结果
    save_json(merged, WEEKLY_LINKS)
    print(f"📝 已保存: {WEEKLY_LINKS.name} ({len(merged)} 条)")

    # 3. 加载已发记录
    sent_codes = set(load_json(TF_WECHAT_SENT))

    # 4. 生成新一期合集 TXT
    result = generate_weekly_txt(merged, sent_codes)
    if result:
        fname, issue, new_tf = result
        print(f"📝 TXT: {fname} ({len(new_tf)} 款新, 第{issue}期)")

        # 更新已发记录
        for e in new_tf:
            sent_codes.add(e["code"])
        save_json(sorted(sent_codes), TF_WECHAT_SENT)
        print(f"📝 已更新已发记录: {len(sent_codes)} 条")
    else:
        print("✅ 无新的 TF 链接")


if __name__ == "__main__":
    main()
