#!/usr/bin/env python3
"""
tf_translate.py — TestFlight 简介中文化工具
============================================================
给 tf_scraper.py 用：把每款 App 的简介转成中文。

策略（依次尝试，取第一个成功的）：
  0. 缓存命中           —— descriptions.json 里已有该 App 的中文简介，直接返回
  1. 已经是中文         —— desc 本身含中文，规整后直接用（不浪费翻译额度）
  2. App Store 中国区   —— 按 App 名查 iTunes(cn)，拿官方中文简介（质量最好）
  3. 机器翻译英文简介   —— 把已有英文 desc 翻成中文
  4. 都失败             —— 返回原文（英文）或空

所有成功结果都会写回缓存 descriptions.json，下次直接命中、不再联网。

对外主函数：
  translate_entries(entries, cache_path="descriptions.json")
      entries: [{"name":..., "desc":..., ...}, ...]（就地补/改 desc 字段）
"""
import json
import re
import time
import urllib.parse
from pathlib import Path

try:
    import requests
    _HTTP = "requests"
except Exception:  # 退回标准库
    import urllib.request
    _HTTP = "urllib"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"
MAX_LEN = 120  # 与项目现有 descriptions 风格一致，简介截断长度


# ---------- 底层 HTTP ----------
def _get(url, timeout=15, tries=2):
    last = None
    for i in range(tries):
        try:
            if _HTTP == "requests":
                r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
                r.raise_for_status()
                return r.text
            else:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
        except Exception as e:
            last = e
            time.sleep(1.0 * (i + 1))
    raise last


# ---------- 工具 ----------
def has_cjk(s):
    return bool(re.search(r"[一-鿿]", s or ""))


def _norm(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9一-鿿]+", " ", s)
    for w in ("beta", "app", "ios", "test", "testflight"):
        s = re.sub(rf"\b{w}\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _name_matches(query, candidate):
    """iTunes 返回名是否确实对应 query，防错配。"""
    a, b = _norm(query), _norm(candidate)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return False
    inter = len(sa & sb)
    return inter >= 1 and inter / len(sa | sb) >= 0.5


def _tidy(text):
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) > MAX_LEN:
        text = text[:MAX_LEN].rstrip() + "..."
    return text


# ---------- 简介来源 ----------
def itunes_cn_desc(name):
    """按 App 名查中国区 App Store，返回官方中文简介或 None。"""
    try:
        q = urllib.parse.urlencode({"term": name, "entity": "software",
                                    "limit": 5, "country": "cn"})
        d = json.loads(_get("https://itunes.apple.com/search?" + q, timeout=15))
        for r in d.get("results", []):
            tn = r.get("trackName") or ""
            desc = (r.get("description") or "").strip()
            if desc and has_cjk(desc) and _name_matches(name, tn):
                return desc
    except Exception:
        pass
    return None


def gtx_translate(text, tl="zh-CN"):
    """免费 Google 翻译端点，失败返回 None。"""
    if not text:
        return None
    text = text[:1500]
    try:
        q = urllib.parse.urlencode({"client": "gtx", "sl": "auto", "tl": tl,
                                    "dt": "t", "q": text})
        d = json.loads(_get("https://translate.googleapis.com/translate_a/single?" + q, timeout=15))
        out = "".join(seg[0] for seg in d[0] if seg[0])
        return out or None
    except Exception:
        return None


# ---------- 核心：单条中文化 ----------
def to_chinese(name, desc):
    """
    返回该 App 的中文简介（尽力）。不写缓存，纯计算。
    调用方负责缓存。
    """
    # 1) desc 本身已是中文
    if desc and has_cjk(desc):
        return _tidy(desc)

    # 2) App Store 中国区官方中文简介（最佳）
    cn = itunes_cn_desc(name)
    if cn:
        return _tidy(cn)

    # 3) 机器翻译已有英文简介
    if desc:
        zh = gtx_translate(desc)
        if zh and has_cjk(zh):
            return _tidy(zh)
        return _tidy(desc)  # 翻译失败，原文兜底

    # 4) 无简介
    return ""


# ---------- 对外主函数 ----------
def load_cache(cache_path):
    p = Path(cache_path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_cache(cache, cache_path):
    try:
        Path(cache_path).write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def translate_entries(entries, cache_path="descriptions.json", sleep=0.25, verbose=True):
    """
    就地把 entries 里每条的 desc 中文化。
    命中缓存不联网；新翻译结果写回缓存。
    返回 entries（同一对象）。
    """
    cache = load_cache(cache_path)
    n_cache = n_new = n_empty = 0

    for e in entries:
        name = (e.get("name") or "").strip()
        desc = e.get("desc") or ""

        # 缓存命中（按 App 名）
        if name and name in cache and cache[name]:
            e["desc"] = cache[name]
            n_cache += 1
            continue

        zh = to_chinese(name, desc)
        e["desc"] = zh
        if zh:
            if name:
                cache[name] = zh
            n_new += 1
            time.sleep(sleep)  # 温柔一点，别打爆接口
        else:
            n_empty += 1

    save_cache(cache, cache_path)
    if verbose:
        print(f"🌐 简介中文化: 缓存命中 {n_cache} | 新处理 {n_new} | 仍为空 {n_empty}")
    return entries


# ---------- 命令行自测 ----------
if __name__ == "__main__":
    demo = [
        {"name": "1Password - Password Manager", "desc": ""},
        {"name": "Elevate - Brain Training Games",
         "desc": "Elevate is a brain training program designed to improve focus, memory and processing speed."},
        {"name": "颠倒思维", "desc": "一款锻炼逆向思维的脑力训练游戏。"},
    ]
    translate_entries(demo, cache_path="/tmp/_tf_cache_demo.json", verbose=True)
    for d in demo:
        print(f"  {d['name']}\n    -> {d['desc']}")
