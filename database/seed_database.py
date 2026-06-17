"""
BRIGHTUITY — Simulated Bank Database Seeder
============================================
Generates 100 realistic clients for a fictional European digital bank
operating under EU MiCA. Outcomes are NEVER scripted: each client's
latent attributes (documents, KYC status, risk) drive what the agents
will decide when they read the data.

Distribution (natural, emergent):
  ~75% clean             -> pass all gates
  ~10% document issues   -> fail at Doc Auditor
  ~8%  PEP / sanctions   -> fail at KYC Guardian (hard governance halt)
  ~7%  elevated risk     -> fail at Stress-Test Simulator

Output: brightuity_clients.json  (drop-in for PostgreSQL ingestion later)

Deterministic: random.seed(42) -> same database every run (reproducible demos).
"""

import json
import random
import hashlib
from datetime import datetime, timedelta

random.seed(42)

# ----------------------------------------------------------------------------
# Name pools by country (gender-split) — European digital bank client base
# ----------------------------------------------------------------------------
COUNTRIES = {
    "Germany":     {"flag": "🇩🇪", "cities": ["Berlin", "Munich", "Frankfurt", "Hamburg"],
                    "male": ["Lukas Hoffmann", "Jonas Becker", "Felix Wagner", "Maximilian Krüger", "Elias Schmitt"],
                    "female": ["Anna Fischer", "Lena Weber", "Marie Schneider", "Laura Zimmermann", "Emilia Braun"]},
    "France":      {"flag": "🇫🇷", "cities": ["Paris", "Lyon", "Bordeaux", "Nice"],
                    "male": ["Antoine Moreau", "Julien Lefèvre", "Nicolas Garnier", "Thomas Roussel"],
                    "female": ["Camille Dubois", "Léa Fontaine", "Chloé Mercier", "Isabelle Laurent"]},
    "Greece":      {"flag": "🇬🇷", "cities": ["Athens", "Thessaloniki", "Patras"],
                    "male": ["Dimitris Papadopoulos", "Nikos Georgiou", "Kostas Nikolaidis"],
                    "female": ["Sofia Andreou", "Eleni Vasilakis", "Maria Economou"]},
    "Cyprus":      {"flag": "🇨🇾", "cities": ["Limassol", "Nicosia", "Larnaca"],
                    "male": ["Viktor Petrov", "Andreas Christou", "Stelios Ioannou"],
                    "female": ["Elena Charalambous", "Despina Antoniou"]},
    "Sweden":      {"flag": "🇸🇪", "cities": ["Stockholm", "Gothenburg", "Malmö"],
                    "male": ["Henrik Larsson", "Oskar Lindqvist", "Erik Johansson"],
                    "female": ["Astrid Nilsson", "Freja Andersson", "Ingrid Bergström"]},
    "Spain":       {"flag": "🇪🇸", "cities": ["Madrid", "Barcelona", "Valencia", "Seville"],
                    "male": ["Carlos Fernández", "Javier Morales", "Diego Navarro", "Alejandro Ruiz"],
                    "female": ["Lucía García", "Carmen Ortega", "Paula Jiménez", "Marta Delgado"]},
    "Italy":       {"flag": "🇮🇹", "cities": ["Milan", "Rome", "Florence", "Turin"],
                    "male": ["Marco Rossi", "Luca Bianchi", "Alessandro Conti", "Matteo Greco"],
                    "female": ["Giulia Ricci", "Francesca Romano", "Elena Marino", "Valentina Gallo"]},
    "Netherlands": {"flag": "🇳🇱", "cities": ["Amsterdam", "Rotterdam", "Utrecht"],
                    "male": ["Daan de Vries", "Sem Bakker", "Lucas Visser"],
                    "female": ["Emma Jansen", "Sophie van Dijk", "Julia Smit"]},
    "Portugal":    {"flag": "🇵🇹", "cities": ["Lisbon", "Porto", "Faro"],
                    "male": ["João Silva", "Tiago Costa", "Rui Almeida"],
                    "female": ["Inês Santos", "Beatriz Ferreira", "Mariana Oliveira"]},
    "Austria":     {"flag": "🇦🇹", "cities": ["Vienna", "Salzburg", "Graz"],
                    "male": ["Sebastian Gruber", "Florian Steiner"],
                    "female": ["Katharina Huber", "Magdalena Bauer"]},
    "Ireland":     {"flag": "🇮🇪", "cities": ["Dublin", "Cork", "Galway"],
                    "male": ["Liam O'Connor", "Sean Murphy", "Cian Walsh"],
                    "female": ["Aoife Kelly", "Niamh Byrne", "Saoirse Doyle"]},
    "Poland":      {"flag": "🇵🇱", "cities": ["Warsaw", "Kraków", "Gdańsk"],
                    "male": ["Jakub Kowalski", "Piotr Nowak", "Mateusz Wiśniewski"],
                    "female": ["Zofia Lewandowska", "Maja Wójcik", "Aleksandra Kamińska"]},
}

