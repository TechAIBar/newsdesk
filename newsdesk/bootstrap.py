"""Generate one directly executable command, containing its host runtime in memory."""
from __future__ import annotations

import base64
import gzip
import ipaddress
import json
from pathlib import Path
import sys


def runtime_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "newsdesk" / "resources" / "openclaw_bootstrap.cjs"


def make_command(host: str = "", port: int = 18790, command: str = "", rotate: bool = False, mode: str = "gateway", autostart: bool = True) -> str:
    host = host.strip()
    if host:
        try:
            address = ipaddress.ip_address(host)
            if address.version != 4 or not address.is_private or address.is_unspecified or address.is_link_local:
                raise ValueError()
        except ValueError:
            raise ValueError("请输入 OpenClaw 主机的局域网 IPv4 地址，或留空自动识别") from None
    if not 1024 <= port <= 65535:
        raise ValueError("端口须为 1024–65535")
    if len(command) > 500 or any(c in command for c in ("\r", "\n", "\x00")):
        raise ValueError("OpenClaw 命令路径无效")
    if mode not in ("gateway", "local"):
        raise ValueError("OpenClaw 运行方式无效")
    options = {"host": host, "port": port, "command": command.strip() or "openclaw", "rotate": bool(rotate), "mode": mode, "autostart": bool(autostart)}
    source = "globalThis.NEWSDESK_BOOTSTRAP_OPTIONS=" + json.dumps(options, ensure_ascii=True, separators=(",", ":")) + ";\n"
    source += runtime_path().read_text(encoding="utf-8")
    encoded = base64.b64encode(gzip.compress(source.encode("utf-8"), compresslevel=9, mtime=0)).decode("ascii")
    # Only constant syntax and base64 cross the shell boundary. No host/path text is interpolated.
    return 'node -e "eval(require(\'node:zlib\').gunzipSync(Buffer.from(\'' + encoded + '\',\'base64\')).toString(\'utf8\'))"'


def make_service_command(action: str) -> str:
    if action not in ("start", "stop", "status"):
        raise ValueError("服务管理操作无效")
    code = ("require(require('node:path').join(require('node:os').homedir(),'.newsdesk-node-bridge','service.cjs'))"
            + ".manage('" + action + "').catch(e=>{console.error(e.message);process.exitCode=1})")
    return 'node -e "' + code + '"'
