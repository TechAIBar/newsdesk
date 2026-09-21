from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


def data_dir() -> Path:
    override = os.environ.get("NEWSDESK_DATA_DIR")
    return Path(override) if override else Path(os.environ.get("LOCALAPPDATA", Path.home())) / "NewsDesk"


def http_url(value: str) -> bool:
    try:
        u = urlsplit(value)
        return u.scheme in ("http", "https") and bool(u.hostname) and not u.username and not u.password
    except ValueError:
        return False


@dataclass
class Source:
    id: str
    name: str
    section: str
    kind: str
    url: str
    interval: int = 30
    enabled: bool = True
    fallback: str = ""


def default_sources() -> list[Source]:
    return [
        Source("hf", "Hugging Face", "papers", "hf", "https://huggingface.co/api/daily_papers", 60),
        Source("ithome", "IT之家", "news", "rss", "https://www.ithome.com/rss/"),
        Source("techcrunch", "TechCrunch · AI", "news", "rss", "https://techcrunch.com/category/artificial-intelligence/feed/"),
        Source("hackernews", "Hacker News", "news", "rss", "https://news.ycombinator.com/rss"),
        Source("weibo", "微博热搜", "social", "hot", "https://60s.crystelf.top/v2/weibo", 60, fallback="https://api.elysiayanyu.top/v2/weibo"),
        Source("rednote", "小红书热点", "social", "hot", "https://60s.crystelf.top/v2/rednote", 60, fallback="https://60s.viki.moe/v2/rednote"),
    ]


@dataclass
class Config:
    sources: list[Source] = field(default_factory=default_sources)
    notifications: bool = True
    daily_digest: bool = True
    digest_time: str = "09:00"
    quiet_start: int = 23
    quiet_end: int = 8
    hover_delay_ms: int = 350
    max_items: int = 50
    ai_enabled: bool = False
    ai_authorized: bool = False
    ai_mode: str = "lan"
    ai_lan_url: str = ""
    ai_lan_fingerprint: str = ""
    ai_lan_token: str = ""
    ai_command: list[str] = field(default_factory=list)
    ai_agent: str = "main"
    ai_limit: int = 8

    def validate(self):
        if not 10 <= self.max_items <= 200:
            raise ValueError("列表条数须为 10–200")
        if not 100 <= self.hover_delay_ms <= 3000:
            raise ValueError("悬停时间须为 100–3000 毫秒")
        if not 1 <= self.ai_limit <= 20:
            raise ValueError("AI 每批条数须为 1–20")
        if any(not isinstance(v, int) or not 0 <= v <= 23 for v in (self.quiet_start, self.quiet_end)):
            raise ValueError("免打扰时段须为 0–23 时；起止相同表示关闭")
        parts = self.digest_time.split(":")
        if len(parts) != 2 or not all(v.isdigit() for v in parts) or not (0 <= int(parts[0]) < 24 and 0 <= int(parts[1]) < 60):
            raise ValueError("每日推送时间格式为 HH:mm")
        ids = set()
        for s in self.sources:
            if not s.id or s.id in ids:
                raise ValueError("数据源 ID 不能为空或重复")
            ids.add(s.id)
            if s.section not in ("papers", "news", "social") or s.kind not in ("hf", "rss", "hot", "weibo"):
                raise ValueError("数据源板块或类型无效")
            if not http_url(s.url) or (s.fallback and not http_url(s.fallback)):
                raise ValueError(f"{s.name} 需要有效的 HTTP(S) 地址")
            if not 5 <= s.interval <= 1440:
                raise ValueError("刷新间隔须为 5–1440 分钟")
        if self.ai_mode not in ("local", "lan"):
            raise ValueError("AI 连接方式无效")
        if self.ai_enabled:
            if not self.ai_authorized:
                raise ValueError("请先配对局域网 OpenClaw")
            if self.ai_mode == "local" and not self.ai_command:
                raise ValueError("请先通过 authorize-openclaw 命令授权 AI")
            if self.ai_mode == "lan" and (not self.ai_lan_url.startswith("https://") or not http_url(self.ai_lan_url)
                                         or len(self.ai_lan_fingerprint) != 64 or not self.ai_lan_token):
                raise ValueError("局域网配对信息不完整")

    def save(self, path: Path | None = None):
        self.validate()
        target = path or data_dir() / "config.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        target = path or data_dir() / "config.json"
        if not target.exists():
            return cls()
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
        if raw.get("ai_agent") == "newsdesk":
            raw["ai_agent"] = "main"
        if "sources" in raw:
            raw["sources"] = [Source(**s) for s in raw["sources"]]
        value = cls(**raw)
        value.validate()
        return value


def is_quiet(hour: int, start: int, end: int) -> bool:
    if start == end:
        return False
    return start <= hour < end if start < end else hour >= start or hour < end