# ----------------------------------------------------------------------------
# Asset catalogue — realistic European market values (EUR)
# ----------------------------------------------------------------------------
ASSET_TYPES = [
    {"type": "Commercial Property", "details": ["Office building", "Retail complex", "Logistics warehouse", "Mixed-use building"],
     "range": (1_200_000, 8_500_000)},
    {"type": "Residential Property", "details": ["Apartment", "Townhouse", "Penthouse"],
     "range": (450_000, 2_200_000)},
    {"type": "Luxury Villa", "details": ["Seafront estate", "Mountain chalet", "Vineyard estate"],
     "range": (2_500_000, 9_000_000)},
    {"type": "Gold Reserve", "details": ["Allocated bullion, 20kg", "Allocated bullion, 40kg", "Allocated bullion, 75kg"],
     "range": (1_300_000, 4_900_000)},
    {"type": "Private Equity", "details": ["Fund stake", "Growth fund position", "Infrastructure fund stake"],
     "range": (800_000, 5_000_000)},
    {"type": "Fine Art Collection", "details": ["Modern art portfolio", "Classical collection"],
     "range": (600_000, 3_500_000)},
]

SOURCES_OF_FUNDS = ["Business income", "Inheritance", "Property sale proceeds",
                    "Investment returns", "Salary accumulation", "Company exit / acquisition"]

SUSPICIOUS_SOURCES = ["Unverifiable offshore structures", "Undisclosed third-party transfers",
                      "Shell company dividends — opaque ownership"]

DOC_ISSUES = ["Title deed missing notarization", "Valuation report expired (>12 months)",
              "Ownership chain incomplete — prior transfer undocumented",
              "Registry extract inconsistent with deed", "Signature mismatch across documents"]

RISK_FLAGS = ["Valuation 35% above market comparables", "Illiquid micro-market — no sales in 18 months",
              "Concentration risk — single-tenant dependency", "Currency exposure — non-EUR rental income"]

# randomuser.me portrait pools (gender-matched, stable URLs)
MALE_PHOTOS = list(range(10, 90))
FEMALE_PHOTOS = list(range(10, 90))
random.shuffle(MALE_PHOTOS)
random.shuffle(FEMALE_PHOTOS)

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def doc_id(seed_text: str) -> str:
    """Opaque encrypted-style document reference (what Band sees)."""
    h = hashlib.sha256(seed_text.encode()).hexdigest().upper()
    return f"{h[0:4]}-{h[4:8]}-{h[8:12]}"

def passport_number(country: str, idx: int) -> str:
    prefix = {"Germany": "C", "France": "F", "Greece": "AK", "Cyprus": "K",
              "Sweden": "S", "Spain": "PAB", "Italy": "YA", "Netherlands": "NX",
              "Portugal": "P", "Austria": "U", "Ireland": "PC", "Poland": "ZS"}.get(country, "X")
    return f"{prefix}{random.randint(1000000, 9999999)}"

def birth_date() -> str:
    start = datetime(1958, 1, 1)
    days = random.randint(0, (datetime(1998, 12, 31) - start).days)
    return (start + timedelta(days=days)).strftime("%Y-%m-%d")

def submitted_at(days_back_max=14) -> str:
    dt = datetime(2026, 6, 12) - timedelta(days=random.randint(0, days_back_max),
                                           hours=random.randint(0, 23),
                                           minutes=random.randint(0, 59))
    return dt.isoformat()

male_i, female_i = 0, 0
def photo_url(gender: str) -> str:
    global male_i, female_i
    if gender == "male":
        n = MALE_PHOTOS[male_i % len(MALE_PHOTOS)]; male_i += 1
        return f"https://randomuser.me/api/portraits/men/{n}.jpg"
    n = FEMALE_PHOTOS[female_i % len(FEMALE_PHOTOS)]; female_i += 1
    return f"https://randomuser.me/api/portraits/women/{n}.jpg"

