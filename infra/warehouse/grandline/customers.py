"""Customers (shippers), annual contracts and their rate cards."""

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
from faker import Faker

from grandline import markets
from grandline import reference as ref

N_CUSTOMERS = 8000
# country, home region, weight, Faker locale, typical city prefixes for company names
COUNTRIES = (
    ("China", "Asia", 26, "en_US", ("Shanghai", "Ningbo", "Shenzhen", "Qingdao", "Xiamen",
                                    "Guangzhou", "Tianjin", "Suzhou", "Dongguan")),
    ("Vietnam", "Asia", 5, "en_US", ("Saigon", "Hanoi", "Binh Duong", "Haiphong")),
    ("India", "Asia", 5, "en_IN", ()),
    ("South Korea", "Asia", 4, "en_US", ("Busan", "Seoul", "Incheon", "Ulsan")),
    ("Japan", "Asia", 3, "en_US", ("Tokyo", "Osaka", "Nagoya", "Yokohama")),
    ("Singapore", "Asia", 2, "en_US", ("Jurong", "Tuas", "Pasir Panjang")),
    ("Thailand", "Asia", 2, "en_US", ("Bangkok", "Chonburi", "Rayong")),
    ("Malaysia", "Asia", 2, "en_US", ("Klang", "Penang", "Johor")),
    ("United States", "North America", 12, "en_US", ()),
    ("Canada", "North America", 1, "en_CA", ()),
    ("Germany", "Europe", 6, "de_DE", ()),
    ("Netherlands", "Europe", 4, "nl_NL", ()),
    ("United Kingdom", "Europe", 4, "en_GB", ()),
    ("France", "Europe", 3, "fr_FR", ()),
    ("Italy", "Europe", 3, "it_IT", ()),
    ("Spain", "Europe", 3, "es_ES", ()),
    ("Poland", "Europe", 1, "pl_PL", ()),
    ("Turkey", "Europe", 1, "tr_TR", ()),
    ("Brazil", "Latin America", 4, "pt_BR", ()),
    ("Argentina", "Latin America", 1, "es_AR", ()),
    ("Mexico", "Latin America", 1, "es_MX", ()),
    ("United Arab Emirates", "Middle East", 2, "en_US", ("Dubai", "Sharjah", "Abu Dhabi")),
    ("Saudi Arabia", "Middle East", 1, "en_US", ("Jeddah", "Riyadh", "Dammam")),
)
ASIA_SUFFIX = ("Trading Co., Ltd.", "Industrial Co., Ltd.", "Import & Export Co., Ltd.",
               "Manufacturing Co., Ltd.", "Logistics Co., Ltd.", "Corporation")
ASIA_WORDS = ("Golden", "Harmony", "Pacific", "Everbright", "Sunrise", "Prosper", "Jade",
              "Oriental", "Unity", "Starlight", "Evergreen", "Grandview", "Lotus", "Phoenix",
              "Silverline", "Fortune", "Lucky", "Bright", "Dragon", "Rising", "Crystal",
              "Maple", "Summit", "Ocean", "Hongxin", "Tianli", "Huamei", "Xinda", "Kaiyuan",
              "Minhua", "Yongsheng", "Dongfang", "Jinlong", "Shengtai")
ASIA_TRADES = ("Electronics", "Textile", "Furniture", "Hardware", "Plastics", "Toys",
               "Machinery", "Garments", "Lighting", "Ceramics", "Auto Parts", "Packaging")


@dataclass(frozen=True)
class Commercial:
    customers: pd.DataFrame
    contracts: pd.DataFrame
    rate_cards: pd.DataFrame


ME_WORDS = ("Al Noor", "Gulf Star", "Al Fajr", "Najd", "Al Safa", "Rawabi", "Al Waha",
            "Desert Rose", "Al Bahar", "Zayed", "Al Manara", "Falcon")
ME_SUFFIX = ("Trading LLC", "General Trading LLC", "Industries LLC", "Logistics FZE",
             "Group", "Import & Export LLC")
ME_CITIES = {"Dubai", "Sharjah", "Abu Dhabi", "Jeddah", "Riyadh", "Dammam"}


def _company(fake: Faker, rng: np.random.Generator, prefixes: tuple[str, ...]) -> str:
    if prefixes and prefixes[0] in ME_CITIES:
        p = prefixes[int(rng.integers(len(prefixes)))]
        w = ME_WORDS[int(rng.integers(len(ME_WORDS)))]
        return f"{w} {ME_SUFFIX[int(rng.integers(len(ME_SUFFIX)))]} ({p})"
    if prefixes:
        p = prefixes[int(rng.integers(len(prefixes)))]
        w = ASIA_WORDS[int(rng.integers(len(ASIA_WORDS)))]
        t = ASIA_TRADES[int(rng.integers(len(ASIA_TRADES)))]
        return f"{p} {w} {t} {ASIA_SUFFIX[int(rng.integers(len(ASIA_SUFFIX)))]}"
    return fake.company()


