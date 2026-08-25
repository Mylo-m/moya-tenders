#!/usr/bin/env python3
"""
Moya — Document Engine (Proposal / Returnable Generator)
==============================================================
Formats proposal outputs to match standard public-sector returnables for the
two deployment hubs:

South Africa (ZA) — SBD forms (Standard Bidding Documents, National Treasury):
    SBD 1  — Invitation and instruction to bidders
    SBD 2  — Declaration of interest / conflict of interest
    SBD 3  — Pricing (schedule)
    SBD 4  — Declaration of bidder's past supply-chain management performance
    SBD 5  — Declaration of bidder's B-BBEE status
    SBD 6.1 — Preference points claim form (B-BBEE) — 90/10 or 80/20 pref
    SBD 7  — Declaration of companies / close corporations in the employ of
             the bidder (and CIDB register for construction)
    SBD 8  — Certificate of independent bid determination
    SBD 9  — Disclosure of directors / shareholders with public-sector employment

Kenya (KE) — PPADA-aligned bid returnables (Public Procurement and
             Asset Disposal Act, 2015):
    Cover / Form of Tender
    Confidential Business Questionnaire (CBQ)
    Tax Compliance (KRA TCC) & BRS evidence
    AGPO preference claim (if applicable)
    Priced Bill of Quantities / Schedule of Rates
    Technical proposal / company profile

This module produces a structured, ready-to-render DATA PACKAGE per tender bid.
The PHP layer (generate-pdf.php) renders it to PDF; for local verification here
we emit a Markdown pack.

Run:  python3 doc_engine.py --demo     # prints a sample ZA SBD pack + KE PPADA pack
"""

import argparse
from datetime import date


# ---------------------------------------------------------------------------
# TEMPLATES — field schemas per country/form
# ---------------------------------------------------------------------------
SBD_FORMS = {
    "SBD 1": {
        "title": "Invitation and Instruction to Bidders",
        "fields": ["bid_number", "bid_description", "closing_datetime", "bidder_name", "bidder_ref"],
    },
    "SBD 2": {
        "title": "Declaration of Interest (Conflict of Interest)",
        "fields": ["bidder_name", "declaration_text", "authorized_signatory", "date_signed"],
    },
    "SBD 3": {
        "title": "Pricing Schedule",
        "fields": ["bidder_name", "currency", "line_items[]", "total_excl_vat", "vat", "total_incl_vat"],
    },
    "SBD 4": {
        "title": "Declaration of Bidder's Past SCM Performance",
        "fields": ["bidder_name", "tax_clearance_pin", "no_terminal_scm_default", "declared_true"],
    },
    "SBD 5": {
        "title": "Declaration of Bidder's B-BBEE Status",
        "fields": ["bidder_name", "bbbee_level", "bbbee_cert_no", "bbbee_expiry", "is_affidavit"],
    },
    "SBD 6.1": {
        "title": "Preference Points Claim Form (B-BBEE) — 90/10 or 80/20",
        "fields": ["bidder_name", "pref_method", "bbbee_level", "points_claimed", "citizenship_sa"],
    },
    "SBD 7": {
        "title": "Companies / CCs in Employ of Bidder (incl. CIDB register)",
        "fields": ["bidder_name", "cidb_grade", "cidb_class", "related_companies[]"],
    },
    "SBD 8": {
        "title": "Certificate of Independent Bid Determination",
        "fields": ["bidder_name", "declaration_text", "authorized_signatory", "date_signed"],
    },
    "SBD 9": {
        "title": "Disclosure of Directors / Shareholders with Public-Sector Employment",
        "fields": ["bidder_name", "directors[]", "public_sector_links"],
    },
}

KE_PPADA_FORMS = {
    "Form of Tender": {
        "title": "Form of Tender (PPADA)",
        "fields": ["tender_ref", "procuring_entity", "bidder_name", "bid_amount_words", "bid_amount_figures", "validity_period", "date_signed"],
    },
    "Confidential Business Questionnaire (CBQ)": {
        "title": "Confidential Business Questionnaire",
        "fields": ["bidder_name", "brs_no", "kra_pin", "contact_person", "email", "postal_address", "year_established"],
    },
    "Tax & Registration Evidence": {
        "title": "KRA Tax Compliance Certificate + BRS Registration",
        "fields": ["kra_pin", "kra_tcc_no", "kra_tcc_expiry", "brs_no", "brs_cert_no"],
    },
    "AGPO Preference Claim": {
        "title": "AGPO Certificate (Youth / Women / PWD) — if applicable",
        "fields": ["agpo_category", "agpo_cert_no", "agpo_expiry", "claiming_preference"],
    },
    "Priced Schedule / BoQ": {
        "title": "Priced Bill of Quantities / Schedule of Rates",
        "fields": ["currency", "line_items[]", "total_excl_tax", "tax", "total_incl_tax"],
    },
    "Technical Proposal": {
        "title": "Technical Proposal / Company Profile",
        "fields": ["bidder_name", "similar_assignments[]", "key_personnel[]", "delivery_plan"],
    },
}

