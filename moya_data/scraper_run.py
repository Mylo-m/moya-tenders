#!/usr/bin/env python3
"""
Moya — Production Scraper
Scrapes South African tender portals and stores in SQLite.
Run via cron: cd /path && python3 scraper_run.py
"""

import os
import re
import hashlib
import sqlite3
import json
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus

DB_PATH = os.environ.get('MOYA_DB', '/usr/www/users/myloxy/moya_data/moya.db')

SOURCES = [
    {
        "key": "etenders",
        "name": "eTenders National",
        "base_url": "https://www.etenders.gov.za",
        "list_url": "https://www.etenders.gov.za/content/advertised-tenders",
    },
    {
        "key": "gauteng",
        "name": "Gauteng Provincial",
        "base_url": "https://www.gauteng.gov.za",
        "list_url": "https://www.gauteng.gov.za/tenders",
    },
    {
        "key": "western_cape",
        "name": "Western Cape Government",
        "base_url": "https://www.westerncape.gov.za",
        "list_url": "https://www.westerncape.gov.za/tenders",
    },
    {
        "key": "kzn",
        "name": "KwaZulu-Natal",
        "base_url": "https://www.kzn.gov.za",
        "list_url": "https://www.kzn.gov.za/tenders",
    },
    {
        "key": "joburg",
        "name": "City of Johannesburg",
        "base_url": "https://www.joburg.org.za",
        "list_url": "https://www.joburg.org.za/tenders",
    },
    {
        "key": "capetown",
        "name": "City of Cape Town",
        "base_url": "https://www.capetown.gov.za",
        "list_url": "https://www.capetown.gov.za/tenders",
    },
    {
        "key": "kwazulunatal_tpa",
        "name": "KZN Transport",
        "base_url": "http://www.kzntransport.gov.za",
        "list_url": "http://www.kzntransport.gov.za/tenders/",
    },
    {
        "key": "treasury",
        "name": "National Treasury",
        "base_url": "https://www.treasury.gov.za",
        "list_url": "https://www.treasury.gov.za/tenders",
    },
    {
        "key": "sars",
        "name": "SARS Tenders",
        "base_url": "https://www.sars.gov.za",
        "list_url": "https://www.sars.gov.za/tenders",
    },
    {
        "key": "transnet",
        "name": "Transnet",
        "base_url": "https://www.transnet.net",
        "list_url": "https://www.transnet.net/tenders",
    },
    {
        "key": "eskom",
        "name": "Eskom",
        "base_url": "https://www.eskom.co.za",
        "list_url": "https://www.eskom.co.za/tenders",
    },
    {
        "key": "sanral",
        "name": "SANRAL",
        "base_url": "https://www.sanral.co.za",
        "list_url": "https://www.sanral.co.za/tenders",
    },
    {
        "key": "dwa",
        "name": "Water Affairs",
        "base_url": "https://www.dwa.gov.za",
        "list_url": "https://www.dwa.gov.za/tenders",
    },
    {
        "key": "daff",
        "name": "Agriculture",
        "base_url": "https://www.daff.gov.za",
        "list_url": "https://www.daff.gov.za/tenders",
    },
    {
        "key": "dhet",
        "name": "Higher Education",
        "base_url": "https://www.dhet.gov.za",
        "list_url": "https://www.dhet.gov.za/tenders",
    },
    {
        "key": "health",
        "name": "Health Department",
        "base_url": "https://www.health.gov.za",
        "list_url": "https://www.health.gov.za/tenders",
    },
    {
        "key": "education",
        "name": "Basic Education",
        "base_url": "https://www.education.gov.za",
        "list_url": "https://www.education.gov.za/tenders",
    },
    {
        "key": "saps",
        "name": "South African Police",
        "base_url": "https://www.saps.gov.za",
        "list_url": "https://www.saps.gov.za/tenders",
    },
    {
        "key": " defence",
        "name": "Defence",
        "base_url": "https://www.dod.mil.za",
        "list_url": "https://www.dod.mil.za/tenders",
    },
    {
        "key": "homeaffairs",
        "name": "Home Affairs",
        "base_url": "https://://www.dha.gov.za",
        "list_url": "https://www.dha.gov.za/tenders",
    },
]

