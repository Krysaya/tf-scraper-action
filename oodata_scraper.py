# 📱 oodata.net 今日限免抓取器
# 每天抓取 https://apps.oodata.net/ 的限免应用列表，推送到 Telegram 频道

import re, json, os
from datetime import datetime
from urllib.request import urlopen, Request

# ========== 配置 ==========
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("环境变量 TELEGRAM_BOT_TOKEN 未设置")
CHANNEL = "@ios_collection_ipa"
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

SITE = "https://apps.oodata.net"
SENT_FILE = "oodata_sent.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; oodata-bot/1.0)"}

def fetch_apps():
    """抓取 oodata.net 今日限免应用列表"""
    req = Request(SITE, headers=HEADERS)
    html = urlopen(req, timeout=30).read().decode('utf-8')

    results = []
    # 按 <header 切分，每段对应一个帖子
    sections = html.split('<header class="')

    for sec in sections:
        # 提取帖子 ID
        pid_match = re.search(r'/posts/(\d+)', sec)
        if not pid_match:
            continue
        post_id = pid_match.group(1)

        # 提取 content div 内容
        content_match = re.search(
            r'<div\s+class="[^"]*content[^"]*">(.*?)</div>',
            sec, re.DOTALL
        )
        if not content_match:
            continue
        content = content_match.group(1)

        # 跳过图片帖、非应用内容（content 以 < 开头说明没有直接文本）
        content_stripped = content.strip()
        if content_stripped.startswith('<'):
            continue

        # 提取应用名称（content 开头的纯文本，到 <br> 为止）
        name_match = re.search(r'^\s*([^<]+)', content)
        if not name_match:
            continue
        name = name_match.group(1).strip()

        # 跳过站点头部、互推广告
        if 'Limited-Time Free' in name or 'oodata' in name.lower():
            continue
        # 跳过纯互推内容
        if '【' in name and '】' in name and 'apps.apple.com' not in content:
            continue

        # 提取 App Store ID 和国家代码（兼容 /app/id /cn/app/id /us/app/id）
        app_id = ""
        country = ""
        app_match = re.search(r'apps\.apple\.com/(?:([a-z]{2})/)?app/id(\d+)', content)
        if app_match:
            country = app_match.group(1) or ""
            app_id = app_match.group(2)

        # 无 App Store 链接 → 跳过（Epic 游戏、Telegram 链接等）
        if not app_id:
            continue

        # 提取中文描述（第一个 <br> 之后到下一个 <br> 的文本）
        desc = ""
        parts = re.split(r'<br[^>]*>', content, maxsplit=3)
        if len(parts) >= 2:
            desc_raw = parts[1].strip()
            desc = re.sub(r'<[^>]+>', '', desc_raw).strip()
            desc = re.sub(r'\s*#.*', '', desc).strip()

        # 提取标签 — 匹配 >#XXX</a> 避免捕获 title 属性
        tag = ""
        tag_match = re.search(r'>#([^<]+)</a>', content)
        if tag_match:
            tag = "#" + tag_match.group(1).strip()

        results.append({
            'post_id': post_id,
            'name': name,
            'desc': desc,
            'tag': tag,
            'app_id': app_id,
            'country': country,
        })

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
    print(f"🕐 {datetime.now()} 抓取 oodata 限免...")
    apps = fetch_apps()
    print(f"📊 共解析 {len(apps)} 个应用")

    sent = load_sent()
    new_apps = [a for a in apps if a['post_id'] not in sent]
    for a in new_apps:
        sent.add(a['post_id'])

    if not new_apps:
        print("✅ 没有新增应用")
        save_sent(sent)
        return

    print(f"🆕 {len(new_apps)} 个新应用")

    for start in range(0, len(new_apps), 10):
        batch = new_apps[start:start+10]
        now = datetime.now().strftime('%m/%d')
        lines = [f"📱 今日限免 ({now})", ""]
        for i, a in enumerate(batch, start+1):
            lines.append(f"{i}. {a['name']}")
            desc_tag = a['desc']
            if a['tag']:
                desc_tag += f" | {a['tag']}"
            lines.append(f"   {desc_tag}")
            lines.append(f"   https://apps.apple.com/{a['country'] + '/' if a['country'] else ''}app/id{a['app_id']}")
        msg = "\n".join(lines)
        ok = tg_send(msg)
        print(f"  {'✅' if ok else '❌'} batch {start//10+1}")

    save_sent(sent)
    print("🏁 完成")

if __name__ == "__main__":
    main()
