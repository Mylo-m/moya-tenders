#!/usr/bin/env python3
"""
Moya — Multi-Country Local Scraper (source of truth)
Runs on the MY-LO box, scrapes African tender portals, writes moya_data/moya.db.
A separate sync step (sync_tenders.sh) FTP-uploads the DB to the live host.

Countries supported:
  ZA  South Africa  — eTenders (national, www.etenders.gov.za), OCPO (transversal SOE)
  KE  Kenya         — PPIP official portal (tenders.go.ke /api/tender) + e-GP Kenya probe

IMPORTANT (2026-08-24):
  - etenders.treasury.gov.za is DEAD (404). Live portal: www.etenders.gov.za.
  - eTenders JSON dumps the FULL ~172MB archive. We CACHE it locally (24h TTL) and
    filter to recent OPEN tenders in Python (matches the SA-tender-monitoring skill).
  - e-GP Kenya (egpkenya.go.ke) is an Angular SPA; its /api/tender/common/ajax is
    session-gated. We PROBE it defensively — if it returns nothing, we skip silently
    and rely on PPIP. No 300s limit here (local only).

Run:  python3 scraper_sqlite.py
Cron: every 6h via the Hermes scheduled job.
"""

import os
import re
import json
import gzip
import hashlib
import sqlite3
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'moya.db')
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.cache')
ETENDERS_CACHE = os.path.join(CACHE_DIR, 'za_etenders.json')
ETENDERS_TTL = 24 * 3600  # seconds

UA = "Mozilla/5.0 (compatible; TenderMoya/1.0)"

# ---------------------------------------------------------------------------
# Sector keyword map (shared with scrape.php — keep identical)
# ---------------------------------------------------------------------------
SECTOR_KEYWORDS = {
    "construction": ["building", "construction", "civil", "roads", "infrastructure", "renovation", "maintenance"],
    "ict": ["ict", "software", "hardware", "network", "cyber", "cybersecurity", "cloud", "server", "database system", "erp", "application development", "it ", "digital", "data"],
    "medical": ["medical", "health", "hospital", "clinic", "pharmaceutical", "ppe", "ambulance"],
    "security": ["security", "guarding", "cctv", "access control", "armed response", "surveillance"],
    "logistics": ["transport", "logistics", "freight", "courier", "fleet", "delivery", "warehousing"],
    "education": ["education", "school", "training", "learnership", "seta", "curriculum", "e-learning"],
    "energy": ["energy", "electrical", "solar", "power", "renewable", "generator", "eskom"],
    "agriculture": ["agriculture", "farming", "livestock", "crop", "agri", "food processing", "foodstuffs"],
    "consulting": ["consulting", "advisory", "professional services", "feasibility", "strategy"],
    "marketing": ["marketing", "advertising", "branding", "communications", "pr", "media"],
    "cleaning": ["cleaning", "hygiene", "sanitation", "waste", "facilities", "pest control"],
    "legal": ["legal", "attorney", "conveyancing", "litigation", "law", "paralegal", "notary"],
    "financial": ["financial", "accounting", "audit", "tax", "bookkeeping", "payroll"],
    "property": ["property", "real estate", "facility management", "valuator"],
    "mining": ["mining", "drilling", "geological", "mineral", "petroleum", "quarry"],
    "manufacturing": ["manufacturing", "production", "assembly", "fabrication", "engineering"],
    "retail": ["retail", "supply", "procurement", "wholesale", "consumer goods"],
    "hospitality": ["hospitality", "catering", "hotel", "restaurant", "tourism", "events"],
    "printing": ["printing", "print", "stationery", "signage"],
    "hr": ["human resource", "recruitment", "staffing", "personnel", "temp", "placement"],
    "environmental": ["environmental", "waste management", "recycling", "sustainability", "green"],
    "insurance": ["insurance", "broker", "underwriting", "risk", "claims"],
    "telecoms": ["telecoms", "telecommunications", "voip", "connectivity", "broadband", "5g"],
    "aviation": ["aviation", "airport", "airline", "aeronautical", "cargo handling"],
    "maritime": ["maritime", "port", "shipping", "marine", "fisheries"],
    "defence": ["defence", "military", "army", "force", "mod", "dod"],
    "research": ["research", "survey", "study", "data collection", "market research", "census"],
    "arts": ["arts", "culture", "heritage", "museum", "library", "archive"],
    "sports": ["sports", "recreation", "fitness", "gym", "stadium"],
}

COUNTRY_REGIONS = {
    "ZA": "Southern Africa",
    "KE": "East Africa",
    "NG": "West Africa",
    "ET": "East Africa",
    "UG": "East Africa",
    "GH": "West Africa",
    "TZ": "East Africa",
    "ZM": "Southern Africa",
    "MW": "Southern Africa",
    "RW": "East Africa",
    "MZ": "Southern Africa",
    "ZW": "Southern Africa",
    "MA": "North Africa",
    "MU": "East Africa",
    "BW": "Southern Africa",
    "SC": "East Africa",
    "EG": "North Africa",
}


def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def ensure_tables():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS tenders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            source_key TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            issuing_dept TEXT,
            sector TEXT,
            province TEXT,
            country TEXT,
            country_code TEXT,
            region TEXT,
            advert_date TEXT,
            closing_date TEXT,
            status TEXT DEFAULT 'open',
            contact_person TEXT,
            contact_email TEXT,
            contact_phone TEXT,
            document_url TEXT,
            source_url TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_tenders_sector ON tenders(sector);
        CREATE INDEX IF NOT EXISTS idx_tenders_province ON tenders(province);
        CREATE INDEX IF NOT EXISTS idx_tenders_closing ON tenders(closing_date);
        CREATE INDEX IF NOT EXISTS idx_tenders_status ON tenders(status);
        CREATE INDEX IF NOT EXISTS idx_tenders_country ON tenders(country_code);
        CREATE TABLE IF NOT EXISTS scrape_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            country TEXT,
            tenders_found INTEGER,
            tenders_saved INTEGER,
            status TEXT,
            error TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    # Backfill scrape_log.country if the column was added by an older CREATE without it
    try:
        c = db.execute("PRAGMA table_info(scrape_log)").fetchall()
        if all('country' != row[1] for row in c):
            db.execute("ALTER TABLE scrape_log ADD COLUMN country TEXT")
    except Exception:
        pass
    # Backfill existing rows (SA legacy) with country metadata
    db.execute("UPDATE tenders SET country='South Africa', country_code='ZA', region='Southern Africa' WHERE country IS NULL OR country=''")
    db.commit()
    db.close()


def make_source_key(country_code, source, url):
    return hashlib.sha256(f"{country_code}:{source}:{url}".encode()).hexdigest()[:16]


def extract_sector(text):
    if not text:
        return None
    text_lower = text.lower()
    matches = {}
    for sector, keywords in SECTOR_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in text_lower)
        if count > 0:
            matches[sector] = count
    if matches:
        return max(matches.items(), key=lambda x: x[1])[0]
    return None


def http_get(url, headers=None, timeout=40):
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    # Wall-clock hard cap: urllib3's read timeout can be defeated by a server
    # that trickles/holds the connection open, so enforce a real deadline via a
    # thread. On expiry we raise Timeout and LEAVE the hung thread running
    # (we must not join/wait on it, or we'd block forever).
    import concurrent.futures as _cf
    hard = min(timeout * 2, 40)  # wall-clock cap: fail fast, never exceed 40s
    _ex = _cf.ThreadPoolExecutor(max_workers=1)
    _fut = _ex.submit(requests.get, url, headers=h, timeout=timeout)
    try:
        _r = _fut.result(timeout=hard)
        _ex.shutdown(wait=False)
        return _r
    except _cf.TimeoutError:
        raise requests.exceptions.Timeout(f"hard wall-clock timeout ({hard}s) on {url}")


DATE_PATTERNS = [
    (r'(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})', '%d %B %Y'),
    (r'(\d{4})-(\d{2})-(\d{2})', '%Y-%m-%d'),
    (r'(\d{2})/(\d{2})/(\d{4})', '%d/%m/%Y'),
    (r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})', '%d %b %Y'),
]


