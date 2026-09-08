#!/usr/bin/env python3
"""
tf_translate.py — TestFlight 简介中文化工具
============================================================
给 tf_scraper.py 用：把每款 App 的简介转成中文。

策略（依次尝试，取第一个成功的）：
  0. 缓存命中           —— descriptions.json / tf_titles_cn.json 里已有中文，直接返回
  1. 已经是中文         —— 本身含中文，规整后直接用（不浪费翻译额度）
  2. App Store 中国区   —— 按 App 名查 iTunes(cn)，拿官方中文简介/中文名（质量最好）
  3. 腾讯云 TMT 机器翻译 —— 主用机翻源（免费额度内），把英文翻成中文
  4. gtx 兜底           —— TMT 不可用时的最后兜底
  5. 都失败             —— 简介返回原文（英文）；标题返回 None（保留英文原名）

所有成功结果都会写回缓存 descriptions.json，下次直接命中、不再联网。

对外主函数：
  translate_entries(entries, cache_path="descriptions.json")
      entries: [{"name":..., "desc":..., ...}, ...]（就地补/改 desc 字段）
"""
import json
import os
import re
import time
import hashlib
import hmac
import datetime
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
def itunes_cn_lookup(name):
    """按 App 名查中国区 App Store，返回 (中文名, 中文简介)，找不到返回 (None, None)。"""
    try:
        q = urllib.parse.urlencode({"term": name, "entity": "software",
                                    "limit": 5, "country": "cn"})
        d = json.loads(_get("https://itunes.apple.com/search?" + q, timeout=15))
        for r in d.get("results", []):
            tn = r.get("trackName") or ""
            desc = (r.get("description") or "").strip()
            if _name_matches(name, tn):
                return (tn if has_cjk(tn) else None,
                        desc if (desc and has_cjk(desc)) else None)
    except Exception:
        pass
    return (None, None)


def itunes_cn_desc(name):
    """按 App 名查中国区 App Store，返回官方中文简介或 None。"""
    return itunes_cn_lookup(name)[1]


def gtx_translate(text, tl="zh-CN"):
    """免费 Google 翻译端点，失败返回 None。内部重试一次以提高成功率。"""
    if not text:
        return None
    text = text[:1500]
    q = urllib.parse.urlencode({"client": "gtx", "sl": "auto", "tl": tl,
                                "dt": "t", "q": text})
    for attempt in range(2):
        try:
            d = json.loads(_get("https://translate.googleapis.com/translate_a/single?" + q, timeout=15))
            out = "".join(seg[0] for seg in d[0] if seg[0])
            if out:
                return out
        except Exception:
            time.sleep(1.0 * (attempt + 1))
    return None


# ---------- 腾讯云机器翻译 TMT（主用机翻源）----------
def _tmt_creds():
    """从环境变量读取腾讯云密钥；未配置返回 (None, None)。"""
    return (os.getenv("TENCENTCLOUD_SECRET_ID"), os.getenv("TENCENTCLOUD_SECRET_KEY"))


def _tc3_sign(secret_id, secret_key, payload, action, timestamp, region="ap-guangzhou"):
    """构造腾讯云 API TC3-HMAC-SHA256 签名，返回 (Authorization, headers)。"""
    service = "tmt"
    version = "2018-03-21"
    endpoint = "tmt.tencentcloudapi.com"
    date = datetime.datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")
    ct = "application/json; charset=utf-8"

    canonical_headers = f"content-type:{ct}\nhost:{endpoint}\n"
    signed_headers = "content-type;host"
    payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = "\n".join([
        "POST", "/", "",
        canonical_headers, signed_headers, payload_hash,
    ])
    credential_scope = f"{date}/{service}/tc3_request"
    string_to_sign = "\n".join([
        "TC3-HMAC-SHA256",
        str(timestamp),
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])
    secret_date = hmac.new(("TC3" + secret_key).encode("utf-8"), date.encode("utf-8"), hashlib.sha256).digest()
    secret_service = hmac.new(secret_date, service.encode("utf-8"), hashlib.sha256).digest()
    secret_signing = hmac.new(secret_service, b"tc3_request", hashlib.sha256).digest()
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        f"TC3-HMAC-SHA256 Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    headers = {
        "Authorization": authorization,
        "Content-Type": ct,
        "Host": endpoint,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": version,
        "X-TC-Region": region,
    }
    return headers


