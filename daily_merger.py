#!/usr/bin/env python3
"""
每日限免合并器 — mergeek + oodata → 每日限免MMDD.txt
只产出数据文件，不推送（推送由 tg_push.py / 公众号守护进程处理）

修正说明（2026-09-07）：
  - 抓取后实时核价：对每款 App 查 iTunes 中区(cn) + 美区(us) 当前价格，
    两区均收费或无法核实(无 app_id) 的直接排除（"收费的不入"）。
  - 中区免费 → 正文主列表；仅美区免费 → 单列「外区限免」一节（需切区下载）。
  - TXT 携带双区价格行：中区:<状态>:<原价> | 美区:<状态>:<原价>
    状态 ∈ {免费, 付费, 未知}；原价形如 ¥68 / $4.99 / ?
  - 主列表(中区免费) App 若中区原价为 '?'（已核实免费但无原价可展示），
    视为「价格不明确」直接剔除；外区限免 App 若美区原价也为 '?' 同样剔除。
"""
import sys, os, json, time, re
from datetime import datetime, timezone, timedelta
BEIJING = timezone(timedelta(hours=8))
from pathlib import Path
from urllib.request import urlopen, Request

import mergeek_scraper
import oodata_scraper

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
ITUNES_LOOKUP = "https://itunes.apple.com/lookup?id={}&country={}"


# ============================================================
# 实时核价（req3：抓取后必须先核实价格是否限免）
# ============================================================
def itunes_price(app_id, country):
    """返回该区当前价格(float)。resultCount=0 或异常 → None。0.0 表示免费。"""
    try:
        url = ITUNES_LOOKUP.format(app_id, country)
        req = Request(url, headers=UA)
        resp = urlopen(req, timeout=8)
        d = json.loads(resp.read())
        if d.get("resultCount", 0) > 0:
            return d["results"][0].get("price")
    except Exception:
        pass
    return None


def verify_region(app):
    """核价中区+美区，返回带 region 字段的 dict；无法核实/两区均收费返回 None。

    返回字段: name, category, price(mergeek原价或?), url, app_id, section,
              cn_status, cn_orig, us_status, us_orig
    """
    app_id = app.get("app_id")
    if not app_id:
        return None  # 无 app_id → 无法核实 → 排除

    cn_price = itunes_price(app_id, "cn")
    us_price = itunes_price(app_id, "us")
    time.sleep(0.3)  # 限速，别打爆 iTunes

    cn_free = (cn_price == 0.0)
    us_free = (us_price == 0.0)
    if not (cn_free or us_free):
        return None  # 两区都收费 → 排除

    mergeek_price = app.get("price")  # "¥68" 或 "?"
    # 原价展示：优先用 mergeek 页面原价；否则用 iTunes 当前价(>0)
    cn_orig = mergeek_price if (mergeek_price and mergeek_price != "?") \
        else (f"¥{cn_price}" if (cn_price and cn_price > 0) else "?")
    us_orig = f"${us_price}" if (us_price and us_price > 0) else "?"

    cn_status = "免费" if cn_free else ("付费" if cn_price is not None else "未知")
    us_status = "免费" if us_free else ("付费" if us_price is not None else "未知")

    if cn_free:
        section = "main"
        url = app["url"]
    else:
        # 仅美区免费：改用美区 URL，扫码跳到免费页
        section = "external"
        url = f"https://apps.apple.com/us/app/id{app_id}"

    return {
        "name": app["name"],
        "category": app.get("category", ""),
        "price": mergeek_price or "?",
        "url": url,
        "app_id": app_id,
        "section": section,
        "cn_status": cn_status, "cn_orig": cn_orig,
        "us_status": us_status, "us_orig": us_orig,
    }


def merge_all():
    """合并两个数据源，按 App ID 去重"""
    print(f"🕐 {datetime.now(BEIJING)} 合并 mergeek + oodata")

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


