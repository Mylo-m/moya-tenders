#!/usr/bin/env python3
"""Seed the Moya talent graph with 10 realistic demo people/companies.

Idempotent: skips if the pool already has >=10 rows. The contacts are clearly
demo handles (not real personal data). Run from the repo root:
    python3 moya_data/seed_talent.py
"""
from __future__ import annotations

import json

from talent_db import add_talent, talent_count

# Each entry: realistic African ICT/procurement talent with real cert names.
# (costs/day in ZAR are illustrative demo values)
SEED = [
    dict(name="Thabo Mokoena", type="individual", country_code="ZA", province="Gauteng",
         skills=json.dumps(["q-sys", "crestron", "av-design"]),
         certs=json.dumps({"cidb": "9", "bbee": "1", "qsys": True, "crestron": True}),
         languages=json.dumps(["en", "zu"]), rate_day=4500, available=1,
         contact="thabo.demo@moya.example",
         bio="Lead AV integrator, 12 yrs. CIDB 9, B-BBEE Level 1. Q-SYS & Crestron certified."),
    dict(name="Naledi Smart Systems (Pty) Ltd", type="company", country_code="ZA", province="Western Cape",
         skills=json.dumps(["structured-cabling", "cctv", "networking", "cisco"]),
         certs=json.dumps({"cidb": "7", "bbee": "2", "cisco": True, "psira": True}),
         languages=json.dumps(["en", "af"]), rate_day=9000, available=1,
         contact="projects@naledi-demo.example",
         bio="Cape Town SI: structured cabling, CCTV, Cisco networking. PSIRA registered, CIDB 7."),
    dict(name="Aisha Khan", type="individual", country_code="ZA", province="KwaZulu-Natal",
         skills=json.dumps(["project-management", "compliance", "bid-writing"]),
         certs=json.dumps({"bbee": "1", "pmp": True, "csd": True}),
         languages=json.dumps(["en", "zu"]), rate_day=3500, available=1,
         contact="aisha.demo@moya.example",
         bio="Bid manager & compliance lead. PMP, CSD registered, B-BBEE Level 1 specialist."),
    dict(name="Sipho Dlamini", type="individual", country_code="ZA", province="Gauteng",
         skills=json.dumps(["solar-pv", "electrical", "epc"]),
         certs=json.dumps({"cidb": "8", "bbee": "3", "electrical-license": True}),
         languages=json.dumps(["en", "zu"]), rate_day=5000, available=1,
         contact="sipho.demo@moya.example",
         bio="EPC electrical engineer, solar PV. Licensed, CIDB 8, B-BBEE Level 3."),
    dict(name="Wanjiru Tech Solutions", type="company", country_code="KE", province="Nairobi",
         skills=json.dumps(["software", "cloud", "data", "gcp"]),
         certs=json.dumps({"agpo": True, "iso": "9001"}),
         languages=json.dumps(["en", "sw"]), rate_day=7000, available=1,
         contact="bids@wanjiru-demo.example",
         bio="Nairobi software/SaaS firm, AGPO-certified, ISO 9001. GCP & data engineering."),
    dict(name="Brian Otieno", type="individual", country_code="KE", province="Nairobi",
         skills=json.dumps(["networking", "cybersecurity", "cisco"]),
         certs=json.dumps({"cisco": True, "isc2": True}),
         languages=json.dumps(["en", "sw"]), rate_day=4000, available=1,
         contact="brian.demo@moya.example",
         bio="Cybersecurity engineer, CCNP + CISSP. Nairobi-based, AGPO eligible."),
    dict(name="Adaeze Okafor", type="individual", country_code="NG", province="Lagos",
         skills=json.dumps(["fiber", " osp", "civil-works"]),
         certs=json.dumps({"cidb": "6", "iso": "14001"}),
         languages=json.dumps(["en", "yo"]), rate_day=4200, available=1,
         contact="adaeze.demo@moya.example",
         bio="Fibre/OSP civil works lead, Lagos. ISO 14001, CIDB 6 equivalent."),
    dict(name="Lagos Digital Infrastructure Ltd", type="company", country_code="NG", province="Lagos",
         skills=json.dumps(["data-centre", "power", "cooling", "structured-cabling"]),
         certs=json.dumps({"iso": "9001", "cidb": "9"}),
         languages=json.dumps(["en", "yo"]), rate_day=11000, available=1,
         contact="tenders@lagosdi-demo.example",
         bio="Data-centre builder: power, cooling, cabling. CIDB 9, ISO 9001."),
    dict(name="Lerato Molefe", type="individual", country_code="ZA", province="Free State",
         skills=json.dumps(["hvac", "refrigeration", "facilities"]),
         certs=json.dumps({"bbee": "2", "cidb": "5"}),
         languages=json.dumps(["en", "st"]), rate_day=3000, available=1,
         contact="lerato.demo@moya.example",
         bio="HVAC & facilities tech, Free State. CIDB 5, B-BBEE Level 2."),
    dict(name="Kwame Asante", type="individual", country_code="ZA", province="Gauteng",
         skills=json.dumps(["ui-ux", "frontend", "accessibility"]),
         certs=json.dumps({"bbee": "1"}),
         languages=json.dumps(["en", "zu"]), rate_day=3200, available=1,
         contact="kwame.demo@moya.example",
         bio="Accessible UI/frontend dev. B-BBEE Level 1. WCAG specialist."),
]


def main():
    if talent_count() >= 10:
        print(f"talent pool already has {talent_count()} rows — skipping seed.")
        return
    for e in SEED:
        add_talent(**e)
    print(f"seeded {len(SEED)} talent rows (total now {talent_count()}).")


if __name__ == "__main__":
    main()