def tmt_translate(text, source="en", target="zh", region="ap-guangzhou"):
    """腾讯云机器翻译 TMT 文本翻译。失败返回 None。
    凭证从环境变量 TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY 读取。
    免费额度内（每月 500 万字符）不收费。
    """
    if not text or not text.strip():
        return None
    secret_id, secret_key = _tmt_creds()
    if not secret_id or not secret_key:
        return None
    text = text[:2000]  # TMT 单次文本翻译长度限制
    payload = json.dumps({
        "SourceText": text, "Source": source,
        "Target": target, "ProjectId": 0,
    })
    timestamp = int(time.time())
    try:
        headers = _tc3_sign(secret_id, secret_key, payload, "TextTranslate", timestamp, region)
        if _HTTP == "requests":
            r = requests.post("https://tmt.tencentcloudapi.com", headers=headers,
                              data=payload.encode("utf-8"), timeout=15)
            d = r.json()
        else:
            req = urllib.request.Request("https://tmt.tencentcloudapi.com",
                                         data=payload.encode("utf-8"), headers=headers, method="POST")
            d = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore"))
        resp = d.get("Response", {})
        if resp.get("TargetText"):
            return resp["TargetText"].strip()
        if resp.get("Error"):
            print(f"⚠️ TMT 错误: {resp['Error'].get('Code')} {resp['Error'].get('Message')}")
    except Exception as e:
        print(f"⚠️ TMT 调用异常: {e}")
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

    # 3) 机器翻译已有英文简介（TMT 主用，gtx 兜底）
    if desc:
        zh = tmt_translate(desc) or gtx_translate(desc)
        if zh and has_cjk(zh):
            return _tidy(zh)
        return _tidy(desc)  # 翻译失败，原文兜底

    # 4) 无简介
    return ""


# ---------- 标题中文化（新增）----------
def to_chinese_name(name):
    """
    返回 App 的中文名（尽力）。不写缓存，纯计算。
    调用方负责缓存（title_cache_path）。
    """
    if not name:
        return None
    if has_cjk(name):
        return name  # 本就中文
    # 1) App Store 中国区官方中文名（最佳）
    cn_name, _ = itunes_cn_lookup(name)
    if cn_name:
        return cn_name
    # 2) 机器翻译英文名（TMT 主用，gtx 兜底）
    zh = tmt_translate(name) or gtx_translate(name)
    if zh and has_cjk(zh):
        return _tidy(zh)
    # 3) 都失败 → 返回 None（调用方保留英文原名）
    return None


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


def translate_entries(entries, cache_path="descriptions.json", title_cache_path=None, sleep=0.25, verbose=True):
    """
    就地把 entries 里每条中文化：
      - desc  → 中文简介（写回 e['desc']）
      - name  → 中文标题（写回 e['name_cn']，仅当翻译成功且与原名不同）
    命中缓存不联网；新翻译结果写回缓存。
    返回 entries（同一对象）。
    """
    cache = load_cache(cache_path)
    title_cache = load_cache(title_cache_path) if title_cache_path else None
    n_cache = n_new = n_empty = 0
    n_title = 0

    for e in entries:
        name = (e.get("name") or "").strip()
        desc = e.get("desc") or ""

        # ---------- 简介中文化 ----------
        translated = False
        if name and name in cache and cache[name] and has_cjk(cache[name]):
            e["desc"] = cache[name]
            n_cache += 1
            translated = True
        if not translated:
            zh = to_chinese(name, desc)
            e["desc"] = zh
            if zh and has_cjk(zh):
                if name:
                    cache[name] = zh
                n_new += 1
                time.sleep(sleep)  # 温柔一点，别打爆接口
            else:
                if name:
                    cache.pop(name, None)  # 清掉旧的英文/空脏缓存
                n_empty += 1

        # ---------- 标题中文化（新增）----------
        if title_cache is not None and name:
            if name in title_cache and has_cjk(title_cache[name]):
                e["name_cn"] = title_cache[name]
                n_title += 1
            else:
                cn = to_chinese_name(name)
                if cn and has_cjk(cn) and cn != name:
                    e["name_cn"] = cn
                    title_cache[name] = cn
                    n_title += 1
                    time.sleep(sleep)
                else:
                    title_cache.pop(name, None)  # 翻译失败，保留英文原名

    save_cache(cache, cache_path)
    if title_cache is not None:
        save_cache(title_cache, title_cache_path)
    if verbose:
        print(f"🌐 简介中文化: 缓存命中 {n_cache} | 新处理 {n_new} | 仍为空 {n_empty}")
        if title_cache is not None:
            print(f"🌐 标题中文化: 新处理/命中 {n_title} 条")
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
