from __future__ import annotations

import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

from .config import Source, http_url


@dataclass
class Item:
    id: str
    source_id: str
    source: str
    section: str
    title: str
    url: str
    summary: str = ""
    published: str = ""
    rank: int = 0
    score: str = ""
    day: str = ""
    ai_summary: str = ""
    read: bool = False


@dataclass
class FeedResult:
    source_id: str
    items: list[Item] = field(default_factory=list)
    fetched_at: str = ""
    day: str = ""
    error: str = ""
    note: str = ""


def plain(value: object, limit: int = 2500) -> str:
    value = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", str(value or ""), flags=re.I | re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", value))).strip()[:limit]


def canonical_url(url: str) -> str:
    u = urllib.parse.urlsplit(url)
    query = urllib.parse.urlencode([(k, v) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True)
                                   if not k.lower().startswith("utm_") and k not in ("fbclid", "gclid")])
    return urllib.parse.urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path, query, ""))


def item_for(s: Source, title: str, url: str, **kwargs) -> Item | None:
    title = plain(title, 500)
    if not title or not http_url(url):
        return None
    url = canonical_url(url)
    ident = hashlib.sha256((s.id + "|" + url).encode()).hexdigest()[:24]
    return Item(ident, s.id, s.name, s.section, title, url, **kwargs)


def request_bytes(url: str, timeout: int = 15) -> bytes:
    if not http_url(url):
        raise ValueError("仅支持 HTTP(S) 数据源")
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "NewsDesk/1.0 (Windows; RSS reader)",
                                                       "Accept": "application/json, application/rss+xml, application/atom+xml, */*"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                if not http_url(response.url):
                    raise ValueError("数据源重定向地址无效")
                data = response.read(6 * 1024 * 1024 + 1)
                if len(data) > 6 * 1024 * 1024:
                    raise ValueError("响应超过 6 MB")
                return data
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt:
                raise
        time.sleep(0.5)
    raise RuntimeError("请求失败")


def parse_papers(data: object, s: Source, day: str) -> list[Item]:
    if not isinstance(data, list):
        raise ValueError("Hugging Face 返回格式异常")
    out = []
    for row in data:
        p = row.get("paper", row)
        paper_id = str(p.get("id", ""))
        if not re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", paper_id):
            continue
        i = item_for(s, row.get("title") or p.get("title", ""), f"https://huggingface.co/papers/{paper_id}",
                     summary=plain(p.get("summary") or row.get("summary")),
                     published=p.get("publishedAt", ""), score=str(p.get("upvotes", 0)) + " 赞", day=day)
        if i:
            out.append(i)
    if data and not out:
        raise ValueError("论文列表未包含有效条目")
    return out


def parse_rss(data: bytes, s: Source) -> list[Item]:
    # Reject DTD/entity declarations before XML parsing, including UTF-16 inputs.
    scan = data.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in scan or b"<!ENTITY" in scan:
        raise ValueError("不支持包含 DTD 或实体声明的订阅源")
    root = ET.fromstring(data)
    local = lambda tag: tag.rsplit("}", 1)[-1]
    if local(root.tag) not in ("rss", "feed", "RDF"):
        raise ValueError("该地址没有返回 RSS/Atom，可能需要登录或已失效")
    out = []
    for row in root.iter():
        if local(row.tag) not in ("item", "entry"):
            continue
        values = {}
        url = ""
        for child in row:
            tag = local(child.tag)
            values[tag] = "".join(child.itertext()).strip()
            if tag == "link" and child.attrib.get("rel", "alternate") == "alternate":
                url = child.attrib.get("href") or values[tag]
        stamp = values.get("pubDate") or values.get("published") or values.get("updated") or values.get("date", "")
        try:
            date = parsedate_to_datetime(stamp)
            stamp = date.astimezone().isoformat()
        except (ValueError, TypeError, OverflowError):
            try:
                stamp = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone().isoformat()
            except ValueError:
                stamp = ""
        i = item_for(s, values.get("title", ""), urllib.parse.urljoin(s.url, url) if url else "",
                     summary=plain(values.get("description") or values.get("summary") or values.get("encoded") or values.get("content")),
                     published=stamp)
        if i:
            out.append(i)
    if not out:
        raise ValueError("订阅源暂无有效条目")
    return out


