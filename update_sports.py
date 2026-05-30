#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "sports_sources.json"


@dataclass(frozen=True)
class Candidate:
    target_id: str
    target_name: str
    source_name: str
    extinf: str
    url: str
    score: int
    latency_ms: int | None = None


def candidate_extinf(display_name: str, group_title: str) -> str:
    return f'#EXTINF:-1 tvg-name="{display_name}" group-title="{group_title}",{display_name}'


def fetch_text(url: str, user_agent: str | None = None, timeout: int = 20) -> tuple[str, str | None]:
    headers = {"User-Agent": user_agent or "Mozilla/5.0 APTV-sports-source"}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace"), None
    except urllib.error.URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise

    context = ssl._create_unverified_context()
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return (
            response.read().decode("utf-8", errors="replace"),
            "default certificate verification failed; fetched with unverified TLS context",
        )


def channel_name(extinf: str) -> str:
    if "," in extinf:
        return extinf.rsplit(",", 1)[1].strip()
    match = re.search(r'tvg-name="([^"]+)"', extinf)
    return match.group(1).strip() if match else extinf


def parse_m3u(text: str) -> list[tuple[str, str, str]]:
    items: list[tuple[str, str, str]] = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith("#EXTINF"):
            index += 1
            continue

        probe = index + 1
        while probe < len(lines) and lines[probe].startswith("#"):
            probe += 1
        if probe < len(lines):
            items.append((line, lines[probe], channel_name(line)))
        index = probe + 1
    return items


def parse_existing_source(path: Path) -> list[tuple[str, str, str]]:
    if not path.exists():
        return []
    return parse_m3u(path.read_text(encoding="utf-8", errors="replace"))


def target_for(name: str, extinf: str, targets: list[dict]) -> dict | None:
    haystack = f"{name} {extinf}"
    for target in targets:
        if any(re.search(pattern, haystack, flags=re.IGNORECASE) for pattern in target["patterns"]):
            return target
    return None


def base_score(url: str, name: str, source_name: str) -> int:
    score = 100
    parsed = urlparse(url)
    host = parsed.hostname or ""

    if parsed.scheme == "https":
        score += 8
    if source_name == "manual":
        score += 14
    if source_name == "previous":
        score += 6
    if "zbds" in source_name.lower():
        score += 10
    if host.endswith("epg.pw"):
        score += 8
    if host.endswith("cztv.com") or host.endswith("myalicdn.com"):
        score += 5
    if re.search(r":(80|808|8082|9901|8154)$", parsed.netloc):
        score -= 2
    if "4k" in name.lower() or "8k" in name.lower():
        score -= 25
    if "支持作者" in name or parsed.path.endswith(".mp4"):
        score -= 100
    return score


def probe_stream(url: str, timeout: int) -> tuple[bool, int | None, str | None]:
    headers = {"User-Agent": "Mozilla/5.0 APTV-sports-source"}
    request = urllib.request.Request(url, headers=headers)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return validate_probe_response(url, response, start)
    except urllib.error.URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc) and "self-signed certificate" not in str(exc):
            return False, None, str(exc)
    except (TimeoutError, OSError) as exc:
        return False, None, str(exc)

    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            ok, latency_ms, error = validate_probe_response(url, response, start)
            if ok:
                return True, latency_ms, None
            return False, latency_ms, error
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, None, str(exc)


def validate_probe_response(url: str, response, start: float) -> tuple[bool, int | None, str | None]:
    chunk = response.read(2048)
    latency_ms = int((time.monotonic() - start) * 1000)
    content_type = response.headers.get("Content-Type", "")
    if response.status >= 400:
        return False, latency_ms, f"HTTP {response.status}"
    if b"#EXTM3U" in chunk or b"#EXT-X-" in chunk or "mpegurl" in content_type.lower():
        return True, latency_ms, None
    if url.endswith(".m3u8"):
        return True, latency_ms, None
    return False, latency_ms, "not an m3u8 playlist"