def extract_dates(text):
    if not text:
        return None, None
    found = []
    for pattern, fmt in DATE_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            try:
                found.append(datetime.strptime(m.group(0), fmt).date())
            except ValueError:
                continue
    if len(found) >= 2:
        return min(found).isoformat(), max(found).isoformat()
    elif len(found) == 1:
        return found[0].isoformat(), None
    return None, None


def log_scrape(source, country, found, saved, status, error=""):
    db = get_db()
    db.execute(
        "INSERT INTO scrape_log (source, country, tenders_found, tenders_saved, status, error) VALUES (?,?,?,?,?,?)",
        (source, country, found, saved, status, error),
    )
    db.commit()
    db.close()


# ===========================================================================
# SOUTH AFRICA — eTenders national (www.etenders.gov.za) with local cache
# ===========================================================================
def _load_etenders_cached():
    os.makedirs(CACHE_DIR, exist_ok=True)
    now = time.time()
    if os.path.exists(ETENDERS_CACHE) and (now - os.path.getmtime(ETENDERS_CACHE)) < ETENDERS_TTL:
        try:
            with open(ETENDERS_CACHE) as f:
                return json.load(f), True  # (data, from_cache)
        except Exception:
            pass
    url = "https://www.etenders.gov.za/Home/TenderOpportunities?status=Published"
    resp = http_get(url, headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}, timeout=180)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):
        data = data.get("data") or data.get("aaData") or []
    with open(ETENDERS_CACHE, "w") as f:
        json.dump(data, f)
    return data, False


def scrape_sa_etenders(max_records=500, only_recent_days=400):
    """National Treasury eTenders via cached full archive, filtered to recent OPEN."""
    tenders = []
    try:
        data, from_cache = _load_etenders_cached()
        if isinstance(data, dict):
            data = data.get("data") or data.get("aaData") or []
        scanned = len(data)
        now = datetime.now()
        cutoff = now - timedelta(days=only_recent_days)
        kept = 0
        for r in data:
            status = (r.get("status") or "").lower()
            closing = r.get("closing_Date") or r.get("closing_date") or ""
            # parse closing date best-effort
            cdate = None
            m = re.search(r"(\d{4}-\d{2}-\d{2})", closing or "")
            if m:
                try:
                    cdate = datetime.strptime(m.group(1), "%Y-%m-%d")
                except ValueError:
                    cdate = None
            # keep only recent + not clearly closed
            if cdate and cdate < cutoff:
                continue
            if status in ("closed", "awarded", "cancelled", "withdrawal", "hidden", "expired"):
                continue
            prov = r.get("province") or (r.get("provinces") or {}).get("name") or "National"
            title = r.get("description") or r.get("title") or ""
            if len(title) < 8:
                continue
            tenders.append({
                "source": "za_etenders",
                "source_key": make_source_key("ZA", "za_etenders", str(r.get("ocid") or r.get("id") or r.get("tender_No"))),
                "title": title,
                "description": "",
                "issuing_dept": r.get("organ_of_State") or r.get("department") or "",
                "sector": extract_sector(title + " " + (r.get("category") or "")),
                "province": prov,
                "country": "South Africa",
                "country_code": "ZA",
                "region": "Southern Africa",
                "advert_date": (r.get("date_Published") or "")[:10],
                "closing_date": (closing or "")[:19],
                "status": "open" if status in ("open", "published", "advertised", "active") else "closed",
                "contact_person": (r.get("contactPerson") or "")[:120],
                "contact_email": r.get("email") or "",
                "contact_phone": (r.get("telephone") or "")[:60],
                "document_url": "",
                "source_url": "https://www.etenders.gov.za/Home/opportunities?id=1",
            })
            kept += 1
            if kept >= max_records:
                break
        print(f"  za_etenders: kept {len(tenders)} (scanned {scanned}, cache={'hit' if from_cache else 'miss'})")
    except Exception as e:
        print(f"  za_etenders: FAILED - {e}")
        log_scrape("za_etenders", "ZA", 0, 0, "error", str(e)[:200])
        return []
    log_scrape("za_etenders", "ZA", len(tenders), 0, "ok")
    return tenders


# ===========================================================================
# SOUTH AFRICA — OCPO transversal tenders (National Treasury HTML tables)
# ===========================================================================
def scrape_sa_ocpo(max_records=200):
    """Office of the Chief Procurement Officer — Current Tenders (server-rendered HTML).
    Real tenders live in tables #3/#4 as single-cell 'Tender Info - ...' blocks."""
    url = "https://www.treasury.gov.za/divisions/ocpo/ostb/CurrentTenders.aspx"
    tenders = []
    try:
        resp = http_get(url, timeout=40)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        tables = soup.find_all("table")
        if len(tables) < 5:
            raise RuntimeError(f"OCPO: expected >=5 tables, got {len(tables)}")
        no_re = re.compile(r"(RT\d+[-\/]\d{4})[:\s]*(.*?)(?=Published date|Closing Date|$)", re.IGNORECASE | re.DOTALL)
        date_re = re.compile(r"Published date:\s*([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4}).*?Closing Date:\s*([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})", re.IGNORECASE)
        for tb in (tables[3], tables[4]):
            for row in tb.find_all("tr"):
                cell = row.find_all("td")
                text = " ".join(c.get_text(" ", strip=True) for c in cell)
                if "E-Tenders" not in text or "Closing Date" not in text:
                    continue
                mno = re.search(r"(RT\d+[-\/]\d{4})", text)
                dm = date_re.search(text)
                if not mno:
                    continue
                # title = text after the tender number up to 'Published date'
                title_raw = text.split(mno.group(1), 1)[-1]
                title = re.split(r"Published date", title_raw, flags=re.IGNORECASE)[0].strip(" :-\t")
                title = re.sub(r"\s+", " ", title)[:300]
                if len(title) < 8:
                    continue
                adv = cls = None
                if dm:
                    try:
                        adv = datetime.strptime(dm.group(1), "%d %B %Y").date().isoformat()
                        cls = datetime.strptime(dm.group(2), "%d %B %Y").date().isoformat()
                    except ValueError:
                        pass
                tenders.append({
                    "source": "za_ocpo",
                    "source_key": make_source_key("ZA", "za_ocpo", mno.group(1)),
                    "title": (mno.group(1) + ": " + title)[:300],
                    "description": "",
                    "issuing_dept": "National Treasury — OCPO",
                    "sector": extract_sector(title),
                    "province": "National",
                    "country": "South Africa",
                    "country_code": "ZA",
                    "region": "Southern Africa",
                    "advert_date": adv,
                    "closing_date": cls,
                    "status": "open",
                    "document_url": "https://www.etenders.gov.za",
                    "source_url": url,
                })
                if len(tenders) >= max_records:
                    break
            if len(tenders) >= max_records:
                break
        print(f"  za_ocpo: found {len(tenders)}")
    except Exception as e:
        print(f"  za_ocpo: FAILED - {e}")
        log_scrape("za_ocpo", "ZA", 0, 0, "error", str(e)[:200])
        return []
    log_scrape("za_ocpo", "ZA", len(tenders), 0, "ok")
    return tenders


