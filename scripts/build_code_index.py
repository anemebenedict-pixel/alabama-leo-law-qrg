#!/usr/bin/env python3
"""
Alabama LEO Law QRG - GitHub Pages Code Index Builder v2

Builds a static section/catchline index by querying the official Alabama
Legislature Code search endpoint title-by-title, instead of trying to crawl
the JavaScript-rendered table of contents.

The resulting data/code-index.json is used by the GitHub Pages app.
Official statute text is NOT copied into the repository; clicks still open
the controlling section on the Alabama Legislature website.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

BASE = "https://alison.legislature.state.al.us"
SEARCH = BASE + "/code-of-alabama/search"
OUT = Path("data/code-index.json")

# Alabama title numbers in the current Code interface.
TITLES = [
    "1","2","3","4","5","6","7","8","9","10","10A","11","12","13A",
    "14","15","16","17","18","19","20","21","22","23","24","25","26",
    "27","28","29","30","31","32","33","34","35","36","37","38","39",
    "40","41","42","43","44","45"
]

SECTION_RE = re.compile(
    r"^(?P<section>[0-9]+A?(?:-[0-9A-Za-z.]+)+)\b",
    re.I,
)

def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def sort_key(section: str):
    # Natural-ish sort: 13A-6-2 before 13A-6-10.
    return [
        int(p) if p.isdigit() else p.lower()
        for p in re.split(r"([0-9]+)", section)
    ]

def section_from_href(href: str) -> str | None:
    try:
        u = urlparse(urljoin(BASE, href))
        qs = parse_qs(u.query)
        val = qs.get("section", [None])[0]
        if val:
            return val.strip()
    except Exception:
        return None
    return None

def title_of(section: str) -> str:
    m = re.match(r"^([0-9]+A?)", section, re.I)
    return m.group(1).upper() if m else ""

def parse_results(html: str) -> dict[str, dict]:
    """
    Parse all official section links from a server-rendered search-result page.
    Handles both ordinary anchors and raw href fragments.
    """
    found: dict[str, dict] = {}
    soup = BeautifulSoup(html, "html.parser")

    # Primary parse: actual anchors.
    for a in soup.find_all("a", href=True):
        sec = section_from_href(a.get("href", ""))
        if not sec:
            continue
        text = clean(a.get_text(" ", strip=True))

        # Search results usually begin "Section 13A-6-2 Murder."
        catch = text
        catch = re.sub(r"^Section\s+" + re.escape(sec) + r"\s*", "", catch, flags=re.I)
        catch = catch.strip(" .–—-")
        # Search result anchors can include body text. Keep the first sentence-ish
        # portion as the catchline if it is overly long.
        if len(catch) > 220:
            first = re.split(r"(?<=[.?!])\s+", catch, maxsplit=1)[0]
            catch = first[:220].strip()
        if not catch:
            catch = f"Section {sec}"

        found[sec] = {
            "section": sec,
            "title": catch,
            "title_no": title_of(sec),
            "url": f"{BASE}/code-of-alabama?section={sec}",
        }

    # Fallback: raw HTML may contain section query strings even if markup changes.
    for sec in re.findall(r"[?&]section=([0-9]+A?(?:-[0-9A-Za-z.]+)+)", html, flags=re.I):
        sec = sec.strip()
        if sec not in found:
            found[sec] = {
                "section": sec,
                "title": f"Section {sec}",
                "title_no": title_of(sec),
                "url": f"{BASE}/code-of-alabama?section={sec}",
            }

    return found

def fetch(session: requests.Session, query: str, page: int) -> tuple[str, str]:
    r = session.get(
        SEARCH,
        params={"query": query, "page": page},
        timeout=40,
        allow_redirects=True,
    )
    r.raise_for_status()
    return r.text, r.url

def crawl_title(session: requests.Session, title: str) -> dict[str, dict]:
    """
    Search for the title prefix (e.g. "13A-" or "32-") and walk result pages.
    We stop after two consecutive pages return no new section IDs.
    """
    query = f"{title}-"
    sections: dict[str, dict] = {}
    empty_or_duplicate = 0

    for page in range(1, 501):
        html, final_url = fetch(session, query, page)
        parsed = parse_results(html)

        # Keep only sections belonging to this title; full-text search may return
        # cross-references from other titles.
        parsed = {
            sec: row for sec, row in parsed.items()
            if title_of(sec).upper() == title.upper()
        }

        before = len(sections)
        sections.update(parsed)
        added = len(sections) - before

        print(
            f"Title {title:>3} page {page:>3}: "
            f"{len(parsed):>3} parsed, {added:>3} new, {len(sections):>5} total",
            flush=True,
        )

        # Stop when the result set is exhausted. Two pages protects against
        # occasional duplicate-only pagination.
        if added == 0:
            empty_or_duplicate += 1
        else:
            empty_or_duplicate = 0

        # The search page exposes a "No results were found" message.
        if "No results were found" in html:
            break
        if empty_or_duplicate >= 2:
            break

        time.sleep(0.08)

    return sections

def main() -> int:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Alabama-LEO-Law-QRG-GitHub-Indexer/4.1 "
            "(public legal-reference index; GitHub Actions)"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    })

    all_sections: dict[str, dict] = {}
    failures = []

    for title in TITLES:
        try:
            rows = crawl_title(session, title)
            print(f"Finished Title {title}: {len(rows)} unique sections", flush=True)
            all_sections.update(rows)
        except Exception as e:
            failures.append({"title": title, "error": repr(e)})
            print(f"WARNING Title {title} failed: {e!r}", file=sys.stderr, flush=True)

    ordered = sorted(all_sections.values(), key=lambda x: sort_key(x["section"]))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SEARCH,
        "method": "official-search-title-prefix-v2",
        "complete": len(ordered) >= 1000 and len(failures) == 0,
        "count": len(ordered),
        "failed_titles": failures,
        "sections": ordered,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    print(f"\nWrote {len(ordered)} sections to {OUT}", flush=True)

    # Fail only if discovery is clearly broken. Partial indexes with >1000
    # sections are still committed, and the JSON records failed titles.
    if len(ordered) < 1000:
        print(
            "ERROR: Fewer than 1,000 sections were discovered. "
            "The official search-page markup or query behavior likely changed.",
            file=sys.stderr,
        )
        return 2

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