SECTOR_KEYWORDS = {
    "construction": ["building", "construction", "civil", "roads", "infrastructure", "renovation", "maintenance", "structural", "painting", "plumbing", "electrical", "roofing", "paving", "fencing", "demolition", "excavation", "landscaping", "tiling", "waterproofing", "plastering", "carpentry", "welding", "steel", "concrete", "cement", "brick", "masonry", "scaffolding", "crane", "earthworks", "drainage", "sewer", "pipeline", "dam", "bridge", "tunnel", "airport", "harbour", "railway", "station", "hospital", "clinic", "school", "university", "college", "library", "museum", "stadium", "community centre", "housing", "RDP", "residential", "commercial", "industrial", "warehouse", "factory", "office", "retail", "shopping centre", "hotel", "resort", "sports facility", "park", "garden", "road", "highway", "street", "sidewalk", "stormwater", "water supply", "irrigation"],
    "ict": ["ict", "it", "software", "hardware", "network", "cyber", "data", "digital", "system", "computer", "server", "cloud", "artificial intelligence", "ai", "machine learning", "iot", "internet", "website", "app", "mobile", "database", "erp", "crm", "telecom", "voip", "fiber", "broadband", "wifi", "lan", "wan", "vpn", "firewall", "security", "antivirus", "backup", "disaster recovery", "hosting", "domain", "email", "microsoft", "google", "aws", "azure", "blockchain", "rpa", "automation", "api", "integration", "migration", "upgrade", "support", "helpdesk", "training", "consulting", "audit", "license", "subscription", "saas", "paas", "iaas"],
    "medical": ["medical", "health", "hospital", "clinic", "pharmaceutical", "ppe", "ambulance", "nurse", "doctor", "specialist", "gp", "dentist", "optometrist", "physiotherapy", "occupational therapy", "radiology", "pathology", "laboratory", "surgical", "equipment", "device", "medicine", "vaccine", "blood", "organ", "tissue", "rehabilitation", "mental health", "substance abuse", "hospice", "home care", "primary health care", "phc", "nhi", "medical scheme", "coida", "occupational health", "infection control", "waste management", "sterilization", "autoclave", "cold chain", "pharmacovigilance", "clinical trial", "ethics committee", "sahpra", "medicine control council", "mcc"],
    "security": ["security", "guarding", "cctv", "access control", "armed response", "surveillance", "alarm", "detection", "inspection", "patrol", "vehicle", "k9", "dog", "crowd control", "event security", "close protection", "executive protection", "asset protection", "loss prevention", "retail security", "industrial security", "residential security", "commercial security", "government security", "psira", "private security industry regulatory authority"],
    "logistics": ["transport", "logistics", "freight", "courier", "fleet", "delivery", "warehousing", "distribution", "supply chain", "cold chain", "refrigerated", "flatbed", "tanker", "container", "abnormal", "load", "permit", "route", "tracking", "gps", "fleet management", "driver", "operator", "vehicle", "truck", "trailer", "interlink", "superlink", "breakbulk", "consolidation", "cross-docking", "last mile", "reverse logistics"],
    "education": ["education", "school", "training", "learnership", "seta", "curriculum", "e-learning", "assessment", "moderation", "accreditation", "nqf", "saqa", "umalusi", "qcto", "department of higher education and training", "dhet", "department of basic education", "dbe", "tvet", "community education and training", "cet", "abet", "literacy", "numeracy", "matric", "nsc", "ncv", "national certificate vocational"],
    "energy": ["energy", "electrical", "solar", "power", "renewable", "generator", "eskom", "municipal", "distribution", "transmission", "substation", "transformer", "cable", "overhead", "underground", "switchgear", "protection", "metering", "prepaid", "conventional", "smart meter", "ami", "scada", "dms", "oms", "network", "planning", "design", "construction", "commissioning", "testing", "maintenance", "refurbishment", "upgrade", "expansion"],
    "agriculture": ["agriculture", "farming", "livestock", "crop", "agri", "food processing", "abattoir", "dairy", "poultry", "piggery", "aquaculture", "horticulture", "viticulture", "deciduous", "citrus", "subtropical", "grain", "maize", "wheat", "soybean", "sunflower"],
    "consulting": ["consulting", "advisory", "professional services", "feasibility", "due diligence", "valuation", "audit", "tax", "legal", "engineering", "environmental", "social", "impact assessment", "eia", "smp", "strategic management plan"],
    "marketing": ["marketing", "advertising", "branding", "communications", "pr", "media", "digital", "social media", "content", "creative", "design", "print", "broadcast", "outdoor", "ooh", "activation", "event"],
    "cleaning": ["cleaning", "hygiene", "sanitation", "waste", "facilities", "pest control", "waste management", "recycling", "environmental"],
    "legal": ["legal", "attorney", "conveyancing", "litigation", "law", "paralegal", "notary", "legal advisor"],
    "financial": ["financial", "accounting", "audit", "tax", "bookkeeping", "payroll", "insurance", "banking"],
    "property": ["property", "real estate", "conveyancing", "valuator", "facility management", "body corporate"],
    "mining": ["mining", "drilling", "geological", "mineral", "petroleum", "quarry", "drilling"],
    "manufacturing": ["manufacturing", "production", "assembly", "fabrication", "engineering"],
    "retail": ["retail", "supply", "procurement", "wholesale", "consumer goods"],
    "hospitality": ["hospitality", "catering", "hotel", "restaurant", "tourism", "events"],
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
]

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
            advert_date TEXT,
            closing_date TEXT,
            status TEXT DEFAULT 'open',
            source_url TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_tenders_sector ON tenders(sector);
        CREATE INDEX IF NOT EXISTS idx_tenders_province ON tenders(province);
        CREATE INDEX IF NOT EXISTS idx_tenders_closing ON tenders(closing_date);
        CREATE INDEX IF NOT EXISTS idx_tenders_status ON tenders(status);
        CREATE TABLE IF NOT EXISTS scrape_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            tenders_found INTEGER DEFAULT 0,
            tenders_saved INTEGER DEFAULT 0,
            status TEXT,
            error TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    db.commit()
    db.close()