# ===========================================================================
# KENYA — PPIP official portal (tenders.go.ke /api/tender)  [VERIFIED WORKING]
# ===========================================================================
def scrape_ke_ppip(max_pages=2000):
    """Kenya Public Procurement Information Portal (PPIP).
    GET https://tenders.go.ke/api/tender?page=N&status_id=1  (status_id=1 = open)
    Paginated, 10/page. ~143k records total; we walk pages until empty."""
    base = "https://tenders.go.ke/api/tender"
    base2 = "https://tenders.go.ke/api/tender"
    tenders = []
    page = 1
    seen = 0
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}
    try:
        while page <= max_pages:
            try:
                resp = requests.get(base2, params={"page": page, "status_id": 1}, headers=headers, timeout=30)
            except Exception as e:
                print(f"  ke_ppip: page {page} request failed ({e}); stopping KE PPIP crawl (kept {len(tenders)})")
                break
            if resp.status_code != 200:
                break
            try:
                data = resp.json()
            except Exception:
                break
            rows = data.get("data") or []
            if not rows:
                break
            for r in rows:
                pe = r.get("pe") or {}
                pe_name = pe.get("name") or ""
                title = r.get("title") or ""
                if len(title) < 5:
                    continue
                docs = r.get("documents") or []
                doc_url = ""
                if docs:
                    du = docs[0].get("url") or ""
                    if du:
                        doc_url = "https://tenders.go.ke" + du if du.startswith("/") else du
                tenders.append({
                    "source": "ke_ppip",
                    "source_key": make_source_key("KE", "ke_ppip", str(r.get("ocid") or r.get("id"))),
                    "title": title,
                    "description": r.get("description") or "",
                    "issuing_dept": pe_name,
                    "sector": extract_sector(title + " " + (r.get("procurement_category") or {}).get("title", "")),
                    "province": (r.get("county_ministry") or {}).get("name") if r.get("county_ministry") else "",
                    "country": "Kenya",
                    "country_code": "KE",
                    "region": "East Africa",
                    "advert_date": (r.get("published_at") or "")[:10],
                    "closing_date": (r.get("close_at") or "")[:19],
                    "status": "open" if r.get("terminated") in (0, None, False) else "closed",
                    "document_url": doc_url,
                    "source_url": "https://tenders.go.ke/tenders",
                })
            seen += len(rows)
            if page % 50 == 0:
                print(f"  ke_ppip: page {page}, {seen} scanned, {len(tenders)} kept")
            page += 1
        print(f"  ke_ppip: total {len(tenders)} tenders (scanned {seen})")
    except Exception as e:
        print(f"  ke_ppip: FAILED - {e}")
        log_scrape("ke_ppip", "KE", 0, 0, "error", str(e)[:200])
        return []
    log_scrape("ke_ppip", "KE", len(tenders), 0, "ok")
    return tenders


# ===========================================================================
# KENYA — e-GP Kenya (egpkenya.go.ke)  [PROBE ONLY; session-gated, best-effort]
# ===========================================================================
def scrape_ke_egp(max_records=100):
    """e-GP Kenya is an Angular SPA. Public /api/tender/common/ajax is session-gated
    and returns empty without auth. We probe a couple of common action payloads;
    if nothing comes back we skip gracefully and rely on PPIP."""
    tenders = []
    try:
        url = "https://egpkenya.go.ke/api/tender/common/ajax"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                   "Content-Type": "application/json", "Accept": "application/json"}
        payloads = [
            {"action": "searchTender", "page": 1, "size": 10},
            {"action": "getPublishedTenders", "page": 1},
            {"action": "listTenders", "status": "open"},
        ]
        got = None
        for p in payloads:
            try:
                resp = requests.post(url, json=p, headers=headers, timeout=20)
                if resp.status_code == 200 and resp.text.strip():
                    try:
                        j = resp.json()
                        if isinstance(j, (list, dict)) and j:
                            got = j
                            break
                    except Exception:
                        pass
            except Exception:
                continue
        if not got:
            print("  ke_egp: no public feed available (session-gated) — skipped, PPIP covers KE")
            log_scrape("ke_egp", "KE", 0, 0, "skipped", "session-gated")
            return []
        # If we ever get data, map it here (defensive placeholder)
        rows = got if isinstance(got, list) else got.get("data") or []
        for r in rows[:max_records]:
            tenders.append({
                "source": "ke_egp",
                "source_key": make_source_key("KE", "ke_egp", str(r.get("id") or r.get("tenderNo") or r.get("referenceNo"))),
                "title": r.get("title") or r.get("tenderName") or "",
                "description": "",
                "issuing_dept": r.get("procuringEntity") or r.get("pe") or "",
                "sector": extract_sector(r.get("title") or ""),
                "province": r.get("county") or "",
                "country": "Kenya",
                "country_code": "KE",
                "region": "East Africa",
                "advert_date": (r.get("publishedDate") or "")[:10],
                "closing_date": (r.get("closingDate") or "")[:19],
                "status": "open",
                "document_url": "",
                "source_url": "https://egpkenya.go.ke/",
            })
        print(f"  ke_egp: found {len(tenders)} (PROBE)")
    except Exception as e:
        print(f"  ke_egp: FAILED - {e}")
        log_scrape("ke_egp", "KE", 0, 0, "error", str(e)[:200])
        return []
    log_scrape("ke_egp", "KE", len(tenders), 0, "ok")
    return tenders


