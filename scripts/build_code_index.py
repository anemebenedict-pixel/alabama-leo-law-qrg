#!/usr/bin/env python3
"""
Alabama Code static index builder for the Alabama LEO Law QRG.

Why Playwright:
The Alabama Legislature Code site renders its table of contents in the browser.
Plain requests/BeautifulSoup sees the shell but not the Code tree. This builder
uses Chromium, reads the rendered table of contents, and recursively follows the
first section shown for each chapter/article/part range.

It stores ONLY section numbers, catchlines, and official URLs. The controlling
statutory text remains on the Alabama Legislature website.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

BASE = "https://alison.legislature.state.al.us"
CODE = BASE + "/code-of-alabama"
OUT = Path("data/code-index.json")

# Alabama Code title identifiers.
TITLES = [
    "1","2","3","4","5","6","7","8","9","10","10A","11","12","13A",
    "14","15","16","17","18","19","20","21","22","23","24","25","26",
    "27","28","29","30","31","32","33","34","35","36","37","38","39",
    "40","41","42","43","44","45"
]

# Common first-section guesses. Most titles use X-1-1. 10A is structured
# differently, so several fallbacks are attempted automatically.
SEED_SUFFIXES = [
    "1-1", "1-1.01", "1-1.1", "1-101", "1-101.1", "1-1-1"
]

SECTION_LINE_RE = re.compile(
    r"^\s*Section\s+([0-9]+A?(?:-[0-9A-Za-z.]+)+)\s*(.*?)\s*$",
    re.I,
)
RANGE_RE = re.compile(
    r"\(§\s*([0-9]+A?(?:-[0-9A-Za-z.]+)+)\s+to\s+§\s*"
    r"([0-9]+A?(?:-[0-9A-Za-z.]+)+)\)",
    re.I,
)
ANY_SECTION_RE = re.compile(
    r"\b§\s*([0-9]+A?(?:-[0-9A-Za-z.]+)+)\b",
    re.I,
)

def title_of(section: str) -> str:
    m = re.match(r"^([0-9]+A?)", section, re.I)
    return m.group(1).upper() if m else ""

def normalize_section(section: str) -> str:
    return section.strip().rstrip(".,;:").upper()

def natural_key(value: str):
    parts = re.split(r"(\d+)", value)
    return [int(p) if p.isdigit() else p.lower() for p in parts]

def clean_catchline(text: str, section: str) -> str:
    s = re.sub(r"\s+", " ", text or "").strip()
    s = re.sub(r"^\[Effective\b.*?\]\s*", "", s, flags=re.I)
    if not s:
        return f"Section {section}"
    return s[:500]

async def rendered_text(page, section: str | None = None) -> str:
    url = CODE if not section else f"{CODE}?section={quote(section)}"
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)

    # The SPA may still be hydrating after DOMContentLoaded.
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except PlaywrightTimeoutError:
        pass

    # Wait specifically for the Code UI if possible, but do not fail solely
    # because its exact markup changed.
    try:
        await page.get_by_text("Code of Alabama", exact=True).first.wait_for(timeout=8000)
    except Exception:
        pass

    await page.wait_for_timeout(500)
    return await page.locator("body").inner_text(timeout=20000)

def parse_page(text: str):
    sections: dict[str, str] = {}
    starts: set[str] = set()

    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue

        m = SECTION_LINE_RE.match(line)
        if m:
            sec = normalize_section(m.group(1))
            catch = clean_catchline(m.group(2), sec)
            sections[sec] = catch

        for rm in RANGE_RE.finditer(line):
            starts.add(normalize_section(rm.group(1)))

    # Some pages expose standalone section symbols outside "Section ..." lines.
    # They are useful as navigation seeds, but not as catchlines.
    for sec in ANY_SECTION_RE.findall(text):
        sec = normalize_section(sec)
        if sec.count("-") >= 2:
            starts.add(sec)

    return sections, starts

async def find_title_seed(page, title: str):
    # Try conventional first-section forms until the rendered page actually
    # identifies itself as belonging to the requested title.
    for suffix in SEED_SUFFIXES:
        candidate = f"{title}-{suffix}"
        try:
            text = await rendered_text(page, candidate)
        except Exception as exc:
            print(f"  seed {candidate}: navigation error: {exc}", flush=True)
            continue

        # A valid section page normally shows "Title <n>" and section/chapter data.
        if re.search(rf"\bTitle\s+{re.escape(title)}\b", text, re.I):
            sections, starts = parse_page(text)
            if sections or starts:
                return candidate, text

    return None, ""

async def main() -> int:
    all_sections: dict[str, dict] = {}
    queued: set[str] = set()
    visited: set[str] = set()
    failed_titles: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128 Safari/537.36 "
                "Alabama-LEO-Law-QRG-Indexer/5.0"
            ),
            viewport={"width": 1440, "height": 1200},
        )
        page = await context.new_page()

        # Reduce bandwidth and speed up thousands of rendered TOC requests.
        async def route_handler(route):
            if route.request.resource_type in {"image", "media", "font"}:
                await route.abort()
            else:
                await route.continue_()
        await page.route("**/*", route_handler)

        queue = deque()

        # Seed every title.
        for title in TITLES:
            print(f"\nFinding seed for Title {title}...", flush=True)
            try:
                seed, text = await find_title_seed(page, title)
            except Exception as exc:
                seed, text = None, ""
                print(f"  title seed error: {exc!r}", file=sys.stderr, flush=True)

            if not seed:
                failed_titles.append({"title": title, "reason": "no valid seed found"})
                print(f"WARNING: no valid starting section found for Title {title}", file=sys.stderr, flush=True)
                continue

            print(f"  seed = {seed}", flush=True)
            sections, starts = parse_page(text)

            for sec, catch in sections.items():
                all_sections[sec] = {
                    "section": sec,
                    "title": catch,
                    "title_no": title_of(sec),
                    "url": f"{CODE}?section={sec}",
                }

            # Queue the seed itself and all hierarchy-range starts discovered.
            for sec in {seed, *starts}:
                sec = normalize_section(sec)
                if sec not in queued:
                    queued.add(sec)
                    queue.append(sec)

        # Recursive rendered-TOC discovery.
        consecutive_failures = 0
        max_pages = 12000

        while queue and len(visited) < max_pages:
            sec = queue.popleft()
            if sec in visited:
                continue
            visited.add(sec)

            try:
                text = await rendered_text(page, sec)
                parsed, starts = parse_page(text)
                consecutive_failures = 0
            except Exception as exc:
                print(f"WARNING {sec}: {exc!r}", file=sys.stderr, flush=True)
                consecutive_failures += 1
                if consecutive_failures >= 25:
                    print("ERROR: 25 consecutive page failures; aborting.", file=sys.stderr)
                    break
                continue

            before = len(all_sections)
            for found_sec, catch in parsed.items():
                all_sections[found_sec] = {
                    "section": found_sec,
                    "title": catch,
                    "title_no": title_of(found_sec),
                    "url": f"{CODE}?section={found_sec}",
                }

            for child in starts:
                child = normalize_section(child)
                if child not in visited and child not in queued:
                    queued.add(child)
                    queue.append(child)

            added = len(all_sections) - before
            if len(visited) % 10 == 0 or added:
                print(
                    f"[{len(visited):>5} pages] {sec:<18} "
                    f"+{added:<3} sections | total={len(all_sections):>6} | "
                    f"queue={len(queue):>5}",
                    flush=True,
                )

        await browser.close()

    rows = sorted(all_sections.values(), key=lambda x: natural_key(x["section"]))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": CODE,
        "method": "playwright-rendered-hierarchy-v1",
        "count": len(rows),
        "complete": len(rows) >= 1000 and not failed_titles,
        "failed_titles": failed_titles,
        "sections": rows,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    print(f"\nWrote {len(rows)} sections to {OUT}", flush=True)
    print(f"Visited {len(visited)} rendered hierarchy pages.", flush=True)

    # A real Alabama Code index should be far larger than the QRG seed data.
    # This threshold detects a broken renderer without requiring an exact count.
    if len(rows) < 1000:
        print(
            "ERROR: fewer than 1,000 sections were discovered. "
            "The rendered hierarchy could not be indexed reliably.",
            file=sys.stderr,
        )
        return 2

    return 0

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