def parse_hot(data: object, s: Source, day: str) -> list[Item]:
    if isinstance(data, dict):
        if data.get("success") is False or data.get("code", 200) not in (0, 200, "200"):
            raise ValueError("热榜服务返回失败状态")
        rows = data.get("data", data.get("items", []))
        if isinstance(rows, dict):
            rows = rows.get("items", rows.get("list", []))
    else:
        rows = data
    if not isinstance(rows, list):
        raise ValueError("热榜格式应为 JSON 条目数组")
    out = []
    for index, row in enumerate(rows, 1):
        title = row.get("title") or row.get("word") or row.get("name", "")
        url = row.get("url") or row.get("link") or row.get("mobileUrl")
        if not url:
            base = "https://www.xiaohongshu.com/search_result?keyword=" if s.id == "rednote" else "https://s.weibo.com/weibo?q="
            url = base + urllib.parse.quote(str(title))
        i = item_for(s, title, url, rank=index, score=plain(row.get("score") or row.get("hot_value") or row.get("hot", ""), 60), day=day)
        if i:
            out.append(i)
    if not out:
        raise ValueError("热榜暂无有效条目，请稍后重试或更换数据源")
    return out


def parse_weibo(data: dict, s: Source, day: str) -> list[Item]:
    rows = data.get("data", {}).get("realtime")
    if not isinstance(rows, list):
        raise ValueError("微博接口暂不可用")
    return parse_hot([{"title": row.get("word"), "hot": row.get("num", "")} for row in rows if not row.get("is_ad")], s, day)


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}：源站限制访问或暂不可用，可在设置中更换地址"
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return "网络连接失败或超时，请检查网络和系统代理"
    if isinstance(exc, (json.JSONDecodeError, ET.ParseError)):
        return "数据源未返回有效的 JSON / RSS"
    return str(exc)[:180]


def fetch_source(s: Source, limit: int = 50, today: str | None = None, fetch=request_bytes) -> FeedResult:
    day = today or datetime.now().astimezone().date().isoformat()
    result = FeedResult(s.id, fetched_at=datetime.now().astimezone().isoformat(), day=day)
    try:
        if s.kind == "hf":
            # Pagination is zero-based. Fetch the entire day's list; UI limit applies to other sources.
            found = {}
            for page in range(20):
                u = urllib.parse.urlsplit(s.url)
                params = dict(urllib.parse.parse_qsl(u.query))
                params.update(date=day, p=page, limit=100)
                url = urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, urllib.parse.urlencode(params), ""))
                raw = json.loads(fetch(url))
                parsed = parse_papers(raw, s, day)
                before = len(found)
                found.update({i.id: i for i in parsed})
                if len(raw) < 100 or len(found) == before:
                    break
            else:
                raise ValueError("论文分页超过 2000 条，请检查接口")
            result.items = list(found.values())
            result.note = f"{day} · {len(result.items)} 篇" if result.items else f"{day} 尚未发布论文（周末或发布前可能为空）"
        elif s.kind == "rss":
            result.items = parse_rss(fetch(s.url), s)[:limit]
        else:
            try:
                raw = json.loads(fetch(s.url))
                result.items = parse_weibo(raw, s, day) if s.kind == "weibo" and isinstance(raw, dict) and isinstance(raw.get("data"), dict) and "realtime" in raw["data"] else parse_hot(raw, s, day)
            except Exception:
                if not s.fallback:
                    raise
                result.items = parse_hot(json.loads(fetch(s.fallback)), s, day)
                result.note = "通过备用热榜服务获取"
            result.items = result.items[:limit]
        result.items = list({i.id: i for i in result.items}.values())
    except Exception as exc:
        result.error = friendly_error(exc)
    return result
