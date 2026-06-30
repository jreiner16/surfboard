from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

_BOT_BLOCK_PHRASES = [
    "verify you are human",
    "verify you're human",
    "are you a robot",
    "bot verification",
    "captcha",
    "cloudflare",
    "access denied",
    "enable javascript",
    "please enable cookies",
    "your browser doesn't support",
    "just a moment",
    "checking your browser",
    "ddos-guard",
    "please stand by",
    "unexpected error",
    "automated access",
    "automated queries",
    "too many requests",
    "please try again later",
    "sorry, you have been blocked",
    "you have been blocked",
    "our systems have detected",
    "suspicious activity",
    "we need to make sure you're not a robot",
]


def _is_bot_block(html: str, status_code: int) -> bool:
    if status_code in (403, 418, 429, 503):
        return True
    lower = html[:4000].lower()
    return any(phrase in lower for phrase in _BOT_BLOCK_PHRASES)


@dataclass
class FetchResult:
    url: str
    html: str
    status_code: int
    headers: dict[str, str]
    final_url: str
    error: Optional[str] = None
