"""URL rewriting rules: Reddit → JSON, Twitter → Nitter, Medium → Scribe, AMP stripping."""

from __future__ import annotations

import json
import re as _re

_REDDIT_RE = _re.compile(r"https?://(?:www\.|old\.)?reddit\.com(/[^\s]*)")
_MEDIUM_RE = _re.compile(r"https?://(?:www\.)?medium\.com(/[^\s]*)")
_TWITTER_RE = _re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com(/[^\s]*)")
_AMP_RE = _re.compile(r"(https?://[^\s]+?)/amp/?$", _re.IGNORECASE)


def rewrite_url(url: str) -> tuple[str, str | None]:
    """Return (rewritten_url, note). note is set if the URL was rewritten."""
    m = _REDDIT_RE.match(url)
    if m:
        path = m.group(1).rstrip("/")
        if not path.endswith(".json"):
            return f"https://www.reddit.com{path}.json?raw_json=1", "reddit-json"

    m = _TWITTER_RE.match(url)
    if m:
        return f"https://nitter.net{m.group(1)}", "nitter-mirror"

    m = _MEDIUM_RE.match(url)
    if m:
        return f"https://scribe.rip{m.group(1)}", "scribe-mirror"

    m = _AMP_RE.match(url)
    if m:
        return m.group(1), "amp-stripped"

    return url, None


def reddit_json_to_html(raw: str, url: str) -> str:
    """Convert Reddit JSON API response to simple HTML for build_page."""
    try:
        data = json.loads(raw)
    except Exception:
        return raw

    parts: list[str] = []

    def post_html(post: dict) -> str:
        title = post.get("title", "")
        author = post.get("author", "")
        score = post.get("score", "")
        selftext = post.get("selftext", "")
        link = post.get("url", "")
        permalink = "https://www.reddit.com" + post.get("permalink", "")
        h = f"<h1><a href='{permalink}'>{title}</a></h1>"
        h += f"<p>by u/{author} · {score} points</p>"
        if selftext:
            h += f"<p>{selftext}</p>"
        elif link:
            h += f"<p><a href='{link}'>{link}</a></p>"
        return h

    def comment_html(node: dict, depth: int = 0) -> str:
        if node.get("kind") == "more":
            return ""
        d = node.get("data", node)
        author = d.get("author", "[deleted]")
        body = d.get("body", "")
        score = d.get("score", "")
        tag = f"h{min(depth + 2, 6)}"
        h = f"<{tag}>u/{author} ({score} pts)</{tag}><p>{body}</p>"
        replies = d.get("replies", {})
        if isinstance(replies, dict):
            for child in replies.get("data", {}).get("children", []):
                h += comment_html(child, depth + 1)
        return h

    if isinstance(data, dict) and data.get("kind") == "Listing":
        for child in data.get("data", {}).get("children", []):
            parts.append(post_html(child.get("data", {})))
    elif isinstance(data, list) and len(data) == 2:
        for child in data[0].get("data", {}).get("children", []):
            parts.append(post_html(child.get("data", {})))
        parts.append("<h2>Comments</h2>")
        for child in data[1].get("data", {}).get("children", []):
            parts.append(comment_html(child))

    return "<html><body>" + "\n".join(parts) + "</body></html>" if parts else raw
