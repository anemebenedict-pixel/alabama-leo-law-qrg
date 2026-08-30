#!/usr/bin/env python3
from __future__ import annotations
import json, re, time, sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode
import requests
from bs4 import BeautifulSoup

BASE="https://alison.legislature.state.al.us"
START=BASE+"/code-of-alabama"
OUT=Path("data/code-index.json")
SEC_RE=re.compile(r"(?:Section\s+|§\s*)?([0-9]+A?(?:-[0-9A-Za-z.]+)+)",re.I)

def clean(s): return re.sub(r"\s+"," ",s or "").strip()

def canon(url):
    u=urlparse(urljoin(BASE,url))
    if u.netloc!=urlparse(BASE).netloc or u.path.rstrip("/")!="/code-of-alabama": return None
    pairs=[(k,v) for k,v in parse_qsl(u.query,keep_blank_values=True) if k.lower()!="version"]
    seen=set(); kept=[]
    for kv in pairs:
        if kv not in seen: kept.append(kv); seen.add(kv)
    q=urlencode(kept,doseq=True)
    return BASE+"/code-of-alabama"+(("?"+q) if q else "")

def sec_from(href,text):
    u=urlparse(urljoin(BASE,href)); p=dict(parse_qsl(u.query))
    if p.get("section"): return p["section"].strip()
    m=SEC_RE.search(text or "")
    return m.group(1) if m and "Section" in (text or "") else None

def title_no(s):
    m=re.match(r"^([0-9]+A?)",s); return m.group(1) if m else ""

def sortkey(s):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"([0-9]+)",s)]

def main():
    sess=requests.Session()
    sess.headers["User-Agent"]="Alabama-LEO-Law-QRG-GitHub-Indexer/4.0"
    q=deque([START]); visited=set(); sections={}; failures=[]
    while q and len(visited)<25000:
        cu=canon(q.popleft())
        if not cu or cu in visited or "section=" in cu: continue
        visited.add(cu)
        try:
            r=sess.get(cu,timeout=30); r.raise_for_status()
        except Exception as e:
            failures.append({"url":cu,"error":str(e)}); continue
        soup=BeautifulSoup(r.text,"html.parser")
        for a in soup.find_all("a",href=True):
            href=a.get("href",""); txt=clean(a.get_text(" ",strip=True)); absolute=canon(href)
            if not absolute: continue
            sec=sec_from(href,txt)
            if sec:
                title=re.sub(r"^Section\s+"+re.escape(sec)+r"\s*","",txt,flags=re.I).strip(" .–—-") or f"Section {sec}"
                old=sections.get(sec)
                if not old or (old["title"].startswith("Section ") and not title.startswith("Section ")):
                    sections[sec]={"section":sec,"title":title,"title_no":title_no(sec),"url":f"{BASE}/code-of-alabama?section={sec}"}
            elif absolute not in visited:
                q.append(absolute)
        if len(visited)%100==0:
            print(f"Visited {len(visited)} TOC pages; found {len(sections)} sections",flush=True)
        time.sleep(.03)
    ordered=sorted(sections.values(),key=lambda x:sortkey(x["section"]))
    payload={"generated_at":datetime.now(timezone.utc).isoformat(),"source":START,
             "complete":bool(ordered) and not q,"count":len(ordered),
             "navigation_pages_visited":len(visited),"failures":failures[:100],"sections":ordered}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    print(f"Wrote {len(ordered)} sections")
    return 0 if len(ordered)>=1000 else 2

if __name__=="__main__": raise SystemExit(main())
