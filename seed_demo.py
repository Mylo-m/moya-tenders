#!/usr/bin/env python3
"""
Seed moya_data/moya.db with realistic demo tenders so the live Cloud Run demo
has real African-procurement data to show judges. Idempotent: clears + reseeds.

Run:  python3 seed_demo.py
"""
import os
import sqlite3

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "moya_data", "moya.db")
sqlite3.connect(DB).close()  # ensure file exists

ROWS = [
    ("ZA", "South Africa", "Southern Africa", "Gauteng", "construction",
     "Construction of Community Health Centre — Soweto",
     "New-build clinic with solar backup. B-BBEE Level 4, CIDB Grade 7.", "City of Johannesburg",
     "2026-09-15", "2026-09-30"),
    ("ZA", "South Africa", "Southern Africa", "Western Cape", "ict",
     "ICT Managed Services & Cybersecurity — Provincial Treasury",
     "SOC monitoring, endpoint protection, cloud posture review.", "Western Cape Treasury",
     "2026-08-28", "2026-10-05"),
    ("KE", "Kenya", "East Africa", None, "ict",
     "National e-GP Portal Upgrade (PPIP)",
     "API integration, procurement analytics dashboard.", "Kenya PPP Unit",
     "2026-08-20", "2026-10-12"),
    ("NG", "Nigeria", "West Africa", None, "energy",
     "Solar Mini-Grid Expansion — Kaduna State",
     "Design, supply, install 5 mini-grids. ISO 9001 required.", "Kaduna Energy Board",
     "2026-09-01", "2026-10-20"),
    ("ZA", "South Africa", "Southern Africa", "KwaZulu-Natal", "security",
     "Armed Response & CCTV Monitoring — eThekwini Municipality",
     "24/7 monitoring, PSIRA registered guards.", "eThekwini Municipality",
     "2026-08-25", "2026-09-28"),
    ("GH", "Ghana", "West Africa", None, "consulting",
     "Feasibility Study — Accra Waste-to-Energy Plant",
     "Technical + financial feasibility, EIA scoping.", "Ministry of Sanitation",
     "2026-09-05", "2026-11-01"),
    ("ZA", "South Africa", "Southern Africa", "Eastern Cape", "education",
     "Supply of ICT Lab Equipment — 40 Schools",
     "Laptops, smart boards, teacher training.", "Eastern Cape DOE",
     "2026-08-30", "2026-10-15"),
    ("TZ", "Tanzania", "East Africa", None, "logistics",
     "Medical Cold-Chain Logistics — Dar es Salaam",
     "Refrigerated transport, vaccine tracking system.", "TZ Medical Stores",
     "2026-09-10", "2026-10-25"),
    ("ZM", "Zambia", "Southern Africa", None, "agriculture",
     "Smallholder Irrigation Scheme — Lusaka Province",
     "Drip systems, boreholes, agronomy support.", "ZmAIS",
     "2026-09-02", "2026-10-18"),
    ("ZA", "South Africa", "Southern Africa", "Limpopo", "water",
     "Bulk Water Pipeline Rehabilitation — Polokwane",
     "Pipeline refurb, SCADA upgrade.", "Lepelle Water",
     "2026-08-22", "2026-09-26"),
    ("RW", "Rwanda", "East Africa", None, "ict",
     "National Digital ID Integration — Phase 2",
     "Biometric API, data-protection compliance.", "Rwanda NIDA",
     "2026-09-12", "2026-11-10"),
    ("MZ", "Mozambique", "Southern Africa", None, "energy",
     "Grid Electrification — Cabo Delgado (OCDS best-effort)",
     "Last-mile connections, metering.", "EDM",
     "2026-09-08", "2026-10-30"),
    ("ZA", "South Africa", "Southern Africa", "Free State", "financial",
     "Audit & Tax Compliance Services — Provincial Legislature",
     "IRR audit, SARS compliance pack.", "FS Legislature",
     "2026-08-26", "2026-10-08"),
    ("KE", "Kenya", "East Africa", None, "construction",
     "Affordable Housing Block — Kisumu",
     "200 units, B-BBEE-equivalent local content.", "Kisumu County",
     "2026-09-04", "2026-10-22"),
]


def main():
    db = sqlite3.connect(DB)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS tenders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL DEFAULT 'seed',
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
        """
    )
    db.execute("DELETE FROM tenders WHERE source='seed'")
    for i, (cc, country, region, prov, sector, title, desc, dept, adv, close) in enumerate(ROWS):
        db.execute(
            """INSERT INTO tenders
               (source, source_key, title, description, issuing_dept, sector, province,
                country, country_code, region, advert_date, closing_date, status)
               VALUES ('seed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
            (f"seed-{i}", title, desc, dept, sector, prov, country, cc, region, adv, close),
        )
    db.commit()
    n = db.execute("SELECT COUNT(*) c FROM tenders").fetchone()[0]
    db.close()
    print(f"SEEDED {len(ROWS)} demo tenders (total now {n}) -> {DB}")


if __name__ == "__main__":
    main()