def price_clear(a):
    """价格是否明确（主列表 + 外区节统一过滤）。

    主列表(中区免费) App：中区原价已知(非 '?') 才算价格明确；
    外区限免(App 仅美区免费) App：美区原价已知(非 '?') 才算价格明确。
    原价 '?' 表示已核实免费但无法给出折扣幅度 → 视为「价格不明确」剔除。
    注：外区 App 美区现价即 0，iTunes 查不到原价，故目前外区节恒为空；
       若未来能拿到美区原价则可正常展示。
    """
    if a.get("section") == "external":
        return a.get("us_orig", "?") != "?"
    return a.get("cn_orig", "?") != "?"


def _region_line(a):
    line = f"   中区:{a['cn_status']}:{a['cn_orig']} | 美区:{a['us_status']}:{a['us_orig']}"
    if a.get("category"):
        line += f" | {a['category']}"
    return line


def _write_block(a, idx, lines):
    lines.append(f"{idx}. {a['name']}")
    lines.append(_region_line(a))
    lines.append(f"   {a['url']}")


def write_txt(main_apps, external_apps, filepath):
    """写入 TXT：正文(中区免费) + 可选「外区限免」节(仅美区免费)"""
    today = datetime.now(BEIJING).strftime("%m/%d")
    lines = [f"今日限免 ({today})", ""]

    for i, a in enumerate(main_apps, 1):
        _write_block(a, i, lines)

    if external_apps:
        lines.append("")
        lines.append("【外区限免 · 需切换 Apple ID 地区后下载】")
        for i, a in enumerate(external_apps, 1):
            _write_block(a, i, lines)

    filepath.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_yesterday_ids():
    """加载昨天的 TXT，提取已出现的 App ID（用于跨天去重）"""
    yesterday = (datetime.now(BEIJING) - timedelta(days=1)).strftime("%m%d")
    y_file = Path(f"每日限免{yesterday}.txt")
    if not y_file.exists():
        return set()
    text = y_file.read_text(encoding="utf-8")
    ids = set(re.findall(r'apps\.apple\.com/\S*?/id(\d+)', text))
    print(f"📋 昨日 {yesterday}: {len(ids)} 款 → 跨天去重")
    return ids


def main():
    today = datetime.now(BEIJING).strftime("%m%d")
    out = Path(f"每日限免{today}.txt")

    apps = merge_all()
    if not apps:
        print("✅ 今日无新限免")
        return

    # ── 实时核价 + 过滤（req3）──
    verified = []
    excluded = 0
    for a in apps:
        v = verify_region(a)
        if v:
            verified.append(v)
        else:
            excluded += 1
    print(f"🔍 核价: {len(verified)} 款有效(中区或美区免费), 排除 {excluded} 款(两区均收费/无法核实)")
    # ── 过滤价格不明确（主列表中区原价 ?）──
    clear_apps = [a for a in verified if price_clear(a)]
    unclear = len(verified) - len(clear_apps)
    if unclear:
        print(f"💲 价格不明(中区原价?): 去掉 {unclear} 款")
    verified = clear_apps
    if not verified:
        print("✅ 今日无可核实的限免")
        return

    # 跨天去重：去掉昨天已经出现过的 App
    yesterday_ids = load_yesterday_ids()
    if yesterday_ids:
        before = len(verified)
        verified = [a for a in verified if str(a["app_id"]) not in yesterday_ids]
        removed = before - len(verified)
        if removed:
            print(f"🔁 跨天去重: 去掉 {removed} 款昨日已出现")

    if not verified:
        print("✅ 今日无新增限免（全部昨日已出现）")
        return

    # 拆分双区
    main_apps = [a for a in verified if a["section"] == "main"]
    external_apps = [a for a in verified if a["section"] == "external"]
    print(f"📊 中区免费 {len(main_apps)} 款 | 仅美区免费 {len(external_apps)} 款")

    write_txt(main_apps, external_apps, out)
    print(f"📝 已生成: {out.name} (中区 {len(main_apps)} + 外区 {len(external_apps)})")


if __name__ == "__main__":
    main()
