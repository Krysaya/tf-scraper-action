#!/usr/bin/env python3
"""
每周 TF 合集聚合器 — 从最近 7 天的 daily JSON 合并去重
替代 tf_scraper.py weekly 的单次抓取模式

用法: python weekly_tf_merger.py
产出: TestFlight合集_第N期.txt
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

BEIJING = timezone(timedelta(hours=8))

WORK_DIR = Path(__file__).resolve().parent.parent
TF_WECHAT_SENT = WORK_DIR / "tf_wechat_sent.json"
TF_ISSUE_FILE = WORK_DIR / "tf_issue.txt"
WEEKLY_LINKS = WORK_DIR / "tf_weekly_links.json"


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

    # 2. 保存全部合并结果
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
