"""Classify recoverable transport failures without retrying permanent errors."""

from __future__ import annotations

import re


def is_transient_network_error(detail: str) -> bool:
    # stderr may contain an earlier failed attempt followed by a different
    # terminal error. Decide from the last ERROR block, not stale history.
    errors = list(re.finditer(r"(?:^|\n)\s*ERROR:\s*", detail, re.IGNORECASE))
    terminal = detail[errors[-1].end() :] if errors else detail
    lowered = terminal.casefold()
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
    # Numeric socket errors are stable even when Windows localizes their text.
    if re.search(
        r"\b(?:winerror|errno)\s+(?:10050|10051|10052|10053|10054|10060|10061|10064|10065|11001|11002|1231)\b",
        lowered,
    ):
        return True
    curl_error = re.search(r"\bcurl:\s*\((\d+)\)", lowered)
    if curl_error:
        # Only DNS, connection, timeout and interrupted-transfer errors.
        # In particular, never retry disk writes or certificate failures.
        return int(curl_error[1]) in {5, 6, 7, 16, 18, 28, 52, 55, 56, 92}
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
            "could not resolve host",
            "failed to resolve",
            "failed to establish a new connection",
            "no route to host",
            "nodename nor servname",
            "incomplete read",
            "incompleteread",
            "content too short",
            "bytes missing",
            "did not get any data blocks",
        )
    )