COUNTRY_TEMPLATE_MAP = {
    "ZA": ("South Africa — National Treasury SBD Forms", SBD_FORMS),
    "KE": ("Kenya — PPADA Bid Returnables", KE_PPADA_FORMS),
}


# ---------------------------------------------------------------------------
# Builder: turn a bid context into a render-ready data package
# ---------------------------------------------------------------------------
def build_bid_package(country_code, bid):
    """
    bid: dict with keys like bidder_name, bid_number, bbbee_level, cidb_grade,
         kra_pin, agpo_category, line_items (list of {desc, qty, amount}), ...
    Returns dict: {country, template_name, forms: [{name, title, fields, values}]}
    """
    if country_code not in COUNTRY_TEMPLATE_MAP:
        raise ValueError(f"No document template for country {country_code}")
    template_name, forms = COUNTRY_TEMPLATE_MAP[country_code]
    out_forms = []
    for name, spec in forms.items():
        values = {}
        for f in spec["fields"]:
            base = f.replace("[]", "")
            if base in bid:
                values[f] = bid[base]
            elif base == "date_signed":
                values[f] = bid.get("date_signed", date.today().isoformat())
            elif base == "currency":
                values[f] = bid.get("currency", "ZAR" if country_code == "ZA" else "KES")
            else:
                values[f] = bid.get(f, "")
        # compute totals for pricing forms
        if "line_items" in bid and "total_incl_vat" in spec["fields"]:
            items = bid["line_items"]
            excl = sum(i.get("amount", 0) * i.get("qty", 1) for i in items)
            vat_rate = bid.get("vat_rate", 0.15 if country_code == "ZA" else 0.16)
            vat = excl * vat_rate
            values["line_items[]"] = items
            values["total_excl_vat"] = round(excl, 2)
            values["vat"] = round(vat, 2)
            values["total_incl_vat"] = round(excl + vat, 2)
        if "line_items" in bid and "total_incl_tax" in spec["fields"]:
            items = bid["line_items"]
            excl = sum(i.get("amount", 0) * i.get("qty", 1) for i in items)
            tax_rate = bid.get("tax_rate", 0.16)
            tax = excl * tax_rate
            values["line_items[]"] = items
            values["total_excl_tax"] = round(excl, 2)
            values["tax"] = round(tax, 2)
            values["total_incl_tax"] = round(excl + tax, 2)
        out_forms.append({"name": name, "title": spec["title"], "fields": spec["fields"], "values": values})
    return {"country_code": country_code, "template_name": template_name, "forms": out_forms}


def render_markdown(pkg):
    lines = [f"# {pkg['template_name']}", f"Country: {pkg['country_code']}", ""]
    for f in pkg["forms"]:
        lines.append(f"## {f['name']} — {f['title']}")
        for field, val in f["values"].items():
            if isinstance(val, list):
                val = "; ".join(str(v) for v in val) if val else "(not provided)"
            lines.append(f"- **{field}**: {val if val != '' else '(not provided)'}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
def _demo():
    za_bid = {
        "bidder_name": "Cape Tech Solutions (Pty) Ltd",
        "bid_number": "RT8-2027",
        "bid_description": "Transportation of cargo and furniture relocation services",
        "closing_datetime": "2026-09-07 11:00",
        "tax_clearance_pin": "9123456789",
        "bbbee_level": "4",
        "bbbee_cert_no": "BBBEE12345",
        "bbbee_expiry": "2027-08-01",
        "is_affidavit": False,
        "pref_method": "80/20",
        "citizenship_sa": True,
        "cidb_grade": "9",
        "cidb_class": "GB",
        "currency": "ZAR",
        "line_items": [{"desc": "Cargo transport (36 months)", "qty": 1, "amount": 4500000}],
    }
    ke_bid = {
        "bidder_name": "Nairobi Digital Ltd",
        "tender_ref": "MOH/ICT/2026/045",
        "procuring_entity": "Ministry of Health",
        "bid_amount_words": "Forty million shillings",
        "bid_amount_figures": 40000000,
        "validity_period": "120 days",
        "brs_no": "CPR123456",
        "kra_pin": "A123456789B",
        "kra_tcc_no": "TCC998877",
        "kra_tcc_expiry": "2027-05-01",
        "brs_cert_no": "BN123456",
        "agpo_category": "WOMEN",
        "agpo_cert_no": "AGPO5566",
        "agpo_expiry": "2027-03-01",
        "claiming_preference": True,
        "currency": "KES",
        "line_items": [{"desc": "Health information system licensing", "qty": 1, "amount": 40000000}],
    }
    for cc, bid in (("ZA", za_bid), ("KE", ke_bid)):
        pkg = build_bid_package(cc, bid)
        print(render_markdown(pkg))
        print("=" * 70)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="Render sample ZA + KE bid packs")
    args = ap.parse_args()
    if args.demo:
        _demo()
    else:
        print("Pass --demo to render sample bid packs.")