def normalize_extinf(extinf: str, display_name: str, group_title: str, source_name: str, line_no: int) -> str:
    attrs = extinf
    if 'group-title="' in attrs:
        attrs = re.sub(r'group-title="[^"]*"', f'group-title="{group_title}"', attrs)
    else:
        attrs = attrs.replace("#EXTINF:-1", f'#EXTINF:-1 group-title="{group_title}"', 1)
    if 'tvg-name="' not in attrs:
        attrs = attrs.replace("#EXTINF:-1", f'#EXTINF:-1 tvg-name="{display_name}"', 1)
    label = display_name if line_no == 1 else f"{display_name} 线路{line_no}"
    if "," in attrs:
        attrs = attrs.rsplit(",", 1)[0] + f",{label}"
    else:
        attrs = f"{attrs},{label}"
    return attrs


def add_candidate(
    grouped: dict[str, list[Candidate]],
    target: dict,
    source_name: str,
    extinf: str,
    url: str,
    name: str,
    probe_timeout: int,
    report: list[str],
) -> None:
    score = base_score(url, name, source_name)
    if score <= 0:
        return

    ok, latency_ms, error = probe_stream(url, probe_timeout)
    if not ok:
        report.append(f'FAIL {target["name"]} | {name} | {url} | {error}')
        return
    if latency_ms is not None:
        score -= min(latency_ms // 250, 25)
    grouped[target["id"]].append(
        Candidate(target["id"], target["name"], source_name, extinf, url, score, latency_ms)
    )


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    max_lines = int(config.get("max_lines_per_channel", 3))
    min_lines = int(config.get("min_lines_per_channel", 1))
    probe_timeout = int(config.get("probe_timeout_seconds", 6))
    output_path = ROOT / config["output"]
    grouped: dict[str, list[Candidate]] = {target["id"]: [] for target in config["targets"]}
    report: list[str] = []
    warnings: list[str] = []

    for target in config["targets"]:
        for manual in target.get("manual_candidates", []):
            add_candidate(
                grouped,
                target,
                manual.get("source", "manual"),
                candidate_extinf(manual.get("name", target["name"]), config["group_title"]),
                manual["url"],
                manual.get("name", target["name"]),
                probe_timeout,
                report,
            )

    for upstream in config["upstreams"]:
        if upstream.get("enabled", True) is False:
            continue
        try:
            text, warning = fetch_text(upstream["url"], upstream.get("user_agent"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            warnings.append(f'{upstream["name"]}: upstream failed: {exc}')
            continue
        if warning:
            warnings.append(f'{upstream["name"]}: {warning}')

        for extinf, url, name in parse_m3u(text):
            target = target_for(name, extinf, config["targets"])
            if not target:
                continue
            add_candidate(
                grouped,
                target,
                upstream["name"],
                extinf,
                url,
                name,
                probe_timeout,
                report,
            )

    if config.get("keep_previous_when_live", True):
        for extinf, url, name in parse_existing_source(output_path):
            target = target_for(name, extinf, config["targets"])
            if not target:
                continue
            add_candidate(grouped, target, "previous", extinf, url, name, probe_timeout, report)

    lines = [
        f'#EXTM3U x-tvg-url="{config["epg"]}"',
        "# Curated by update_sports.py",
    ]
    kept = 0
    for target in config["targets"]:
        candidates = sorted(
            grouped[target["id"]],
            key=lambda item: (item.score, -(item.latency_ms or 999999)),
            reverse=True,
        )
        seen_urls: set[str] = set()
        selected: list[Candidate] = []
        for candidate in candidates:
            if candidate.url in seen_urls:
                continue
            seen_urls.add(candidate.url)
            selected.append(candidate)
            if len(selected) >= max_lines:
                break

        if len(selected) < min_lines:
            report.append(f'MISS {target["name"]}: no live candidate')
            continue

        for line_no, candidate in enumerate(selected, start=1):
            lines.append(
                normalize_extinf(
                    candidate.extinf,
                    candidate.target_name,
                    config["group_title"],
                    candidate.source_name,
                    line_no,
                )
            )
            lines.append(candidate.url)
            kept += 1
            report.append(
                f'KEEP {candidate.target_name} #{line_no} | score={candidate.score} '
                f'latency={candidate.latency_ms}ms | {candidate.source_name} | {candidate.url}'
            )

    if kept == 0:
        print("没有筛到可用体育频道，保留原文件。", file=sys.stderr)
        return 1

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ROOT / config["report"]).write_text("\n".join(warnings + report) + "\n", encoding="utf-8")
    print(f'写入 {config["output"]}: {kept} 条线路')
    if warnings:
        print("提示：", file=sys.stderr)
        for warning in warnings:
            print(f"- {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
