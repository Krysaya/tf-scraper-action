#!/usr/bin/env python3
"""
Telegram 推送器 — 只读数据文件，格式化推 TG
用法: python tg_push.py [daily-free|daily-tf|weekly-tf]
"""

import json, os, sys
from datetime import datetime, timezone, timedelta
BEIJING = timezone(timedelta(hours=8))
from urllib.request import urlopen, Request

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("环境变量 TELEGRAM_BOT_TOKEN 未设置")
CHANNEL = "@ios_collection_ipa"
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

SENT_FREE = "sent_free.json"       # 每日限免已发记录
SENT_TF = "sent_codes.json"        # TF 已发记录

def tg_send(text):
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


# ========== 每日限免推送 ==========
def push_daily_free():
    today = datetime.now(BEIJING).strftime("%m%d")
    filename = f"每日限免{today}.txt"
    if not os.path.exists(filename):
        print(f"❌ 文件不存在: {filename}")
        return

    with open(filename, encoding="utf-8") as f:
        content = f.read()

    sent = load_set(SENT_FREE)
    if filename in sent:
        print(f"✅ 已推送过: {filename}")
        return

    # 推送完整内容，自动分段
    content = content.strip()
    MAX_LEN = 3800
    msg_parts = []
    while len(content) > MAX_LEN:
        split_at = content.rfind("\n", 0, MAX_LEN)
        if split_at == -1: split_at = MAX_LEN
        msg_parts.append(content[:split_at])
        content = content[split_at:].lstrip()
    if content: msg_parts.append(content)
    if not msg_parts: msg_parts = [content]
    ok = True
    for i, part in enumerate(msg_parts):
        tag = f"({i+1}/{len(msg_parts)}) " if len(msg_parts) > 1 else ""
        ok &= tg_send(tag + part)
    print(f"  {'✅' if ok else '❌'} 每日限免 TG 推送")
    if ok:
        sent.add(filename)
        save_set(sent, SENT_FREE)


# ========== 每日 TF 链接推送 ==========
def push_daily_tf():
    today = datetime.now(BEIJING).strftime("%m%d")
    filename = f"tf_daily_links_{today}.json"
    if not os.path.exists(filename):
        print(f"❌ 文件不存在: {filename}")
        return

    with open(filename, encoding="utf-8") as f:
        entries = json.load(f)

    sent = load_set(SENT_TF)
    new_entries = [e for e in entries if e["code"] not in sent]

    if not new_entries:
        # 无新增内容也通知 TG
        now = datetime.now(BEIJING).strftime("%m/%d")
        tg_send(f"🧪 TestFlight 今日无新增链接 ({now})")
        print("✅ TF 无新增链接（已通知 TG）")
        return

    if len(new_entries) > 100:
        print(f"⚠️ 共 {len(new_entries)} 条新链接，超过 100 条上限，截取前 100 条推送")
        print(f"   （剩余 {len(new_entries) - 100} 条下次推送）")
        new_entries = new_entries[:100]

    now = datetime.now(BEIJING).strftime("%m/%d")
    pushed_codes = []

    for start in range(0, len(new_entries), 10):
        batch = new_entries[start:start+10]
        lines = [f"🧪 TestFlight 新链接 ({now})", ""]
        for i, e in enumerate(batch, start+1):
            line = f"{i}. {e['name']}"
            if e.get("desc"): line += f"\n   {e['desc'][:80]}"
            line += f"\n   {e['url']}"
            lines.append(line)
        msg = "\n".join(lines)
        ok = tg_send(msg)
        if ok:
            pushed_codes.extend(e["code"] for e in batch)
            print(f"  ✅ batch {start//10+1}")
        else:
            print(f"  ❌ batch {start//10+1} 推送失败，跳过标记")

    # 只有推送成功的才标记为 sent
    for code in pushed_codes:
        sent.add(code)
    save_set(sent, SENT_TF)
    print(f"🏁 TF 每日推送完成 ({len(pushed_codes)}/{len(new_entries)} 条成功)")


# ========== 每周 TF 链接推送 ==========
def push_weekly_tf():
    filename = "tf_weekly_links.json"
    if not os.path.exists(filename):
        print(f"❌ 文件不存在: {filename}")
        return

    with open(filename, encoding="utf-8") as f:
        entries = json.load(f)

    now = datetime.now(BEIJING).strftime("%m/%d")

    for start in range(0, len(entries), 10):
        batch = entries[start:start+10]
        lines = [f"🧪 TestFlight 周报 ({now})", ""]
        for i, e in enumerate(batch, start+1):
            line = f"{i}. {e['name']}"
            if e.get("desc"): line += f"\n   {e['desc'][:80]}"
            line += f"\n   {e['url']}"
            lines.append(line)
        msg = "\n".join(lines)
        ok = tg_send(msg)
        print(f"  {'✅' if ok else '❌'} batch {start//10+1}")

    print(f"🏁 TF 周报推送完成 ({len(entries)} 条)")


# ========== 主入口 ==========
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily-free"
    print(f"🕐 {datetime.now(BEIJING)} 模式: {mode}")

    if mode == "daily-free":
        push_daily_free()
    elif mode == "daily-tf":
        push_daily_tf()
    elif mode == "weekly-tf":
        push_weekly_tf()
    else:
        print(f"❌ 未知模式: {mode}")
        print("用法: tg_push.py [daily-free|daily-tf|weekly-tf]")


if __name__ == "__main__":
    main()