def build_customers(rng: np.random.Generator, n_employees: int) -> pd.DataFrame:
    weights = np.array([c[2] for c in COUNTRIES], dtype=float)
    picks = rng.choice(len(COUNTRIES), size=N_CUSTOMERS, p=weights / weights.sum())
    fakers = {loc: Faker(loc) for loc in {c[3] for c in COUNTRIES}}
    for i, f in enumerate(fakers.values()):
        f.seed_instance(1000 + i)
    rows, seen = [], set()
    for i, k in enumerate(picks, start=1):
        country, region, _, loc, prefixes = COUNTRIES[k]
        fake = fakers[loc]
        name = _company(fake, rng, prefixes)
        while name in seen:
            name = _company(fake, rng, prefixes)
        seen.add(name)
        segment = ("strategic" if i <= 60 else "key" if i <= 700
                   else "sme" if i <= 5200 else "spot")
        credit = {"strategic": 25e6, "key": 4e6, "sme": 4e5, "spot": 5e4}[segment]
        person = fakers["en_US"].name() if prefixes else fake.name()
        domain = "".join(ch for ch in name.lower().split()[0] if ch.isalnum()) or "company"
        rows.append({
            "customer_id": i,
            "name": name,
            "industry": ref.INDUSTRIES[int(rng.integers(len(ref.INDUSTRIES)))],
            "country": country,
            "segment": segment,
            "credit_limit_usd": round(credit * rng.uniform(0.6, 1.6), -3),
            "payment_terms_days": int(rng.choice([15, 30, 30, 45, 60])) if segment != "spot" else 0,
            "account_manager_id": int(rng.integers(1, n_employees + 1)) if segment != "spot" else None,
            "contact_name": person,
            "contact_email": f"{person.split()[0].lower()}.{i}@{domain}-example.com",
            "contact_phone": fake.phone_number(),
            "created_date": date(2015, 1, 1) + timedelta(days=int(rng.integers(0, 4100))),
            "home_region": region,
        })
    df = pd.DataFrame(rows)
    # shipping volume follows a long tail: a few giant accounts, many small ones
    df["volume_weight"] = 1.0 / np.arange(1, N_CUSTOMERS + 1) ** 0.75
    return df


def _lane_ports(service: ref.Service, direction: str) -> tuple[list[str], list[str]]:
    legs = service.headhaul if direction == "headhaul" else service.backhaul
    cut = max(range(1, len(legs)), key=lambda i: legs[i][1])
    origins = list(dict.fromkeys(p for p, _ in legs[:cut]))
    dests = [p for p in dict.fromkeys(p for p, _ in legs[cut:]) if p not in origins]
    return origins, dests


def lane_ports() -> dict[tuple[str, str], tuple[list[str], list[str]]]:
    return {(s.code, d): _lane_ports(s, d) for s in ref.SERVICES for d in ("headhaul", "backhaul")}


def build_contracts(customers: pd.DataFrame, rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    lanes = [s.lane for s in ref.SERVICES]
    service_of = {s.lane: s for s in ref.SERVICES}
    contracted = customers[customers["segment"].isin(["strategic", "key"])]
    contracts, cards = [], []
    cid = rid = 0
    for year in (2024, 2025, 2026):
        for c in contracted.itertuples(index=False):
            n_lanes = int(rng.integers(2, 5)) if c.segment == "strategic" else int(rng.integers(1, 3))
            for lane in rng.choice(lanes, size=n_lanes, replace=False):
                cid += 1
                start = date(year, 5, 1) if lane in ("TPW", "AUE") else date(year, 1, 1)
                end = date(year + 1, 4, 30) if lane in ("TPW", "AUE") else date(year, 12, 31)
                kind = "index_linked" if rng.random() < 0.35 else "fixed"
                committed = int((5000 if c.segment == "strategic" else 600) * rng.uniform(0.4, 2.2))
                contracts.append({
                    "contract_id": cid, "contract_number": f"GLC-{year}-{cid:05d}",
                    "customer_id": c.customer_id, "lane_code": lane, "contract_type": kind,
                    "start_date": start, "end_date": end, "committed_teu": committed,
                    "status": "expired" if end < ref.END else "active",
                })
                s = service_of[lane]
                discount = rng.uniform(0.78, 0.95) if c.segment == "strategic" else rng.uniform(0.88, 1.0)
                for direction in ("headhaul", "backhaul"):
                    origins, dests = _lane_ports(s, direction)
                    for o in origins:
                        for d in dests:
                            for ct in ("20DV", "40DV", "40HC", "40RF"):
                                rid += 1
                                spot = markets.spot_rate(lane, start - timedelta(days=45),
                                                         direction == "headhaul", ct)
                                cards.append({
                                    "rate_id": rid, "contract_id": cid, "origin_port": o,
                                    "destination_port": d, "container_type": ct,
                                    "base_rate_usd": round(spot * discount * rng.uniform(0.97, 1.03), 0),
                                    "valid_from": start, "valid_to": end,
                                })
    return pd.DataFrame(contracts), pd.DataFrame(cards)


def build(rng: np.random.Generator, n_employees: int) -> Commercial:
    customers = build_customers(rng, n_employees)
    contracts, cards = build_contracts(customers, rng)
    return Commercial(customers, contracts, cards)
