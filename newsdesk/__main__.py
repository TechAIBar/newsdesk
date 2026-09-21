from __future__ import annotations

import argparse
import getpass
import json
import logging
from logging.handlers import RotatingFileHandler
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from .config import Config, data_dir


def main(argv=None):
    parser = argparse.ArgumentParser(prog="NewsDesk", description="知更 · Windows 托盘新闻聚合")
    sub = parser.add_subparsers(dest="action")
    run = sub.add_parser("run", help="启动托盘程序")
    run.add_argument("--show", action="store_true")
    run.add_argument("--settings", action="store_true", help="启动后直接打开设置")
    run.add_argument("--offline", action="store_true", help="只显示缓存，供离线阅读和测试")
    run.add_argument("--smoke-seconds", type=float, default=0)
    run.add_argument("--screenshot", type=Path)
    refresh = sub.add_parser("refresh", help="获取全部数据并退出，输出各源状态")
    refresh.add_argument("--report", type=Path)
    sub.add_parser("init", help="创建默认配置，不覆盖已有配置")
    sub.add_parser("config-path", help="显示配置文件路径")
    sub.add_parser("revoke-openclaw", help="撤销本应用的 AI 调用授权")
    auth = sub.add_parser("authorize-openclaw", help="授权调用已有 OpenClaw 的 main agent")
    auth.add_argument("--command", default="openclaw")
    auth.add_argument("--wsl", default="", help="WSL 发行版名称，例如 Ubuntu")
    pairing = sub.add_parser("pair-openclaw", help="导入局域网 OpenClaw 主机生成的配对码")
    pairing.add_argument("--file", type=Path, help="从本机文本文件读取配对码；省略时隐藏输入")
    bridge = sub.add_parser("serve-openclaw", help="在已安装 OpenClaw 的 Windows 主机运行局域网摘要授权服务")
    bridge.add_argument("bridge_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    directory = data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(directory / "newsdesk.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        if args.action == "serve-openclaw":
            from .bridge import main as serve
            bridge_args = args.bridge_args
            if bridge_args[:1] == ["--"]:
                bridge_args = bridge_args[1:]
            return serve(bridge_args)
        if args.action in (None, "run"):
            from .app import run
            return run(getattr(args, "show", False), getattr(args, "smoke_seconds", 0), getattr(args, "screenshot", None), getattr(args, "offline", False), getattr(args, "settings", False))
        if args.action == "config-path":
            print(directory / "config.json")
            return 0
        config = Config.load()
        if args.action == "init":
            if not (directory / "config.json").exists():
                config.save()
            print(directory / "config.json")
        elif args.action == "pair-openclaw":
            from .lan import pair
            code = args.file.read_text(encoding="utf-8-sig").strip() if args.file else getpass.getpass("粘贴 OpenClaw 主机生成的 ND1- 配对码（输入隐藏）：")
            cfg = pair(config, code)
            cfg.save()
            print(f"局域网配对成功：{cfg.ai_lan_url}。请在托盘菜单重新加载配置。")
        elif args.action == "authorize-openclaw":
            from .ai import authorize, resolve_command
            print("正在授权：通过 Gateway 调用已有 main agent，沿用其模型与权限。")
            authorize(config, resolve_command(args.command, args.wsl))
            print("授权与模型连通测试成功。请在托盘菜单重新加载配置。")
        elif args.action == "revoke-openclaw":
            config.ai_enabled = config.ai_authorized = False
            config.ai_command = []
            config.ai_lan_url = config.ai_lan_fingerprint = config.ai_lan_token = ""
            config.save()
            print("已撤销本机调用授权。请在托盘菜单重新加载配置。")
        elif args.action == "refresh":
            from .feeds import fetch_source
            from .storage import Store
            sources = [s for s in config.sources if s.enabled]
            with ThreadPoolExecutor(max_workers=6) as pool:
                results = list(pool.map(lambda s: fetch_source(s, config.max_items), sources))
            store = Store(directory / "cache.sqlite3")
            reports = []
            try:
                for result in results:
                    store.merge(result)
                    report = {"source": result.source_id, "count": len(result.items), "day": result.day,
                              "fetched_at": result.fetched_at, "error": result.error, "note": result.note}
                    reports.append(report)
                    print(json.dumps(report, ensure_ascii=False))
            finally:
                store.close()
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
            return 2 if any(r.error for r in results) else 0
        return 0
    except Exception as exc:
        logging.error("Command failed (%s)", type(exc).__name__)
        if sys.stderr is not None:
            print(str(exc), file=sys.stderr)
        else:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"启动失败：{exc}\n日志：{directory / 'newsdesk.log'}", "知更", 0x10)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