def save_tenders(tenders):
    if not tenders:
        return 0
    db = get_db()
    saved = 0
    for t in tenders:
        try:
            cur = db.execute(
                """INSERT OR IGNORE INTO tenders
                   (source, source_key, title, description, issuing_dept, sector, province,
                    country, country_code, region, advert_date, closing_date, status,
                    contact_person, contact_email, contact_phone, document_url, source_url)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (t["source"], t["source_key"], t["title"], t["description"], t["issuing_dept"],
                 t["sector"], t["province"], t["country"], t["country_code"], t["region"],
                 t["advert_date"], t["closing_date"], t["status"], t.get("contact_person", ""),
                 t.get("contact_email", ""), t.get("contact_phone", ""), t.get("document_url", ""),
                 t["source_url"]),
            )
            if cur.rowcount:
                saved += 1
        except Exception as e:
            print(f"    save error: {e}")
    db.commit()
    db.close()
    return saved


# ===========================================================================
# NIGERIA — NOCOPO / BPP OCDS JSON (OCP publication 64)
# ===========================================================================
# OCDS release records carry:
#   r['date']          — release timestamp (ISO)
#   r['buyer']['name'] — procuring entity
#   r['tender']['title']     — tender title
#   r['tender']['status']    — planned / active / complete / cancelled ...
#   r['tender']['value']     — {amount, currency}  (NGN)
#   r['tender']['items']     — list; items[0]['description'] = scope
#   r['ocid']                — unique tender ID
# Source: https://nocopo.bpp.gov.ng  · OCP mirror: publication 64
# ===========================================================================

_MOYA_CACHE = os.path.join(CACHE_DIR, 'moya_ocds')
NG_YEARS = [2026, 2025, 2024]
NG_OCP_PUB = 64
NG_STATUS_MAP = {
    "planned": "open",
    "active": "open",
    "published": "open",
    "advertised": "open",
    "draft": "open",
    "complete": "closed",
    "cancelled": "closed",
    "withdrawn": "closed",
    "unsuccessful": "closed",
    "deleted": "closed",
}


def _download_ocds_year(country_code, year, ocp_pub, max_bytes=500 * 1024 * 1024):
    """Download + decompress a single OCDS year file, return list of parsed JSON records.
    Caches the decompressed JSONL locally inside CACHE_DIR/moya_ocds/<cc>_<year>.jsonl
    (24h TTL). Returns (records, downloaded_now_bool)."""
    os.makedirs(_MOYA_CACHE, exist_ok=True)
    cache_file = os.path.join(_MOYA_CACHE, f"{country_code}_{year}.jsonl")
    now = time.time()
    if os.path.exists(cache_file) and (now - os.path.getmtime(cache_file)) < ETENDERS_TTL:
        try:
            with open(cache_file) as f:
                lines = [json.loads(line) for line in f if line.strip()]
            return lines, True
        except Exception:
            pass
    url = f"https://data.open-contracting.org/en/publication/{ocp_pub}/download?name={year}.jsonl.gz"
    print(f"    downloading {year} from OCP (pub {ocp_pub}) ...")
    resp = http_get(url, timeout=180)
    resp.raise_for_status()
    raw = resp.content
    if not raw[:2] == b"\x1f\x8b":
        raise RuntimeError(f"expected gzip, got {len(raw)} bytes")
    text = gzip.decompress(raw).decode("utf-8", errors="replace")
    lines = [json.loads(line) for line in text.splitlines() if line.strip()]
    # cap cached file size
    with open(cache_file, "w") as f:
        for line in text.splitlines():
            if line.strip():
                f.write(line + "\n")
    return lines, False


def scrape_ng_ocds(max_records=2000):
    """Nigeria NOCOPO via OCP OCDS yearly releases. Filters to records with a
    tender.title, status != closed, recent release date."""
    tenders = []
    total_scanned = 0
    for year in NG_YEARS:
        if len(tenders) >= max_records:
            break
        try:
            records, from_cache = _download_ocds_year("NG", year, NG_OCP_PUB)
            print(f"    NG {year}: {len(records)} records (cache={'hit' if from_cache else 'miss'})")
        except Exception as e:
            print(f"    NG {year}: FAILED - {e}")
            log_scrape("ng_ocds", "NG", 0, 0, "error", str(e)[:200])
            continue
        scanned_this_year = 0
        for r in records:
            if len(tenders) >= max_records:
                break
            total_scanned += 1
            scanned_this_year += 1
            t = r.get("tender") or {}
            title = t.get("title") or ""
            if not title or len(title) < 5:
                continue
            status_raw = (t.get("status") or "").lower()
            status = NG_STATUS_MAP.get(status_raw, "open")
            # skip clear closes
            if status == "closed":
                continue
            buyer = r.get("buyer") or {}
            buyer_name = buyer.get("name") or ""
            release_date = r.get("date") or ""
            adv = release_date[:10] if release_date else None
            value = t.get("value") or {}
            amount = value.get("amount")
            currency = value.get("currency", "NGN")
            items = t.get("items") or []
            item_desc = ""
            if items:
                item_desc = (items[0].get("description") or "")[:300]
            description = item_desc or t.get("description") or ""
            text_for_sector = f"{title} {description} {item_desc}"
            plan = r.get("planning") or {}
            budget = (plan.get("budget") or {}).get("amount") or {}
            budget_amount = budget.get("amount")
            bid_amount = amount if (amount and amount > 0) else budget_amount
            tenders.append({
                "source": "ng_ocds",
                "source_key": make_source_key("NG", "ng_ocds", r.get("ocid") or ""),
                "title": title[:500],
                "description": description[:1000],
                "issuing_dept": buyer_name[:300],
                "sector": extract_sector(text_for_sector),
                "province": "",
                "country": "Nigeria",
                "country_code": "NG",
                "region": "West Africa",
                "advert_date": adv,
                "closing_date": None,
                "status": status,
                "contact_person": "",
                "contact_email": "",
                "contact_phone": "",
                "document_url": "",
                "source_url": f"https://nocopo.bpp.gov.ng/opportunities/ocid/{r.get('ocid') or ''}",
            })
            if scanned_this_year % 5000 == 0 and scanned_this_year > 0:
                print(f"    NG {year}: scanned {scanned_this_year}, kept {len(tenders)}")
        print(f"    NG {year}: kept {len(tenders)} so far (scanned {scanned_this_year})")
    print(f"  ng_ocds: total {len(tenders)} tenders (scanned {total_scanned})")
    log_scrape("ng_ocds", "NG", total_scanned, len(tenders), "ok")
    return tenders


# ===========================================================================
# ZAMBIA — ZPPA e-GP OCDS JSON (OCP publication 3)
# ===========================================================================
# Same OCDS shape as Nigeria. Source: https://www.zppa.org.zm/  · OCP pub 3
# ===========================================================================

ZM_YEARS = [2026, 2025, 2024]
ZM_OCP_PUB = 3
ZM_STATUS_MAP = dict(NG_STATUS_MAP)


# ===========================================================================
# TANZANIA — NeST OCDS API (data.nest.go.tz / gateway)
# ===========================================================================
# API: https://nest.go.tz/gateway/nest-data-portal-api/api/releases
# Paginated, 50/page, cursor-based. Release shape:
#   ocid, buyer.name, date, tender.id, tender.description, tender.status,
#   tender.procurementMethod, tender.procuringEntity, tender.items
# NOTE: tender has no "title" field — use tender.description as title.
# ===========================================================================

def scrape_tz_ocds(max_records=2000):
    """Tanzania NeST via OCDS API. Cursor-based pagination, 50/page.
    Note: Many releases are planning-only (no 'tender' key)."""
    base = "https://nest.go.tz/gateway/nest-data-portal-api/api/releases"
    tenders = []
    seen = 0
    url = base
    pages = 0
    try:
        while url and pages < 200:
            try:
                resp = http_get(url, timeout=30)
                if resp.status_code != 200:
                    # NeST API intermittently 500s on deep cursor pages — stop
                    # gracefully rather than failing the whole run (we keep what
                    # we already fetched, which is real data).
                    print(f"    tz_ocds: upstream HTTP {resp.status_code} at page {pages} — stopping (kept {len(tenders)})")
                    break
                data = resp.json()
            except Exception as e:
                print(f"    tz_ocds: upstream error at page {pages} ({type(e).__name__}) — stopping (kept {len(tenders)})")
                break
            releases = data.get("releases") or []
            if not releases:
                break
            for r in releases:
                if len(tenders) >= max_records:
                    break
                seen += 1
                t = r.get("tender") or {}
                # Tanzania uses description as title
                title = t.get("description") or t.get("title") or ""
                if not title or len(title) < 5:
                    continue
                status_raw = (t.get("status") or "").lower()
                status = ZM_STATUS_MAP.get(status_raw, "open")
                if status == "closed":
                    continue
                buyer = r.get("buyer") or {}
                buyer_name = buyer.get("name") or ""
                release_date = r.get("date") or ""
                adv = release_date[:10] if release_date else None
                items = t.get("items") or []
                item_desc = ""
                if items:
                    item_desc = (items[0].get("description") or "")[:300]
                description = item_desc or t.get("description") or ""
                text_for_sector = f"{title} {description} {item_desc}"
                tenders.append({
                    "source": "tz_ocds",
                    "source_key": make_source_key("TZ", "tz_ocds", r.get("ocid") or ""),
                    "title": title[:500],
                    "description": description[:1000],
                    "issuing_dept": buyer_name[:300],
                    "sector": extract_sector(text_for_sector),
                    "province": "",
                    "country": "Tanzania",
                    "country_code": "TZ",
                    "region": "East Africa",
                    "advert_date": adv,
                    "closing_date": None,
                    "status": status,
                    "contact_person": "",
                    "contact_email": "",
                    "contact_phone": "",
                    "document_url": "",
                    "source_url": f"https://data.nest.go.tz/ocds/release/{r.get('ocid') or ''}",
                })
            pages += 1
            url = data.get("links", {}).get("next")
            if pages % 10 == 0:
                print(f"    tz_ocds: page {pages}, {seen} scanned, {len(tenders)} kept")
        print(f"  tz_ocds: total {len(tenders)} tenders (scanned {seen})")
    except Exception as e:
        print(f"  tz_ocds: FAILED - {e}")
        log_scrape("tz_ocds", "TZ", 0, 0, "error", str(e)[:200])
        return []
    log_scrape("tz_ocds", "TZ", seen, len(tenders), "ok")
    return tenders


# ===========================================================================
# GHANA — OCP OCDS JSONL (publication 85)
# ===========================================================================
# Same OCDS shape as Nigeria/Zambia. Source: https://ghaneps.gov.gh
# ===========================================================================

GH_YEARS = [2026, 2025, 2024]
GH_OCP_PUB = 85
GH_STATUS_MAP = dict(NG_STATUS_MAP)


def scrape_gh_ocds(max_records=2000):
    """Ghana via OCP OCDS yearly releases. Same shape as NG/ZM."""
    tenders = []
    total_scanned = 0
    for year in GH_YEARS:
        if len(tenders) >= max_records:
            break
        try:
            records, from_cache = _download_ocds_year("GH", year, GH_OCP_PUB)
            print(f"    GH {year}: {len(records)} records (cache={'hit' if from_cache else 'miss'})")
        except Exception as e:
            print(f"    GH {year}: FAILED - {e}")
            log_scrape("gh_ocds", "GH", 0, 0, "error", str(e)[:200])
            continue
        scanned_this_year = 0
        for r in records:
            if len(tenders) >= max_records:
                break
            total_scanned += 1
            scanned_this_year += 1
            t = r.get("tender") or {}
            title = t.get("title") or ""
            if not title or len(title) < 5:
                continue
            status_raw = (t.get("status") or "").lower()
            status = GH_STATUS_MAP.get(status_raw, "open")
            if status == "closed":
                continue
            buyer = r.get("buyer") or {}
            buyer_name = buyer.get("name") or ""
            release_date = r.get("date") or ""
            adv = release_date[:10] if release_date else None
            items = t.get("items") or []
            item_desc = ""
            if items:
                item_desc = (items[0].get("description") or "")[:300]
            description = item_desc or t.get("description") or ""
            text_for_sector = f"{title} {description} {item_desc}"
            tenders.append({
                "source": "gh_ocds",
                "source_key": make_source_key("GH", "gh_ocds", r.get("ocid") or ""),
                "title": title[:500],
                "description": description[:1000],
                "issuing_dept": buyer_name[:300],
                "sector": extract_sector(text_for_sector),
                "province": "",
                "country": "Ghana",
                "country_code": "GH",
                "region": "West Africa",
                "advert_date": adv,
                "closing_date": None,
                "status": status,
                "contact_person": "",
                "contact_email": "",
                "contact_phone": "",
                "document_url": "",
                "source_url": f"https://ghaneps.gov.gh/tenders/ocid/{r.get('ocid') or ''}",
            })
            if scanned_this_year % 5000 == 0 and scanned_this_year > 0:
                print(f"    GH {year}: scanned {scanned_this_year}, kept {len(tenders)}")
        print(f"    GH {year}: kept {len(tenders)} so far (scanned {scanned_this_year})")
    print(f"  gh_ocds: total {len(tenders)} tenders (scanned {total_scanned})")
    log_scrape("gh_ocds", "GH", total_scanned, len(tenders), "ok")
    return tenders


# ===========================================================================
# ZIMBABWE — zimbabwetenders.com (HTML, JS-rendered tender cards)
# ===========================================================================
# Page: https://www.zimbabwetenders.com — server-rendered HTML with
# <div class="tender-card"> blocks. Each has a heading + link to authority.
# ===========================================================================

def scrape_zw_html(max_records=200):
    """Zimbabwe via zimbabwetenders.com HTML parsing."""
    url = "https://www.zimbabwetenders.com"
    tenders = []
    try:
        resp = http_get(url, timeout=40)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.find_all("div", class_="tender-card")
        if not cards:
            # Fallback: look for tender-item
            cards = soup.find_all("div", class_="tender-item")
        for card in cards[:max_records]:
            # Get the heading
            heading = card.find(["p", "h3", "h4", "div"], class_=re.compile(r"heading|title", re.I))
            if not heading:
                heading = card.find(["p", "h3", "h4"])
            title = heading.get_text(strip=True) if heading else ""
            if not title or len(title) < 5:
                continue
            # Get the link
            link = card.find("a", href=True)
            source_url = link["href"] if link else url
            # Get any date text
            date_text = card.get_text(" ", strip=True)
            adv, cls = extract_dates(date_text)
            tenders.append({
                "source": "zw_html",
                "source_key": make_source_key("ZW", "zw_html", source_url),
                "title": title[:500],
                "description": "",
                "issuing_dept": "",
                "sector": extract_sector(title),
                "province": "",
                "country": "Zimbabwe",
                "country_code": "ZW",
                "region": "Southern Africa",
                "advert_date": adv,
                "closing_date": cls,
                "status": "open",
                "contact_person": "",
                "contact_email": "",
                "contact_phone": "",
                "document_url": "",
                "source_url": source_url,
            })
        print(f"  zw_html: found {len(tenders)}")
    except Exception as e:
        print(f"  zw_html: FAILED - {e}")
        log_scrape("zw_html", "ZW", 0, 0, "error", str(e)[:200])
        return []
    log_scrape("zw_html", "ZW", len(tenders), 0, "ok")
    return tenders


# ===========================================================================
# MOROCCO — marchespublics.gov.ma (HTML, jQuery tabs)
# ===========================================================================
# Page: https://www.marchespublics.gov.ma/pmmp/ — 1.3MB server-rendered HTML.
# Has search results in a tabbed interface. Parse the main listing.
# ===========================================================================

def scrape_ma_html(max_records=200):
    """Morocco via marchespublics.gov.ma HTML parsing."""
    url = "https://www.marchespublics.gov.ma/pmmp/"
    tenders = []
    try:
        resp = http_get(url, timeout=60)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Find tender listings — look for table rows or list items
        rows = soup.find_all("tr")
        if not rows:
            rows = soup.find_all("div", class_=re.compile(r"item|row|entry", re.I))
        for row in rows[:max_records]:
            # Get the link text as title
            link = row.find("a", href=True)
            title = link.get_text(strip=True) if link else ""
            if not title or len(title) < 8:
                # Try any text in the row
                title = row.get_text(" ", strip=True)[:200]
            if not title or len(title) < 8:
                continue
            source_url = link["href"] if link else url
            if source_url and not source_url.startswith("http"):
                source_url = "https://www.marchespublics.gov.ma" + source_url
            # Get date text
            date_text = row.get_text(" ", strip=True)
            adv, cls = extract_dates(date_text)
            tenders.append({
                "source": "ma_html",
                "source_key": make_source_key("MA", "ma_html", source_url),
                "title": title[:500],
                "description": "",
                "issuing_dept": "",
                "sector": extract_sector(title),
                "province": "",
                "country": "Morocco",
                "country_code": "MA",
                "region": "North Africa",
                "advert_date": adv,
                "closing_date": cls,
                "status": "open",
                "contact_person": "",
                "contact_email": "",
                "contact_phone": "",
                "document_url": "",
                "source_url": source_url,
            })
        print(f"  ma_html: found {len(tenders)}")
    except Exception as e:
        print(f"  ma_html: FAILED - {e}")
        log_scrape("ma_html", "MA", 0, 0, "error", str(e)[:200])
        return []
    log_scrape("ma_html", "MA", len(tenders), 0, "ok")
    return tenders


# ===========================================================================
# MAURITIUS — publicprocurement.govmu.org (WordPress)
# ===========================================================================
# Page: https://publicprocurement.govmu.org/publicprocurement/ — WordPress site.
# Uses [data] shortcodes. Parse the main content area.
# ===========================================================================

def scrape_mu_html(max_records=200):
    """Mauritius via publicprocurement.govmu.org HTML parsing."""
    url = "https://publicprocurement.govmu.org/publicprocurement/"
    tenders = []
    try:
        resp = http_get(url, timeout=40)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Find the main content area
        content = soup.find("div", id="main-container") or soup.find("main") or soup.find("div", class_="content")
        if not content:
            content = soup
        # Find all links that look like tender notices
        links = content.find_all("a", href=True)
        seen_urls = set()
        for link in links:
            if len(tenders) >= max_records:
                break
            href = link["href"]
            if href in seen_urls:
                continue
            title = link.get_text(strip=True)
            if not title or len(title) < 8:
                continue
            # Skip navigation links
            if any(x in href.lower() for x in ["wp-login", "wp-admin", "feed", "comment", "author"]):
                continue
            seen_urls.add(href)
            tenders.append({
                "source": "mu_html",
                "source_key": make_source_key("MU", "mu_html", href),
                "title": title[:500],
                "description": "",
                "issuing_dept": "",
                "sector": extract_sector(title),
                "province": "",
                "country": "Mauritius",
                "country_code": "MU",
                "region": "East Africa",
                "advert_date": None,
                "closing_date": None,
                "status": "open",
                "contact_person": "",
                "contact_email": "",
                "contact_phone": "",
                "document_url": "",
                "source_url": href,
            })
        print(f"  mu_html: found {len(tenders)}")
    except Exception as e:
        print(f"  mu_html: FAILED - {e}")
        log_scrape("mu_html", "MU", 0, 0, "error", str(e)[:200])
        return []
    log_scrape("mu_html", "MU", len(tenders), 0, "ok")
    return tenders


# ===========================================================================
# ETHIOPIA — production.egp.gov.et official sourcing feed (REAL, verified)
# ===========================================================================
# Source of truth: Ethiopia's national e-GP platform public API.
#   GET https://production.egp.gov.et/po-gw/cms-v2/api/sourcing/get-grouped-sourcing
#       ?type=all&skip=N&top=50&locale=en
# Returns ~506 live tender packages with real procuring-entity, reference no,
# submission deadline, invitation date, method and marketPlace. No auth needed.
# This is the genuine government portal — not guessed/scraped HTML.
# ===========================================================================

ET_API = "https://production.egp.gov.et/po-gw/cms-v2/api/sourcing/get-grouped-sourcing"


def scrape_et_feed(max_records=2000):
    """Ethiopia via the official e-GP sourcing feed (real, paginated JSON)."""
    tenders = []
    skip = 0
    top = 50
    seen = 0
    try:
        while len(tenders) < max_records:
            resp = http_get(f"{ET_API}?type=all&skip={skip}&top={top}&locale=en",
                            headers={"Accept": "application/json"}, timeout=40)
            if resp.status_code != 200:
                break
            try:
                data = resp.json()
            except Exception:
                break
            items = data.get("items") or []
            if not items:
                break
            for pkg in items:
                if len(tenders) >= max_records:
                    break
                seen += 1
                results = pkg.get("result") or []
                if not results:
                    continue
                # A package may hold several lots; each lot is one opportunity.
                for lot in results:
                    title = (lot.get("lotName") or lot.get("lotDescription") or "").strip()
                    if not title or len(title) < 5:
                        continue
                    ref = (lot.get("procurementReferenceNo") or "").strip()
                    pe = (lot.get("procuringEntity") or
                          (lot.get("originName") or {}).get("en") or "").strip()
                    adv = (lot.get("invitationDate") or "")[:10]
                    cls = (lot.get("submissionDeadline") or "")[:19]
                    text = f"{title} {lot.get('procurementCategory','')} {lot.get('method','')} {pe}"
                    tenders.append({
                        "source": "et_feed",
                        "source_key": make_source_key("ET", "et_feed", ref or lot.get("id") or title),
                        "title": title[:500],
                        "description": (lot.get("lotDescription") or title)[:1000],
                        "issuing_dept": pe[:300],
                        "sector": extract_sector(text),
                        "province": "",
                        "country": "Ethiopia",
                        "country_code": "ET",
                        "region": "East Africa",
                        "advert_date": adv or None,
                        "closing_date": cls or None,
                        "status": "open",
                        "contact_person": "",
                        "contact_email": "",
                        "contact_phone": "",
                        "document_url": "",
                        "source_url": "https://production.egp.gov.et/egp/bids/all",
                    })
            total = data.get("total")
            if total and skip + top >= total:
                break
            skip += top
        print(f"  et_feed: total {len(tenders)} tenders (packages scanned {seen})")
    except Exception as e:
        print(f"  et_feed: FAILED - {e}")
        log_scrape("et_feed", "ET", 0, 0, "error", str(e)[:200])
        return []
    log_scrape("et_feed", "ET", seen, len(tenders), "ok")
    return tenders


# ===========================================================================
# RWANDA — RPPA Umucyo via OCP OCDS (REAL, verified)
# ===========================================================================
# Source of truth: Open Contracting Partnership publication 145 = Rwanda
# Public Procurement Authority (RPPA) open data. Same OCDS shape as NG/ZM/GH.
#   https://data.open-contracting.org/en/publication/145/download?name=YYYY.jsonl.gz
# ~16k records; ~1,000 active. Genuine government open data (not the SPA shell).
# ===========================================================================

RW_OCP_PUB = 145
RW_YEARS = [2026, 2025, 2024]
RW_STATUS_MAP = dict(NG_STATUS_MAP)


def scrape_rw_ocds(max_records=2000):
    """Rwanda via OCP OCDS yearly releases (real, verified pub 145)."""
    tenders = []
    total_scanned = 0
    for year in RW_YEARS:
        if len(tenders) >= max_records:
            break
        try:
            records, from_cache = _download_ocds_year("RW", year, RW_OCP_PUB)
            print(f"    RW {year}: {len(records)} records (cache={'hit' if from_cache else 'miss'})")
        except Exception as e:
            print(f"    RW {year}: FAILED - {e}")
            log_scrape("rw_ocds", "RW", 0, 0, "error", str(e)[:200])
            continue
        scanned_this_year = 0
        for r in records:
            if len(tenders) >= max_records:
                break
            total_scanned += 1
            scanned_this_year += 1
            t = r.get("tender") or {}
            title = t.get("title") or t.get("description") or ""
            if not title or len(title) < 5:
                continue
            status_raw = (t.get("status") or "").lower()
            status = RW_STATUS_MAP.get(status_raw, "open")
            if status == "closed":
                continue
            buyer = r.get("buyer") or {}
            buyer_name = buyer.get("name") or ""
            release_date = r.get("date") or ""
            adv = release_date[:10] if release_date else None
            items = t.get("items") or []
            item_desc = ""
            if items:
                item_desc = (items[0].get("description") or "")[:300]
            description = item_desc or t.get("description") or ""
            text_for_sector = f"{title} {description} {item_desc}"
            tenders.append({
                "source": "rw_ocds",
                "source_key": make_source_key("RW", "rw_ocds", r.get("ocid") or ""),
                "title": title[:500],
                "description": description[:1000],
                "issuing_dept": buyer_name[:300],
                "sector": extract_sector(text_for_sector),
                "province": "",
                "country": "Rwanda",
                "country_code": "RW",
                "region": "East Africa",
                "advert_date": adv,
                "closing_date": None,
                "status": status,
                "contact_person": "",
                "contact_email": "",
                "contact_phone": "",
                "document_url": "",
                "source_url": f"https://ocds.umucyo.gov.rw/ocid/{r.get('ocid') or ''}",
            })
            if scanned_this_year % 5000 == 0 and scanned_this_year > 0:
                print(f"    RW {year}: scanned {scanned_this_year}, kept {len(tenders)}")
        print(f"    RW {year}: kept {len(tenders)} so far (scanned {scanned_this_year})")
    print(f"  rw_ocds: total {len(tenders)} tenders (scanned {total_scanned})")
    log_scrape("rw_ocds", "RW", total_scanned, len(tenders), "ok")
    return tenders


def scrape_zm_ocds(max_records=2000):
    """Zambia ZPPA via OCP OCDS yearly releases. Same shape as NG."""
    tenders = []
    total_scanned = 0
    for year in ZM_YEARS:
        if len(tenders) >= max_records:
            break
        try:
            records, from_cache = _download_ocds_year("ZM", year, ZM_OCP_PUB)
            print(f"    ZM {year}: {len(records)} records (cache={'hit' if from_cache else 'miss'})")
        except Exception as e:
            print(f"    ZM {year}: FAILED - {e}")
            log_scrape("zm_ocds", "ZM", 0, 0, "error", str(e)[:200])
            continue
        scanned_this_year = 0
        for r in records:
            if len(tenders) >= max_records:
                break
            total_scanned += 1
            scanned_this_year += 1
            t = r.get("tender") or {}
            title = t.get("title") or ""
            if not title or len(title) < 5:
                continue
            status_raw = (t.get("status") or "").lower()
            status = ZM_STATUS_MAP.get(status_raw, "open")
            if status == "closed":
                continue
            buyer = r.get("buyer") or {}
            buyer_name = buyer.get("name") or ""
            release_date = r.get("date") or ""
            adv = release_date[:10] if release_date else None
            value = t.get("value") or {}
            amount = value.get("amount")
            currency = value.get("currency", "ZMW")
            items = t.get("items") or []
            item_desc = ""
            if items:
                item_desc = (items[0].get("description") or "")[:300]
            description = item_desc or t.get("description") or ""
            text_for_sector = f"{title} {description} {item_desc}"
            tenders.append({
                "source": "zm_ocds",
                "source_key": make_source_key("ZM", "zm_ocds", r.get("ocid") or ""),
                "title": title[:500],
                "description": description[:1000],
                "issuing_dept": buyer_name[:300],
                "sector": extract_sector(text_for_sector),
                "province": "",
                "country": "Zambia",
                "country_code": "ZM",
                "region": "Southern Africa",
                "advert_date": adv,
                "closing_date": None,
                "status": status,
                "contact_person": "",
                "contact_email": "",
                "contact_phone": "",
                "document_url": "",
                "source_url": f"https://www.zppa.org.zm/tenders/ocid/{r.get('ocid') or ''}",
            })
            if scanned_this_year % 5000 == 0 and scanned_this_year > 0:
                print(f"    ZM {year}: scanned {scanned_this_year}, kept {len(tenders)}")
        print(f"    ZM {year}: kept {len(tenders)} so far (scanned {scanned_this_year})")
    print(f"  zm_ocds: total {len(tenders)} tenders (scanned {total_scanned})")
    log_scrape("zm_ocds", "ZM", total_scanned, len(tenders), "ok")
    return tenders


# ===========================================================================
# MOZAMBIQUE / NAMIBIA / BOTSWANA — OCP OCDS (best-effort)
# ===========================================================================
# Same OCDS shape as Zambia/Nigeria, pulled from the Open Contracting Partnership
# publication endpoint. These three were added on user request (SADC coverage).
# NOTE: OCP publisher IDs for MZ/NA/BW were NOT confirmed at implementation time
# (the OCP registry search API is JS-gated / blocked from the scraper host). We
# default the pub IDs to None so each source self-skips cleanly (logs "no feed")
# until a real OCP publisher ID is filled in. They will simply stay empty until
# then — no errors, no missed runs for the other countries.
#
# To enable a country: set its *_OCP_PUB to the correct OCP publication id and
# re-run. Find it at https://data.open-contracting.org/ (search the country).
# ===========================================================================

MZ_YEARS = [2026, 2025, 2024]
NA_YEARS = [2026, 2025, 2024]
BW_YEARS = [2026, 2025, 2024]
MZ_OCP_PUB = None   # TODO: confirm OCP publisher id for Mozambique
NA_OCP_PUB = None   # TODO: confirm OCP publisher id for Namibia
BW_OCP_PUB = None   # TODO: confirm OCP publisher id for Botswana
MZ_STATUS_MAP = dict(NG_STATUS_MAP)
NA_STATUS_MAP = dict(NG_STATUS_MAP)
BW_STATUS_MAP = dict(NG_STATUS_MAP)


def _scrape_ocp_best_effort(cc, pub, years, status_map, source_name, country_name,
                             region, source_url_tpl, max_records=2000):
    """Generic OCDS-OCP scraper shared by MZ/NA/BW. Self-skips if no pub id
    or the feed 404s/is empty (best-effort, no run-breaking errors)."""
    tenders = []
    if not pub:
        print(f"  {source_name}: SKIPPED (no OCP publisher id configured)")
        log_scrape(source_name, cc, 0, 0, "skipped", "no OCP publisher id")
        return tenders
    total_scanned = 0
    for year in years:
        if len(tenders) >= max_records:
            break
        try:
            records, from_cache = _download_ocds_year(cc, year, pub)
            print(f"    {cc} {year}: {len(records)} records (cache={'hit' if from_cache else 'miss'})")
        except Exception as e:
            print(f"    {cc} {year}: FAILED - {e}")
            log_scrape(source_name, cc, 0, 0, "error", str(e)[:200])
            continue
        if not records:
            continue
        scanned_this_year = 0
        for r in records:
            if len(tenders) >= max_records:
                break
            total_scanned += 1
            scanned_this_year += 1
            t = r.get("tender") or {}
            title = t.get("title") or t.get("description") or ""
            if not title or len(title) < 5:
                continue
            status_raw = (t.get("status") or "").lower()
            status = status_map.get(status_raw, "open")
            if status == "closed":
                continue
            buyer = r.get("buyer") or {}
            buyer_name = buyer.get("name") or ""
            release_date = r.get("date") or ""
            adv = release_date[:10] if release_date else None
            value = t.get("value") or {}
            amount = value.get("amount")
            currency = value.get("currency", "")
            items = t.get("items") or []
            item_desc = (items[0].get("description") or "")[:300] if items else ""
            description = item_desc or t.get("description") or ""
            text_for_sector = f"{title} {description} {item_desc}"
            tenders.append({
                "source": source_name,
                "source_key": make_source_key(cc, source_name, r.get("ocid") or ""),
                "title": title[:500],
                "description": description[:1000],
                "issuing_dept": buyer_name[:300],
                "sector": extract_sector(text_for_sector),
                "province": "",
                "country": country_name,
                "country_code": cc,
                "region": region,
                "advert_date": adv,
                "closing_date": None,
                "status": status,
                "contact_person": "",
                "contact_email": "",
                "contact_phone": "",
                "document_url": "",
                "source_url": source_url_tpl.format(ocid=(r.get("ocid") or "")),
            })
        print(f"    {cc} {year}: kept {len(tenders)} so far (scanned {scanned_this_year})")
    print(f"  {source_name}: total {len(tenders)} tenders (scanned {total_scanned})")
    log_scrape(source_name, cc, total_scanned, len(tenders), "ok")
    return tenders


def scrape_mz_ocds(max_records=2000):
    """Mozambique — OCP OCDS (best-effort; empty until pub id confirmed)."""
    return _scrape_ocp_best_effort(
        "MZ", MZ_OCP_PUB, MZ_YEARS, MZ_STATUS_MAP, "mz_ocds", "Mozambique",
        "Southern Africa", "https://data.open-contracting.org/en/publication/{ocid}",
        max_records)


def scrape_na_ocds(max_records=2000):
    """Namibia — OCP OCDS (best-effort; empty until pub id confirmed)."""
    return _scrape_ocp_best_effort(
        "NA", NA_OCP_PUB, NA_YEARS, NA_STATUS_MAP, "na_ocds", "Namibia",
        "Southern Africa", "https://data.open-contracting.org/en/publication/{ocid}",
        max_records)


def scrape_bw_ocds(max_records=2000):
    """Botswana — OCP OCDS (best-effort; empty until pub id confirmed)."""
    return _scrape_ocp_best_effort(
        "BW", BW_OCP_PUB, BW_YEARS, BW_STATUS_MAP, "bw_ocds", "Botswana",
        "Southern Africa", "https://data.open-contracting.org/en/publication/{ocid}",
        max_records)


# ===========================================================================
# SOUTH AFRICA — Tender Bulletins (tenderbulletins.co.za) Audio-Visual category
# ===========================================================================
# Real WordPress tender-bulletin site. The AV category page lists ~342 posts
# across 7 pages (50/page). Each listing row links to a detail page with full
# metadata (tender no, closing date, department/company, location/province,
# description, contact person/email/phone). We parse the listing pages for the
# row summary, then fetch each detail page to enrich. Idempotent via
# source_key on the detail URL (INSERT OR IGNORE on re-run).
#
# Category scope (per user request): Audio Visual and Photographic Equipment ONLY.
# To add more categories later, add entries to TB_CATEGORIES and loop them.
# ===========================================================================

TB_CATEGORY_BASE = "https://tenderbulletins.co.za/tender-category/audio-visual-equipment/"


def _tb_parse_datetime(s):
    """Parse '2026-09-01 16:00' or 'Thursday, 27 August 2026 - 16:00' -> ISO-ish."""
    if not s:
        return None
    s = s.strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{1,2}):(\d{2}))?", s)
    if m:
        out = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        if m.group(4):
            out += f" {int(m.group(4)):02d}:{int(m.group(5)):02d}:00"
        return out
    m = re.search(r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})(?:\s*-\s*(\d{1,2}):(\d{2}))?", s, re.IGNORECASE)
    if m:
        try:
            d = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y")
            out = d.strftime("%Y-%m-%d")
            if m.group(4):
                out += f" {int(m.group(4)):02d}:{int(m.group(5)):02d}:00"
            return out
        except ValueError:
            pass
    return None


_TB_STOP = ("email this tender", "account functions", "sign in with", "forgot password",
            "remember me", "login using", "lost your password", "log in with")


def _tb_assign(out, label, val):
    """Map a normalised label to a metadata field (first wins)."""
    label = label.strip("*: ").lower()
    if not label or not val:
        return
    if "tender no" in label or "reference number" in label:
        out.setdefault("tender_no", val)
    elif "department" in label or "company" in label or label == "required at":
        out.setdefault("department", val)
    elif "location" in label or label == "province":
        out.setdefault("province", val)
    elif "closing" in label:
        out.setdefault("closing", val)
    elif "contact person" in label:
        out.setdefault("contact_person", val)
    elif label == "email":
        out.setdefault("contact_email", val)
    elif "telephone" in label or "phone" in label:
        out.setdefault("contact_phone", val)


def _tb_meta(soup):
    """Extract label/value pairs from a Tender Bulletins detail page.
    Handles both templates: definition tables (tender-bulletin/*) and prose
    headers (rfq/*). Walks elements in document order and stops at the login
    block so footer/sidebar junk is never captured."""
    out = {}
    content = soup.find(class_=re.compile("entry-content")) or soup.find("article") or soup
    # 1) definition tables (template A enquiry block + any label/value tables)
    for table in content.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            label = cells[0].get_text(" ", strip=True)
            val = cells[1].get_text(" ", strip=True)
            _tb_assign(out, label, val)
    # 2) prose elements (template B header) — stop at the login block
    for el in content.find_all(["p", "li", "div", "span", "strong"]):
        txt = el.get_text(" ", strip=True)
        if any(s in txt.lower() for s in _TB_STOP):
            break
        if ":" not in txt or len(txt) > 200:
            continue
        label, val = txt.split(":", 1)
        _tb_assign(out, label, val.strip())
    return out


def _tb_description(soup):
    """Grab the first substantial prose paragraph (the real scope/description),
    ignoring the label:value header and the login sidebar."""
    content = soup.find("article") or soup.find(class_=re.compile("entry-content")) or soup
    for el in content.find_all(["p", "div", "li"]):
        txt = el.get_text(" ", strip=True)
        if any(s in txt.lower() for s in _TB_STOP):
            break
        if len(txt) > 60 and ":" not in txt[:30]:
            return txt[:1000]
    return ""


def scrape_za_tenderbulletins(max_pages=15):
    """Scrape the Audio-Visual & Photographic Equipment category on Tender Bulletins.
    Returns a list of tender dicts ready for save_tenders()."""
    import time as _time
    tenders = []
    seen_keys = set()
    enrich = True        # detail-page enrichment; disabled if server starts blocking
    fail_streak = 0
    try:
        page = 1
        while page <= max_pages:
            url = TB_CATEGORY_BASE if page == 1 else f"{TB_CATEGORY_BASE.rstrip('/')}/page/{page}/"
            resp = http_get(url, timeout=40)
            if resp.status_code != 200:
                break
            soup = BeautifulSoup(resp.text, "html.parser")
            table = None
            for t in soup.find_all("table"):
                hdr = t.get_text(" ", strip=True).lower()
                if "tender title" in hdr and "closing date" in hdr:
                    table = t
                    break
            if table is None:
                if page == 1:
                    print("  tenderbulletins: no listing table found on page 1")
                break
            rows = table.find_all("tr")[1:]  # skip header row
            if not rows:
                break
            page_count = 0
            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 2:
                    continue
                link = cols[0].find("a", href=True)
                title = cols[0].get_text(" ", strip=True)
                number = cols[1].get_text(" ", strip=True) if len(cols) > 1 else ""
                closing_listing = cols[3].get_text(" ", strip=True) if len(cols) > 3 else ""
                detail_url = urljoin(url, str(link["href"])) if link else None
                if not title or not detail_url:
                    continue
                # fetch detail page for enrichment (resilient: continue on failure)
                meta = {}
                desc = ""
                if enrich:
                    try:
                        dresp = http_get(detail_url, timeout=12)
                        if dresp.status_code == 200:
                            dsoup = BeautifulSoup(dresp.text, "html.parser")
                            meta = _tb_meta(dsoup)
                            desc = _tb_description(dsoup)
                        fail_streak = 0
                    except Exception:
                        fail_streak += 1
                        if fail_streak >= 3:
                            enrich = False
                            print("  tenderbulletins: detail enrichment disabled (server blocking); using listing data")
                # tender number: prefer detail, fall back to listing
                tender_no = meta.get("tender_no") or number
                closing = _tb_parse_datetime(meta.get("closing") or closing_listing)
                prov = meta.get("province") or meta.get("province_loc")
                if prov:
                    parts = [p.strip() for p in prov.split(",")]
                    province = parts[-1] if len(parts) > 1 else parts[0]
                else:
                    province = "National"
                key = make_source_key("ZA", "tenderbulletins", detail_url)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                tenders.append({
                    "source": "tenderbulletins",
                    "source_key": key,
                    "title": title[:500],
                    "description": desc,
                    "issuing_dept": (meta.get("department") or meta.get("required_at") or "")[:300],
                    "sector": "audio_visual",
                    "province": province[:100],
                    "country": "South Africa",
                    "country_code": "ZA",
                    "region": "Southern Africa",
                    "advert_date": None,
                    "closing_date": closing,
                    "status": "open",
                    "contact_person": meta.get("contact_person", "")[:120],
                    "contact_email": meta.get("contact_email", "")[:120],
                    "contact_phone": meta.get("contact_phone", "")[:60],
                    "document_url": "",
                    "source_url": detail_url,
                })
                page_count += 1
                _time.sleep(0.25)
            print(f"  tenderbulletins: page {page}: {page_count} AV rows")
            if page_count < 1:
                break
            page += 1
        print(f"  tenderbulletins: collected {len(tenders)} Audio-Visual tenders")
    except Exception as e:
        print(f"  tenderbulletins: FAILED - {e}")
        log_scrape("tenderbulletins", "ZA", 0, 0, "error", str(e)[:200])
        return []
    log_scrape("tenderbulletins", "ZA", len(tenders), len(tenders), "ok")
    return tenders


def run():
    print("=== Moya Multi-Country Scraper Starting ===")
    ensure_tables()
    all_found = []
    # South Africa
    all_found += scrape_sa_etenders()
    all_found += scrape_sa_ocpo()
    # South Africa — Tender Bulletins (Audio-Visual category)
    all_found += scrape_za_tenderbulletins()
    # Kenya
    all_found += scrape_ke_ppip()
    all_found += scrape_ke_egp()
    # Nigeria (new)
    all_found += scrape_ng_ocds()
    # Zambia (new)
    all_found += scrape_zm_ocds()
    # Mozambique / Namibia / Botswana (best-effort OCP OCDS; empty until pub ids confirmed)
    all_found += scrape_mz_ocds()
    all_found += scrape_na_ocds()
    all_found += scrape_bw_ocds()
    # Tanzania (real — NeST API)
    all_found += scrape_tz_ocds()
    # Ghana (new)
    all_found += scrape_gh_ocds()
    # Zimbabwe (new)
    all_found += scrape_zw_html()
    # Morocco (new)
    all_found += scrape_ma_html()
    # Mauritius (new)
    all_found += scrape_mu_html()
    # Ethiopia (new — official e-GP sourcing feed)
    all_found += scrape_et_feed()
    # Rwanda (new — RPPA OCP OCDS pub 145)
    all_found += scrape_rw_ocds()

    saved = save_tenders(all_found)
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
    by_country = db.execute("SELECT country_code, COUNT(*) n FROM tenders GROUP BY country_code").fetchall()
    db.close()
    print(f"=== Scraper complete: {len(all_found)} scraped this run ({saved} new), {total} total in DB ===")
    for r in by_country:
        print(f"    {r['country_code']}: {r['n']}")


if __name__ == "__main__":
    run()