# ----------------------------------------------------------------------------
# Profile builders — latent attributes that AGENTS will discover
# ----------------------------------------------------------------------------
def clean_profile():
    return {
        "documents_status": "complete", "document_issues": [],
        "kyc_status": "clean", "kyc_flags": [],
        "source_of_funds": random.choice(SOURCES_OF_FUNDS),
        "source_verifiable": True,
        "risk_flags": [],
        "expected_outcome": "approve",   # for our testing only — agents never see this field name meaningfully
    }

def doc_issue_profile():
    p = clean_profile()
    p["documents_status"] = "issues"
    p["document_issues"] = random.sample(DOC_ISSUES, k=random.choice([1, 2]))
    p["expected_outcome"] = "reject_documents"
    return p

def pep_profile():
    p = clean_profile()
    p["kyc_status"] = random.choice(["pep_match", "sanctions_adjacent"])
    p["kyc_flags"] = (["PEP match — politically exposed network"] if p["kyc_status"] == "pep_match"
                      else ["Indirect link to sanctioned entity (ownership chain)"])
    p["source_of_funds"] = random.choice(SUSPICIOUS_SOURCES)
    p["source_verifiable"] = False
    p["expected_outcome"] = "reject_kyc"
    return p

def high_risk_profile():
    p = clean_profile()
    p["risk_flags"] = random.sample(RISK_FLAGS, k=random.choice([1, 2]))
    p["expected_outcome"] = "reject_risk"
    return p

# ----------------------------------------------------------------------------
# Generate the 100 clients
# ----------------------------------------------------------------------------
clients = []

# ---- 3 anchor clients (used in the frontend demo — fixed attributes) ----
ANCHORS = [
    {"name": "Marcus Weber", "gender": "male", "country": "Germany", "city": "Berlin",
     "asset": {"type": "Commercial Property", "detail": "Office building", "value": 2_000_000},
     "profile": clean_profile(), "request_id": "REQ-2041", "status": "pending",
     "photo": "https://randomuser.me/api/portraits/men/32.jpg"},
    {"name": "Sofia Andreou", "gender": "female", "country": "Greece", "city": "Athens",
     "asset": {"type": "Residential Property", "detail": "Apartment", "value": 800_000},
     "profile": doc_issue_profile(), "request_id": "REQ-2042", "status": "pending",
     "photo": "https://randomuser.me/api/portraits/women/44.jpg"},
    {"name": "Viktor Petrov", "gender": "male", "country": "Cyprus", "city": "Limassol",
     "asset": {"type": "Luxury Villa", "detail": "Seafront estate", "value": 5_000_000},
     "profile": pep_profile(), "request_id": "REQ-2043", "status": "pending",
     "photo": "https://randomuser.me/api/portraits/men/67.jpg"},
]
# Force Viktor to the canonical PEP story used in the demo
ANCHORS[2]["profile"]["kyc_status"] = "pep_match"
ANCHORS[2]["profile"]["kyc_flags"] = ["PEP match — politically exposed network"]
ANCHORS[2]["profile"]["source_of_funds"] = "Unverifiable offshore structures"

for a in ANCHORS:
    cid = len(clients) + 1
    clients.append({
        "client_id": f"CLT-{cid:04d}",
        "request_id": a["request_id"],
        "encrypted_doc_id": doc_id(a["name"] + a["request_id"]),
        "full_name": a["name"],
        "gender": a["gender"],
        "nationality": a["country"],
        "country_flag": COUNTRIES[a["country"]]["flag"],
        "date_of_birth": birth_date(),
        "passport_number": passport_number(a["country"], cid),
        "address": f"{random.randint(2, 180)} {random.choice(['Hauptstraße', 'Avenue', 'Street', 'Boulevard'])}, {a['city']}",
        "photo_url": a["photo"],
        "asset_type": a["asset"]["type"],
        "asset_detail": f"{a['asset']['detail']}, {a['city']}",
        "asset_value_eur": a["asset"]["value"],
        "submitted_at": submitted_at(2),
        "status": a["status"],
        **a["profile"],
    })

# ---- remaining 97 clients with natural distribution ----
# 75 clean total (3 anchors: 1 clean) -> 74 more clean
# 10 doc issues total (1 anchor)      -> 9 more
# 8 PEP total (1 anchor)              -> 7 more
# 7 high risk total                   -> 7 more
profile_queue = (["clean"] * 74) + (["docs"] * 9) + (["pep"] * 7) + (["risk"] * 7)
random.shuffle(profile_queue)

