# 🤖 TestFlight 链接抓取器（纯数据采集，不推送）
# 提供 fetch_all_y() 供 tf_scraper.py 调用

import re, json, os
from urllib.request import urlopen, Request

BASE = "https://raw.githubusercontent.com/fmz200/global-testflight-link/main"
PAGES = ["README.md"] + [f"readme/table{i}.md" for i in range(2, 35)]
SENT_FILE = "sent_codes.json"

ROW_PAT = re.compile(
    r'<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*'
    r'<td[^>]*>.*?join/([A-Za-z0-9]+).*?</td>\s*<td[^>]*>([YFND])</td>',
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
        with open(SENT_FILE, 'r') as f: return set(json.load(f))
    return set()

def save_sent(s):
    with open(SENT_FILE, 'w') as f: json.dump(sorted(list(s)), f)
