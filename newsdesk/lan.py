"""LAN pairing client. TLS certificate is pinned before any bearer token is transmitted."""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import http.client
import json
import os
import re
import ssl
from urllib.parse import urlsplit

from .config import Config, http_url
from .feeds import Item, plain


def protect_secret(value: str) -> str:
    if os.name == "nt":
        return "dpapi:" + base64.b64encode(_dpapi(value.encode(), False)).decode()
    return "local:" + base64.b64encode(value.encode()).decode()


def reveal_secret(value: str) -> str:
    kind, _, encoded = value.partition(":")
    raw = base64.b64decode(encoded, validate=True)
    if kind == "dpapi" and os.name == "nt":
        return _dpapi(raw, True).decode()
    if kind == "local" and os.name != "nt":
        return raw.decode()
    raise ValueError("配对凭据属于其他 Windows 用户或机器，请重新配对")


def _dpapi(data: bytes, decrypt: bool) -> bytes:
    import ctypes
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_byte))]
    buffer = ctypes.create_string_buffer(data)
    original = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    output = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(original), None, None, None, None, 1, ctypes.byref(output)):
        raise OSError("Windows 凭据加密/解密失败")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        free = ctypes.WinDLL("kernel32").LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(output.data)


def pairing_code(url: str, token: str, fingerprint: str) -> str:
    raw = json.dumps({"v": 1, "url": url, "token": token, "fingerprint": fingerprint}, separators=(",", ":"))
    return "ND1-" + base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def parse_pairing(code: str) -> dict:
    code = code.strip()
    if not code.startswith("ND1-") or len(code) > 4096:
        raise ValueError("配对码应以 ND1- 开头")
    try:
        raw = code[4:]
        value = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        u = urlsplit(value["url"])
        if value.get("v") != 1 or not http_url(value["url"]) or u.scheme != "https" or u.path not in ("", "/") or u.query or u.fragment:
            raise ValueError()
        if not re.fullmatch(r"[a-f0-9]{64}", value["fingerprint"]) or not re.fullmatch(r"[A-Za-z0-9_-]{40,128}", value["token"]):
            raise ValueError()
        if not u.port:
            raise ValueError()
        return value
    except (ValueError, KeyError, TypeError):
        raise ValueError("配对码不完整或已损坏，请重新复制") from None


def request(url: str, fingerprint: str, token: str, path: str, payload: dict | None = None, timeout=210) -> dict:
    endpoint = urlsplit(url)
    if endpoint.scheme != "https" or not http_url(url):
        raise ValueError("局域网服务必须使用 HTTPS")
    # The peer is verified against the out-of-band pairing fingerprint, not a public CA.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    conn = http.client.HTTPSConnection(endpoint.hostname, endpoint.port, context=context, timeout=timeout)
    try:
        conn.connect()
        actual = hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest()
        if not hmac.compare_digest(actual, fingerprint):
            raise ValueError("OpenClaw 主机证书已变化，未发送凭据；请在主机重新生成配对码")
        body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        conn.request("POST" if body is not None else "GET", path, body=body,
                     headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        response = conn.getresponse()
        raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("局域网服务响应过大")
        if response.status == 401:
            raise ValueError("配对权限已撤销或配对码无效，请重新授权")
        if response.status == 429:
            raise ValueError("摘要服务正在忙碌或达到每小时限额，请稍后重试")
        if response.status != 200:
            raise ValueError(f"OpenClaw 主机处理失败（HTTP {response.status}），请查看主机控制台")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("局域网服务响应格式无效")
        return result
    finally:
        conn.close()


def pair(config: Config, code: str) -> Config:
    value = parse_pairing(code)
    result = request(value["url"], value["fingerprint"], value["token"], "/health", timeout=12)
    if result.get("service") != "newsdesk-openclaw" or result.get("scope") != "summarize":
        raise ValueError("对方不是受支持的新闻摘要服务")
    cfg = copy.deepcopy(config)
    cfg.ai_mode = "lan"
    cfg.ai_agent = "main"
    cfg.ai_lan_url = value["url"]
    cfg.ai_lan_fingerprint = value["fingerprint"]
    cfg.ai_lan_token = protect_secret(value["token"])
    cfg.ai_authorized = cfg.ai_enabled = True
    cfg.ai_command = []
    cfg.validate()
    return cfg


def summarize_remote(config: Config, items: list[Item]) -> dict[str, str]:
    selected = items[:config.ai_limit]
    rows = [{"id": i.id, "title": i.title[:220], "abstract": i.summary[:600]} for i in selected]
    result = request(config.ai_lan_url, config.ai_lan_fingerprint, reveal_secret(config.ai_lan_token),
                     "/summarize", {"items": rows})
    valid = {i.id for i in selected}
    summaries = result.get("summaries", {})
    if not isinstance(summaries, dict):
        raise ValueError("远程摘要格式无效")
    summaries = {k: plain(v, 400) for k, v in summaries.items() if k in valid and isinstance(v, str) and v.strip()}
    if not summaries:
        raise ValueError("远程服务未返回可用摘要")
    return summaries
