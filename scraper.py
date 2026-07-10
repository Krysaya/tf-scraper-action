# 🤖 TestFlight 链接自动抓取器（GitHub Actions 版）

import re, json, os
from datetime import datetime
from urllib.request import urlopen, Request

# ========== 配置 ==========
BOT_TOKEN = "8878668814:AAF4XnjgHE9eS201jnVPYOcrXL_6F2mUoik"
CHANNEL = "@ios_collection_ipa"
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

BASE = "https://raw.githubusercontent.com/fmz200/global-testflight-link/main"
PAGES = ["README.md"] + [f"readme/table{i}.md" for i in range(2, 35)]

SENT_FILE = "sent_codes.json"  # 已发送过的 join 代码

# HTML 行匹配: <td>logo</td> <td>名称</td> <td><a ...join/CODE>...</td> <td>状态</td>
ROW_PAT = re.compile(
    r'<td[^>]*>(.*?)</td>\s*'
    r'<td[^>]*>(.*?)</td>\s*'
    r'<td[^>]*>.*?join/([A-Za-z0-9]+).*?</td>\s*'
    r'<td[^>]*>([YFND])</td>',
    re.DOTALL | re.IGNORECASE
)

def fetch_all_y():
    results = []
    for pn, page in enumerate(PAGES, 1):
        url = f"{BASE}/{page}"
        try:
            html = urlopen(url, timeout=90).read().decode('utf-8')
        except Exception as e:
            print(f"  Page {pn}: SKIP ({e})")
            continue
        pc = 0
        for block in html.split('</tr>'):
            m = ROW_PAT.search(block)
            if m:
                _, name, code, status = m.groups()
                if status.strip() == 'Y':
                    results.append((name.strip(), code.strip()))
                    pc += 1
        print(f"  Page {pn}/34: {pc} Y")
    return results

def load_sent():
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE, 'r') as f:
            return set(json.load(f))
    return set()

def save_sent(s):
    with open(SENT_FILE, 'w') as f:
        json.dump(sorted(list(s)), f)

def tg_send(text):
    data = json.dumps({"chat_id": CHANNEL, "text": text}).encode('utf-8')
    req = Request(f"{TG_API}/sendMessage", data=data,
                  headers={"Content-Type": "application/json"})
    try:
        resp = urlopen(req, timeout=15)
        return json.loads(resp.read()).get("ok", False)
    except:
        return False

def main():
    print(f"🕐 {datetime.now()} 开始抓取...")
    entries = fetch_all_y()
    print(f"📊 共 {len(entries)} Y")

    sent = load_sent()
    new_entries = [(n, c) for n, c in entries if c not in sent]
    for _, c in new_entries:
        sent.add(c)

    if not new_entries:
        print("✅ 没有新增，跳过发送")
        save_sent(sent)
        return

    print(f"🆕 {len(new_entries)} 条新增")
    for start in range(0, len(new_entries), 10):
        batch = new_entries[start:start+10]
        now = datetime.now().strftime('%m/%d')
        lines = [f"🧪 TestFlight 新链接 ({now})", ""]
        for i, (name, code) in enumerate(batch, start+1):
            lines.append(f"{i}. {name}")
            lines.append(f"   https://testflight.apple.com/join/{code}")
        msg = "\n".join(lines)
        ok = tg_send(msg)
        print(f"  {'✅' if ok else '❌'} batch {start//10+1}")

    save_sent(sent)
    print("🏁 完成")

if __name__ == "__main__":
    main()
