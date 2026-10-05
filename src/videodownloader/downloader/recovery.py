"""Classify recoverable transport failures without retrying permanent errors."""

from __future__ import annotations

import re


def is_transient_network_error(detail: str) -> bool:
    lowered = detail.casefold()
    permanent = (
        "not a bot",
        "sign in",
        "login",
        "authentication",
        "private video",
        "video unavailable",
        "has been removed",
        "unsupported url",
        "cookies",
        "dpapi",
        "failed to decrypt",
        "permission denied",
        "access is denied",
        "no space left",
        "disk full",
        "not enough space",
        "ffmpeg not found",
    )
    if any(token in lowered for token in permanent):
        return False
    if re.search(r"http (?:error |status )?(?:400|401|403|404|410)\b", lowered):
        return False
    if re.search(r"http (?:error |status )?(?:429|5\d\d)\b", lowered):
        return True
    return any(
        token in lowered
        for token in (
            "timed out",
            "timeout",
            "network is unreachable",
            "network unreachable",
            "network is down",
            "connection reset",
            "connection aborted",
            "connection refused",
            "connection closed",
            "remote end closed",
            "temporary failure in name resolution",
            "name resolution",
            "name or service not known",
            "getaddrinfo failed",
            "unable to resolve",
            "nodename nor servname",
            "incomplete read",
            "incompleteread",
            "content too short",
            "bytes missing",
            "winerror 10051",
            "winerror 10054",
            "winerror 10060",
            "errno 11001",
            "errno 11002",
        )
    )
