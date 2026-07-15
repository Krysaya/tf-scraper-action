#!/usr/bin/env python3
"""
每日限免合并器 — mergeek + oodata → 每日限免MMDD.txt
只产出数据文件，不推送（推送由 tg_push.py / 公众号守护进程处理）
"""
import sys, os, json, time
from datetime import datetime
from pathlib import Path

import mergeek_scraper
import oodata_scraper


def merge_all():
    """合并两个数据源，按 App ID 去重"""
    print(f"🕐 {datetime.now()} 合并 mergeek + oodata")

    # 1. mergeek（先查 App ID）
    print("📥 mergeek...")
    mergeek_apps = mergeek_scraper.fetch_apps()
    print(f"   mergeek: {len(mergeek_apps)} 条")
    # mergeek 没有 App ID，用 Apple Search API 查
    mergeek_with_id = []
    for a in mergeek_apps:
        if a.get("name"):
            app_id = mergeek_scraper.search_app_id(a["name"])
            if app_id:
                url = mergeek_scraper.resolve_url(app_id)
                mergeek_with_id.append({
                    "name": a["name"],
                    "price": f"¥{a['price']}" if a.get("price") else "?",
                    "category": a.get("category", ""),
                    "url": url,
                    "app_id": app_id,
                    "source": "mergeek",
                })
        time.sleep(0.3)  # 限速
    print(f"   mergeek → 已查 App ID: {len(mergeek_with_id)} 条")

    # 2. oodata
    print("📥 oodata...")
    oodata_apps = oodata_scraper.fetch_apps()
    print(f"   oodata: {len(oodata_apps)} 条")
    oodata_with_url = []
    for a in oodata_apps:
        if a.get("app_id"):
            url = oodata_scraper.resolve_appstore_url(a["app_id"], a.get("country", ""))
            oodata_with_url.append({
                "name": a["name"],
                "price": "?",
                "category": a.get("tag", "").lstrip("#"),
                "url": url,
                "app_id": a["app_id"],
                "source": "oodata",
            })
    print(f"   oodata → 已解析 URL: {len(oodata_with_url)} 条")

    # 3. 合并去重（按 App ID）
    by_id = {}
    for a in mergeek_with_id + oodata_with_url:
        if a["app_id"] not in by_id:
            by_id[a["app_id"]] = a
        else:
            # 优先保留有原价的
            if a.get("price", "?") != "?" and by_id[a["app_id"]].get("price", "?") == "?":
                by_id[a["app_id"]] = a

    apps = list(by_id.values())
    print(f"📊 合并后: {len(apps)} 款 (mergeek {len(mergeek_with_id)} + oodata {len(oodata_with_url)})")
    return apps


def write_txt(apps, filepath):
    """写入 TXT 文件"""
    today = datetime.now().strftime("%m/%d")
    lines = [f"今日限免 ({today})", ""]
    for i, a in enumerate(apps, 1):
        lines.append(f"{i}. {a['name']}")
        price_part = f"原价 {a['price']} → 免费"
        if a.get("category"):
            price_part += f" | {a['category']}"
        lines.append(f"   {price_part}")
        lines.append(f"   {a['url']}")
    filepath.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    today = datetime.now().strftime("%m%d")
    out = Path(f"每日限免{today}.txt")

    apps = merge_all()
    if not apps:
        print("✅ 今日无新限免")
        return

    write_txt(apps, out)
    print(f"📝 已生成: {out.name} ({len(apps)} 款)")


if __name__ == "__main__":
    main()
