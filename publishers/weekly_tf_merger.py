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

# ========== 翻译：简介中文化（兜底 daily 未翻成功的条目）==========
import sys as _sys
_sys.path.insert(0, str(WORK_DIR))
try:
    import tf_translate
except Exception as _e:
    tf_translate = None
    print(f"⚠️ 翻译模块 tf_translate 未加载: {_e}")
TF_WECHAT_SENT = WORK_DIR / "tf_wechat_sent.json"
TF_ISSUE_FILE = WORK_DIR / "tf_issue.txt"
WEEKLY_LINKS = WORK_DIR / "tf_weekly_links.json"

# 去重滚动窗口：只记住最近 N 期已发的 code，更早的链接可重新入集
# （避免永久去重导致合集变空 / SCF 空推）
SENT_WINDOW_ISSUES = 4


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
        elif needs_name:
            # 页面活跃但无法获取名称 → 大概率无效链接，过滤掉
            print("❌ 无法获取名称，视为无效")
            expired.append(code)
            continue
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


def load_sent_by_issue():
    """读取已发记录，兼容旧格式（纯 code 列表）。

    返回 {'by_issue': {issue_str: [codes]}, 'window': N}
    """
    if TF_WECHAT_SENT.exists():
        try:
            data = json.loads(TF_WECHAT_SENT.read_text(encoding="utf-8"))
        except Exception:
            data = []
        if isinstance(data, list):
            # 旧格式：整体视为历史合集（issue 0），首次运行后会被窗口淘汰
            return {"by_issue": {"0": data}, "window": SENT_WINDOW_ISSUES}
        if isinstance(data, dict):
            data.setdefault("window", SENT_WINDOW_ISSUES)
            data.setdefault("by_issue", {})
            return data
    return {"by_issue": {}, "window": SENT_WINDOW_ISSUES}


def active_sent_codes(sent, current_issue):
    """窗口内（最近 window 期）的 code 集合"""
    window = sent.get("window", SENT_WINDOW_ISSUES)
    cutoff = current_issue - window + 1
    codes = set()
    for iss, cs in sent.get("by_issue", {}).items():
        try:
            iss_n = int(iss)
        except Exception:
            iss_n = 0
        if iss_n >= cutoff:
            codes.update(cs)
    return codes


def generate_weekly_txt(new_apps, sent, next_issue):
    """生成 TestFlight合集_第N期.txt。

    - 仅保留窗口内未发过的新 code（滚动去重，避免永久去重）
    - 若新链接为空，兜底发布全量（仍有效）链接，保证合集不为空，避免 SCF 空推
    返回 (fname, issue, used_apps, is_fallback) 或 None（merged 本身为空时）
    """
    act = active_sent_codes(sent, next_issue)
    new_tf = [a for a in new_apps if a["code"] not in act]

    used_apps = new_tf
    is_fallback = False
    if not used_apps:
        # B: 兜底发全量（仍有效的全部合并结果），避免空推
        is_fallback = True
        used_apps = list(new_apps)
        print("⚠️ 滚动窗口内无新链接，兜底发布全量（仍有效）链接，避免本期为空")

    if not used_apps:
        return None

    fname = f"TestFlight合集_第{next_issue}期.txt"
    lines = [f"TestFlight合集 第{next_issue}期", ""]
    if is_fallback:
        lines.append("（本期含往期仍有效链接）")
        lines.append("")
    for i, entry in enumerate(used_apps, 1):
        title = entry.get("name_cn") or entry.get("name") or ""
        lines.append(f"{i}. {title}")
        if entry.get("desc"):
            clean_desc = entry["desc"].replace("\n", " ").replace("\r", " ")[:200]
            lines.append(f"   简介：{clean_desc}")
        lines.append(f"   {entry['url']}")

    (WORK_DIR / fname).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return fname, next_issue, used_apps, is_fallback


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

    # 1.5 简介 + 标题中文化（兜底：daily 阶段没翻成功的，这里再翻一次）
    #      简介缓存 descriptions.json；标题缓存 tf_titles_cn.json
    if tf_translate is not None:
        try:
            tf_translate.translate_entries(
                merged,
                cache_path=str(WORK_DIR / "descriptions.json"),
                title_cache_path=str(WORK_DIR / "tf_titles_cn.json"),
            )
        except Exception as _e:
            print(f"⚠️ 翻译步骤出错，跳过: {_e}")

    # 2. 补全名称 + 过滤失效链接
    print(f"\n🔍 验证链接并补全名称 ...")
    merged, expired = enrich_and_validate(merged)
    if not merged:
        print("✅ 所有链接均已失效，无需生成")
        return

    # 3. 保存全部合并结果
    save_json(merged, WEEKLY_LINKS)
    print(f"📝 已保存: {WEEKLY_LINKS.name} ({len(merged)} 条)")

    # 3. 加载已发记录（按期存储，支持滚动窗口）
    sent = load_sent_by_issue()
    next_issue = get_issue() + 1

    # 4. 生成新一期合集 TXT（滚动去重 + 兜底全量）
    result = generate_weekly_txt(merged, sent, next_issue)
    if result:
        fname, issue, used_apps, is_fallback = result
        print(f"📝 TXT: {fname} ({len(used_apps)} 款, 第{issue}期"
              f"{' [兜底全量]' if is_fallback else ''})")

        # 记录本期 code，并按窗口淘汰过期期
        sent.setdefault("by_issue", {})[str(issue)] = [e["code"] for e in used_apps]
        window = sent.get("window", SENT_WINDOW_ISSUES)
        cutoff = issue - window + 1
        for iss in list(sent["by_issue"].keys()):
            try:
                if int(iss) < cutoff:
                    del sent["by_issue"][iss]
            except Exception:
                pass
        save_json(sent, TF_WECHAT_SENT)
        set_issue(issue)
        print(f"📝 已更新已发记录 (窗口内 {len(sent['by_issue'])} 期)")
    else:
        print("✅ 合并结果为空，无 TF 链接")


if __name__ == "__main__":
    main()
