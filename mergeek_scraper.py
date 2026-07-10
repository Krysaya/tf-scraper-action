# 📱 mergeek.com 限免抓取器
# 抓取 FREE 应用（含原价）+ ★免费应用（长期免费），跳过冰点特价
# 用 Apple Search API 查找 App ID，优先国区链接

import re, json, os, time
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.parse import quote

# ========== 配置 ==========
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("环境变量 TELEGRAM_BOT_TOKEN 未设置")
CHANNEL = "@ios_collection_ipa"
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

SITE = "https://mergeek.com/free/apps"
SENT_FILE = "mergeek_sent.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# ========== Apple Search API ==========
def search_app_id(name):
    """用 Apple Search API 查找 App Store ID"""
    try:
        url = f"https://itunes.apple.com/search?term={quote(name)}&country=cn&entity=software&limit=3"
        req = Request(url, headers=HEADERS)
        resp = urlopen(req, timeout=10)
        data = json.loads(resp.read())
        if data["resultCount"] > 0:
            # 取第一个匹配的
            return data["results"][0]["trackId"]
    except Exception:
        pass
    return None

# ========== CN App Store 验证 ==========
def resolve_url(app_id):
    """优先国区，失败回退通用链接"""
    cn_url = f"https://apps.apple.com/cn/app/id{app_id}"
    try:
        req = Request(cn_url, headers=HEADERS)
        resp = urlopen(req, timeout=8)
        if resp.getcode() < 400:
            resp.close()
            return cn_url
    except Exception:
        pass
    return f"https://apps.apple.com/app/id{app_id}"

# ========== 页面抓取 ==========
def fetch_apps():
    """抓取 mergeek 限免页面"""
    req = Request(SITE, headers=HEADERS)
    html = urlopen(req, timeout=30).read().decode("utf-8")

    results = []

    # --- 1. 有原价的 FREE 应用 ---
    slug_pattern = re.compile(
        r'onclick=toDetail\(&#39;([^&]+)&#39;\)[^>]*>\s*([^<]+?)\s*</a>'
    )
    seen = set()

    for slug, name in slug_pattern.findall(html):
        short_slug = slug.split("/")[-1]
        name = name.strip()

        # 跳过描述文本（too long → 不是应用名）
        if len(name) > 40 or short_slug in seen:
            continue
        seen.add(short_slug)

        # 找上下文
        idx = html.find(slug)
        if idx == -1:
            continue
        context = html[max(0, idx - 600):min(len(html), idx + 2500)]

        # 跳过冰点特价
        if "selected_freezing" in context:
            continue

        # 确认是 FREE
        if "FREE" not in context:
            continue

        # 提取原价
        price = None
        pm = re.search(r"(\d+(?:\.\d+)?)\s*(?:&#20803;|元)", context)
        if pm:
            price = pm.group(1)

        # 提取分类
        cat = ""
        cm = re.search(
            r'class="[^"]*meta-category[^"]*"[^>]*>.*?<a[^>]*>\s*([^<]+?)\s*</a>',
            context, re.DOTALL
        )
        if cm:
            cat = cm.group(1).strip()

        # 提取评分
        rating = ""
        rm = re.search(
            r'(\d+\.?\d*)\s*·\s*(\d+)\s*(?:&#20010;&#35780;&#20998;|个评分)',
            context
        )
        if rm:
            rating = f"⭐{rm.group(1)} ({rm.group(2)}评)"

        results.append({
            "slug": short_slug,
            "name": name,
            "price": price,
            "category": cat,
            "rating": rating,
            "type": "限免",
        })

    # --- 2. ★免费应用（长期免费） ---
    free_titles = re.findall(
        r'class="[^"]*selected-free-title[^"]*"[^>]*>\s*([^<]+?)\s*</',
        html
    )
    free_tags = re.findall(
        r'class="[^"]*selected-free-tag[^"]*"[^>]*>\s*#([^<]+?)\s*</',
        html
    )

    for name in free_titles:
        name = name.strip()
        if not name or name in seen:
            continue
        seen.add(name)

        # 找对应的 tag (按顺序)
        tag = free_tags[len([r for r in results if r["type"] == "免费"])] if len(free_tags) > 0 else ""
        tag = tag[:8] if tag else ""

        results.append({
            "slug": name,  # 用名字做去重 key
            "name": name,
            "price": None,
            "category": tag,
            "rating": "",
            "type": "免费",
        })

    return results

# ========== 去重 ==========
def load_sent():
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_sent(s):
    with open(SENT_FILE, "w") as f:
        json.dump(sorted(list(s)), f)

# ========== Telegram 发送 ==========
def tg_send(text):
    data = json.dumps({"chat_id": CHANNEL, "text": text}).encode("utf-8")
    req = Request(f"{TG_API}/sendMessage", data=data,
                  headers={"Content-Type": "application/json"})
    try:
        resp = urlopen(req, timeout=15)
        return json.loads(resp.read()).get("ok", False)
    except Exception:
        return False

def build_line(app, idx):
    """构建单行消息"""
    # 获取 App Store ID
    app_id = search_app_id(app["name"])
    if not app_id:
        print(f"  ⚠️ 未找到 App ID: {app['name']}")
        return None

    final_url = resolve_url(app_id)
    cn = "🇨🇳" if "/cn/" in final_url else "🌐"

    line = f"{idx}. {app['name']}"
    if app["type"] == "限免" and app["price"]:
        line += f"\n   原价 ¥{app['price']} → 免费"
    else:
        line += f"\n   长期免费"
    extras = []
    if app["category"]:
        extras.append(app["category"])
    if app["rating"]:
        extras.append(app["rating"])
    if extras:
        line += f" | {' · '.join(extras)}"
    line += f"\n   {final_url}"

    print(f"  {cn} {app['name'][:30]}: {final_url}")
    return line

# ========== 主逻辑 ==========
def main():
    print(f"🕐 {datetime.now()} 抓取 mergeek 限免...")
    apps = fetch_apps()
    print(f"📊 共解析 {len(apps)} 个应用")

    sent = load_sent()
    new_apps = [a for a in apps if a["slug"] not in sent]
    for a in new_apps:
        sent.add(a["slug"])

    if not new_apps:
        print("✅ 没有新增应用")
        save_sent(sent)
        return

    print(f"🆕 {len(new_apps)} 个新应用")

    for start in range(0, len(new_apps), 10):
        batch = new_apps[start:start + 10]
        now = datetime.now().strftime("%m/%d")
        lines = [f"📱 限免 · Mergeek ({now})", ""]
        cnt = 0
        for i, a in enumerate(batch, start + 1):
            line = build_line(a, i)
            if line:
                lines.append(line)
                cnt += 1
            time.sleep(0.5)  # 避免 Apple API 限流

        if cnt == 0:
            print("  ⚠️ 所有应用 App ID 查找失败")
            continue

        msg = "\n".join(lines)
        ok = tg_send(msg)
        print(f"  {'✅' if ok else '❌'} batch {start // 10 + 1}")

    save_sent(sent)
    print("🏁 完成")

if __name__ == "__main__":
    main()