def make_source_key(source, url):
    return hashlib.sha256(f"{source}:{url}".encode()).hexdigest()[:16]

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

def extract_dates(text):
    if not text:
        return None, None
    patterns = [
        (r'(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})', '%d %B %Y'),
        (r'(\d{4})-(\d{2})-(\d{2})', '%Y-%m-%d'),
        (r'(\d{2})/(\d{2})/(\d{4})', '%d/%m/%Y'),
        (r'(\d{2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})', '%d %b %Y'),
    ]
    dates_found = []
    for pattern, fmt in patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            try:
                dt = datetime.strptime(m.group(0), fmt).date()
                dates_found.append(dt)
            except ValueError:
                continue
    if len(dates_found) >= 2:
        return min(dates_found), max(dates_found)
    elif len(dates_found) == 1:
        return dates_found[0], None
    return None, None

def scrape_source(source_config):
    """Generic scraper for a tender source."""
    source_key = source_config["key"]
    url = source_config["list_url"]
    tenders = []
    
    headers = {"User-Agent": USER_AGENTS[hash(source_key) % len(USER_AGENTS)]}
    
    try:
        resp = requests.get(url, timeout=30, headers=headers)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Try multiple selectors for tender items
        rows = soup.select("table tbody tr")
        if not rows:
            rows = soup.select(".tender-item, .views-row, .list-item, .node--type-tender, article")
        if not rows:
            rows = soup.select("div[class*='tender'], div[class*='bid'], div[class*='rfq']")
        
        for row in rows:
            title_el = row.select_one("a, h3, h2, .title, .field-title")
            if not title_el:
                continue
            
            title = title_el.get_text(strip=True)
            if len(title) < 10 or len(title) > 500:
                continue
            
            link = title_el.get("href", "") if title_el.name == "a" else ""
            tender_url = urljoin(url, link) if link else url  # type: ignore
            
            # Extract text content
            text_content = row.get_text(separator=" ", strip=True)
            
            # Try to find department
            dept_el = row.select_one(".department, .field-department, .issuing-dept, td:nth-child(2)")
            dept = dept_el.get_text(strip=True) if dept_el else source_config["name"]
            
            # Try to find dates
            date_text = text_content
            advert_date, closing_date = extract_dates(date_text)
            
            # Determine sector
            sector = extract_sector(title + " " + text_content)
            
            tenders.append({
                "source": source_key,
                "source_key": make_source_key(source_key, tender_url),
                "title": title[:500],
                "description": text_content[:1000],
                "issuing_dept": dept[:300],
                "sector": sector,
                "province": source_config["name"],
                "advert_date": advert_date.isoformat() if advert_date else None,
                "closing_date": closing_date.isoformat() if closing_date else None,
                "status": "open",
                "source_url": tender_url[:1000],
            })
        
        print(f"  {source_key}: found {len(tenders)} tenders")
        
    except Exception as e:
        print(f"  {source_key}: FAILED - {e}")
    
    return tenders

def save_tenders(tenders):
    if not tenders:
        return 0
    db = get_db()
    saved = 0
    for t in tenders:
        try:
            db.execute("""
                INSERT OR IGNORE INTO tenders (source, source_key, title, description, issuing_dept, sector, province, advert_date, closing_date, status, source_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (t["source"], t["source_key"], t["title"], t["description"], t["issuing_dept"], t["sector"], t["province"], t["advert_date"], t["closing_date"], t["status"], t["source_url"]))
            saved += 1
        except Exception as e:
            pass
    db.commit()
    db.close()
    return saved

def log_scrape(source, found, saved, status, error=None):
    db = get_db()
    db.execute("INSERT INTO scrape_log (source, tenders_found, tenders_saved, status, error) VALUES (?, ?, ?, ?, ?)",
               (source, found, saved, status, error))
    db.commit()
    db.close()

def run():
    print(f"\n{'='*60}")
    print(f"  MOYA SCRAPER — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")
    
    ensure_tables()
    
    total_found = 0
    total_saved = 0
    
    for source in SOURCES:
        print(f"\n--- Scraping {source['name']} ---")
        tenders = scrape_source(source)
        saved = save_tenders(tenders)
        total_found += len(tenders)
        total_saved += saved
        log_scrape(source['key'], len(tenders), saved, 'success')
    
    print(f"\n{'='*60}")
    print(f"  COMPLETE: {total_found} found, {total_saved} new tenders saved")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    run()
