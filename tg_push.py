#!/usr/bin/env python3
"""
Telegram 推送器 — 只读数据文件，格式化推 TG
用法: python tg_push.py [daily-free|daily-tf|weekly-tf]
"""

import json, os, sys
from datetime import datetime
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
    today = datetime.now().strftime("%m%d")
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

    lines = content.strip().split("\n")
    # 只取前 15 行 + 摘要
    msg = "\n".join(lines[:15])
    if len(lines) > 15:
        msg += f"\n… 共 {len(lines)} 行，完整列表见公众号"
    msg += "\n\n📱 关注公众号获取完整内容"

    ok = tg_send(msg)
    print(f"  {'✅' if ok else '❌'} 每日限免 TG 推送")
    if ok:
        sent.add(filename)
        save_set(sent, SENT_FREE)


# ========== 每日 TF 链接推送 ==========
def push_daily_tf():
    filename = "tf_daily_links.json"
    if not os.path.exists(filename):
        print(f"❌ 文件不存在: {filename}")
        return

    with open(filename, encoding="utf-8") as f:
        entries = json.load(f)

    sent = load_set(SENT_TF)
    new_entries = [e for e in entries if e["code"] not in sent]

    if not new_entries:
        print("✅ TF 无新增链接")
        return

    if len(new_entries) > 100:
        new_entries = new_entries[:100]

    for e in new_entries:
        sent.add(e["code"])

    now = datetime.now().strftime("%m/%d")

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
        print(f"  {'✅' if ok else '❌'} batch {start//10+1}")

    save_set(sent, SENT_TF)
    print(f"🏁 TF 每日推送完成 ({len(new_entries)} 条)")


# ========== 每周 TF 链接推送 ==========
def push_weekly_tf():
    filename = "tf_weekly_links.json"
    if not os.path.exists(filename):
        print(f"❌ 文件不存在: {filename}")
        return

    with open(filename, encoding="utf-8") as f:
        entries = json.load(f)

    now = datetime.now().strftime("%m/%d")

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
    print(f"🕐 {datetime.now()} 模式: {mode}")

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