country_names = list(COUNTRIES.keys())
used_names = {a["name"] for a in ANCHORS}

for kind in profile_queue:
    cid = len(clients) + 1
    # pick country + unique name
    while True:
        country = random.choice(country_names)
        gender = random.choice(["male", "female"])
        pool = COUNTRIES[country][gender]
        name = random.choice(pool)
        if name not in used_names:
            used_names.add(name)
            break
        # name collision: try modifying with middle initial to keep pools small but names unique
        initial = chr(random.randint(65, 90))
        candidate = name.replace(" ", f" {initial}. ", 1)
        if candidate not in used_names:
            used_names.add(candidate)
            name = candidate
            break

    city = random.choice(COUNTRIES[country]["cities"])
    asset_cls = random.choice(ASSET_TYPES)
    detail = random.choice(asset_cls["details"])
    value = round(random.randint(*asset_cls["range"]), -4)  # round to 10k

    profile = {"clean": clean_profile, "docs": doc_issue_profile,
               "pep": pep_profile, "risk": high_risk_profile}[kind]()

    # request lifecycle: a living bank book
    # GOVERNANCE CONSISTENCY: processed history must respect the gates —
    # a PEP/doc-issue/high-risk client can never appear as "approved"
    r = random.random()
    if r < 0.07:
        status = "pending"            # in the queue right now
    elif r < 0.22:
        if profile["expected_outcome"] == "approve":
            # clean clients: mostly approved; occasionally rejected by the human
            # (business-judgment rejection — perfectly legitimate)
            status = "approved" if random.random() < 0.85 else "rejected"
        else:
            status = "rejected"       # gated clients are ALWAYS rejected in history
    else:
        status = "not_yet_arrived"    # arrives over time via the backend seeder

    clients.append({
        "client_id": f"CLT-{cid:04d}",
        "request_id": f"REQ-{2000 + cid + 43}",
        "encrypted_doc_id": doc_id(name + str(cid)),
        "full_name": name,
        "gender": gender,
        "nationality": country,
        "country_flag": COUNTRIES[country]["flag"],
        "date_of_birth": birth_date(),
        "passport_number": passport_number(country, cid),
        "address": f"{random.randint(2, 180)} {random.choice(['Hauptstraße', 'Rue de la Paix', 'High Street', 'Avenida Central', 'Via Roma', 'Gran Vía'])}, {city}",
        "photo_url": photo_url(gender),
        "asset_type": asset_cls["type"],
        "asset_detail": f"{detail}, {city}",
        "asset_value_eur": value,
        "submitted_at": submitted_at(14),
        "status": status,
        **profile,
    })

# ----------------------------------------------------------------------------
# Write output + summary
# ----------------------------------------------------------------------------
db = {
    "bank": {
        "name": "Digital Assets & Tokenization Division",
        "type": "European digital bank (fictional — simulation)",
        "jurisdiction": "European Union",
        "regulatory_framework": "MiCA / AMLD5",
        "division": "Digital Assets & Tokenization Division",
        "head_of_division": "Nevine AKF",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "note": "All data is synthetic. Outcomes emerge from client attributes — never scripted.",
    },
    "clients": clients,
}

with open("brightuity_clients.json", "w", encoding="utf-8") as f:
    json.dump(db, f, ensure_ascii=False, indent=2)

# summary
from collections import Counter
outcomes = Counter(c["expected_outcome"] for c in clients)
statuses = Counter(c["status"] for c in clients)
countries_c = Counter(c["nationality"] for c in clients)

print("=" * 60)
print("BRIGHTUITY DATABASE SEEDED — 100 clients")
print("=" * 60)
print(f"\nLatent outcome distribution (what agents will discover):")
for k, v in outcomes.most_common():
    print(f"  {k:20s} {v}")
print(f"\nRequest lifecycle status:")
for k, v in statuses.most_common():
    print(f"  {k:20s} {v}")
print(f"\nCountries: {len(countries_c)} — {dict(countries_c.most_common(5))} ...")
print(f"\nAnchor demo clients:")
for c in clients[:3]:
    print(f"  {c['request_id']} {c['full_name']:18s} {c['asset_type']:22s} -> {c['expected_outcome']}")
print(f"\nOutput: brightuity_clients.json ({len(json.dumps(db)) // 1024} KB)")
