"""
Minimal robots.txt handling following RFC 9309.

Python's urllib.robotparser ignores the `*` and `$` wildcards that most
shop robots.txt files use (e.g. `Disallow: /*?filter=`), which would let
us fetch paths a shop has disallowed. This parser supports them and uses
the RFC's longest-match rule (Allow wins on a tie).

Fetch outcome (RFC 9309, section 2.3.1):
  - 2xx          -> parse the rules
  - 4xx          -> no robots.txt, everything allowed
  - 5xx / error  -> treat as "disallow everything" (we stay away)
  - 429          -> rate limited: stay away as well
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[bool, str]] = field(default_factory=list)   # (allow, pattern)


def _pattern_to_regex(pattern: str) -> re.Pattern:
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in pattern)
    return re.compile(rx + ("$" if anchored else ""))


class RobotsRules:
    def __init__(self, text: str | None = None, *, allow_all: bool = False, disallow_all: bool = False,
                 unavailable: str | None = None):
        self.allow_all = allow_all
        self.disallow_all = disallow_all
        # set when robots.txt could not be read (5xx / network error / 429):
        # we stay away, but report it as an error rather than a robots ban
        self.unavailable = unavailable
        self.groups: list[_Group] = []
        self.sitemaps: list[str] = []     # "Sitemap:" lines (apply to all agents)
        if text:
            self._parse(text)

    def _parse(self, text: str) -> None:
        current: _Group | None = None
        last_was_agent = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, value = (p.strip() for p in line.split(":", 1))
            key = key.lower()
            if key == "sitemap":
                if value.startswith(("http://", "https://")) and value not in self.sitemaps:
                    self.sitemaps.append(value)
                continue
            if key == "user-agent":
                if current is None or not last_was_agent:
                    current = _Group()
                    self.groups.append(current)
                current.agents.append(value.lower())
                last_was_agent = True
            elif key in ("allow", "disallow"):
                last_was_agent = False
                if current is None:
                    continue
                if key == "disallow" and value == "":
                    continue          # empty Disallow = allow everything
                current.rules.append((key == "allow", value))
            else:
                last_was_agent = False

    def _rules_for(self, agent: str) -> list[tuple[bool, str]]:
        agent = agent.lower()
        specific = [g for g in self.groups if any(a != "*" and a == agent for a in g.agents)]
        if specific:
            return [r for g in specific for r in g.rules]
        return [r for g in self.groups if "*" in g.agents for r in g.rules]

    def can_fetch(self, agent: str, url: str) -> bool:
        if self.disallow_all:
            return False
        if self.allow_all:
            return True
        parts = urlsplit(url)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        if path == "/robots.txt":
            return True
        best_len, best_allow = -1, True
        for allow, pattern in self._rules_for(agent):
            if not pattern.startswith("/") and not pattern.startswith("*"):
                pattern = "/" + pattern
            if _pattern_to_regex(pattern).match(path):
                length = len(pattern)
                if length > best_len or (length == best_len and allow):
                    best_len, best_allow = length, allow
        return best_allow


def rules_from_response(status: int | None, text: str | None) -> RobotsRules:
    if status is None:
        return RobotsRules(disallow_all=True, unavailable="robots.txt not reachable")
    if status >= 500:
        return RobotsRules(disallow_all=True, unavailable=f"robots.txt returned HTTP {status}")
    if status == 429:
        return RobotsRules(disallow_all=True, unavailable="robots.txt rate limited (HTTP 429)")
    if 400 <= status < 500:
        return RobotsRules(allow_all=True)
    if 200 <= status < 300:
        return RobotsRules(text or "")
    # 3xx that wasn't followed, 1xx: be conservative
    return RobotsRules(disallow_all=True, unavailable=f"robots.txt returned HTTP {status}")
