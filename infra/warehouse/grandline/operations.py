"""Voyage emissions, trucking subcontractors and jobs, warehouses and inventory, employees."""

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
from faker import Faker

from grandline import reference as ref

COORD = {p[0]: (p[5], p[6]) for p in ref.PORTS}
EU = {"NL", "BE", "DE", "FR", "ES", "IT", "GR", "PL"}
PORT_COUNTRY = {p[0]: p[2] for p in ref.PORTS}
CAPE_EXTRA_NM = {"AEX": 3300, "AMX": 2900}
CO2_FACTOR = {"LNG dual-fuel": 2.75, "Methanol dual-fuel": 1.375}  # t CO2 per t fuel; VLSFO 3.114
ETS_PHASE = {2024: 0.4, 2025: 0.7}  # share of emissions covered; 100% from 2026
INLAND = {
    "CN": ("Suzhou", "Hangzhou", "Dongguan", "Foshan", "Wuxi", "Chongqing", "Chengdu"),
    "US": ("Chicago", "Atlanta", "Dallas", "Memphis", "Columbus", "Charlotte", "Phoenix"),
    "DE": ("Duisburg", "Frankfurt", "Munich", "Stuttgart", "Cologne", "Leipzig"),
    "NL": ("Venlo", "Tilburg", "Utrecht", "Eindhoven"),
    "BE": ("Liege", "Ghent", "Brussels"),
    "GB": ("Birmingham", "Manchester", "Leeds", "London"),
    "ES": ("Madrid", "Zaragoza", "Barcelona"),
    "IT": ("Milan", "Turin", "Bologna"),
    "BR": ("Sao Paulo", "Campinas", "Curitiba"),
    "IN": ("Pune", "Ahmedabad", "Delhi"),
    "AE": ("Dubai Industrial City", "Abu Dhabi"),
}
DEPARTMENTS = {
    "Operations": ("Operations Coordinator", "Port Captain", "Vessel Planner", "Operations Manager"),
    "Commercial": ("Sales Executive", "Key Account Manager", "Pricing Analyst", "Trade Lane Manager"),
    "Customer Service": ("Customer Service Agent", "Documentation Specialist", "Team Lead"),
    "Finance": ("Accountant", "Credit Controller", "Financial Analyst", "Finance Manager"),
    "Equipment": ("Equipment Controller", "Reefer Technician", "Equipment Manager"),
    "Technology": ("Software Engineer", "Data Engineer", "Security Analyst", "IT Support Specialist"),
    "HSE and Compliance": ("Compliance Officer", "HSE Advisor", "Customs Specialist"),
    "Human Resources": ("HR Business Partner", "Recruiter", "Payroll Specialist"),
}
OFFICES = (("Rotterdam", 1.0), ("Singapore", 0.9), ("Dubai", 0.85), ("New York", 1.1),
           ("Santos", 0.55), ("Shanghai", 0.6))


def _nm(a: str, b: str) -> float:
    (la1, lo1), (la2, lo2) = COORD[a], COORD[b]
    p1, p2, dl = math.radians(la1), math.radians(la2), math.radians(lo2 - lo1)
    c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
    return 3440.1 * math.acos(max(-1.0, min(1.0, c)))


def build_emissions(voyages, vessels, bookings) -> pd.DataFrame:
    services = {s.code: s for s in ref.SERVICES}
    vinfo = vessels.set_index("vessel_id")
    teu = bookings[bookings["status"] != "cancelled"].groupby("voyage_id")["teu"].sum()
    rows = []
    for v in voyages[voyages["status"] == "completed"].itertuples(index=False):
        s = services[v.service_code]
        legs = s.headhaul if v.direction == "headhaul" else s.backhaul
        nm = sum(_nm(legs[i - 1][0], legs[i][0]) for i in range(1, len(legs))) * 1.18
        days = sum(d for _, d in legs)
        if v.routing != "standard":
            nm += CAPE_EXTRA_NM[s.code]
            days += s.cape_extra_days
        speed = nm / max(days * 24, 1)
        vessel = vinfo.loc[v.vessel_id]
        fuel = 0.08 * vessel.teu_capacity ** 0.75 * (speed / 16) ** 3 * days
        co2 = fuel * CO2_FACTOR.get(vessel.fuel_type, 3.114)
        carried = int(teu.get(v.voyage_id, 0))
        eu = any(PORT_COUNTRY[p] in EU for p, _ in legs)
        year = v.departure_date.year
        rows.append({
            "voyage_id": v.voyage_id, "distance_nm": int(nm), "avg_speed_knots": round(speed, 1),
            "fuel_consumed_mt": round(fuel, 1), "co2_tonnes": round(co2, 1), "teu_carried": carried,
            "co2_grams_per_teu_km": round(co2 * 1e6 / max(carried, 1) / (nm * 1.852), 2),
            "eu_ets_allowances": round(co2 * 0.5 * ETS_PHASE.get(year, 1.0), 1) if eu else 0.0,
        })
    return pd.DataFrame(rows)


def build_subcontractors(rng: np.random.Generator) -> pd.DataFrame:
    fake = Faker("en_US")
    fake.seed_instance(77)
    rows = []
    for i in range(1, 301):
        kind = rng.choice(["trucking", "trucking", "trucking", "rail", "depot", "terminal"])
        country = rng.choice(list(INLAND))
        suffix = {"trucking": "Haulage", "rail": "Rail Freight", "depot": "Container Depot",
                  "terminal": "Terminals"}[kind]
        rows.append({"subcontractor_id": i, "name": f"{fake.last_name()} {suffix}",
                     "service_type": kind, "country": country,
                     "performance_rating": round(float(np.clip(rng.normal(3.9, 0.6), 1.5, 5.0)), 1)})
    return pd.DataFrame(rows)


def build_trucking(bookings, subs, rng: np.random.Generator) -> pd.DataFrame:
    b = bookings[(bookings["status"] != "cancelled") & bookings["incoterm"].isin(["DAP", "DDP", "EXW"])]
    b = b[b["origin_port"].map(PORT_COUNTRY).isin(INLAND) | b["destination_port"].map(PORT_COUNTRY).isin(INLAND)]
    b = b.sample(n=min(len(b), 300_000), random_state=11)
    truckers = subs[subs["service_type"] == "trucking"]
    by_country = {c: g["subcontractor_id"].to_numpy() for c, g in truckers.groupby("country")}
    rows = []
    for r in b.itertuples(index=False):
        on = PORT_COUNTRY[r.destination_port] in INLAND and (
            r.incoterm in ("DAP", "DDP") or PORT_COUNTRY[r.origin_port] not in INLAND)
        port = r.destination_port if on else r.origin_port
        country = PORT_COUNTRY[port]
        pool = by_country.get(country, truckers["subcontractor_id"].to_numpy())
        base = pd.Timestamp(r.arrival if on and r.arrival is not None and not pd.isna(r.arrival)
                            else r.departure)
        sched = base + pd.Timedelta(hours=float(rng.uniform(24, 96))) if on else base - pd.Timedelta(days=float(rng.uniform(2, 5)))
        km = int(rng.gamma(2.5, 120))
        late = rng.gamma(1.2, 3.0)
        done = sched.tz_convert("UTC") < pd.Timestamp(ref.END, tz="UTC") if sched.tzinfo else sched < pd.Timestamp(ref.END)
        rows.append({
            "booking_id": r.booking_id, "subcontractor_id": int(rng.choice(pool)),
            "leg": "on_carriage" if on else "pre_carriage", "port_code": port,
            "inland_city": rng.choice(INLAND[country]) if country in INLAND else "Regional depot",
            "distance_km": km, "cost_usd": round(180 + km * rng.uniform(1.6, 2.6), 2),
            "scheduled_pickup": sched,
            "actual_pickup": sched + pd.Timedelta(hours=float(late)) if done else None,
            "status": "completed" if done else "planned",
        })
    df = pd.DataFrame(rows)
    df.insert(0, "job_id", np.arange(1, len(df) + 1))
    return df


def build_warehouses_inventory(customers, rng: np.random.Generator):
    sites = [("Rotterdam", "Netherlands"), ("Venlo", "Netherlands"), ("Antwerp", "Belgium"),
             ("Hamburg", "Germany"), ("Duisburg", "Germany"), ("Felixstowe", "United Kingdom"),
             ("Valencia", "Spain"), ("Genoa", "Italy"), ("Savannah", "United States"),
             ("Chicago", "United States"), ("Dallas", "United States"), ("Newark", "United States"),
             ("Los Angeles", "United States"), ("Singapore", "Singapore"), ("Shanghai", "China"),
             ("Shenzhen", "China"), ("Jebel Ali", "United Arab Emirates"), ("Santos", "Brazil"),
             ("Nhava Sheva", "India"), ("Port Klang", "Malaysia")]
    wh = pd.DataFrame([{"warehouse_id": i, "name": f"GL Logistics Centre {city}", "city": city,
                        "country": country, "capacity_pallets": int(rng.integers(8, 60)) * 1000}
                       for i, (city, country) in enumerate(sites, start=1)])
    top = customers[customers["segment"].isin(["strategic", "key"])]["customer_id"].to_numpy()[:220]
    cats = ("Consumer electronics", "Apparel", "Furniture", "Auto parts", "Food and beverage",
            "Household goods")
    weeks = pd.date_range("2024-01-07", ref.END.isoformat(), freq="W-SUN")
    rows = []
    for w in wh.itertuples(index=False):
        clients = rng.choice(top, size=8, replace=False)
        for c in clients:
            cat = cats[int(rng.integers(len(cats)))]
            level = rng.uniform(150, 2500)
            for k, day in enumerate(weeks):
                season = 1 + 0.35 * math.sin((day.dayofyear - 200) / 365 * 2 * math.pi)
                pallets = int(max(0, level * season * rng.normal(1, 0.08)))
                rows.append({"snapshot_date": day.date(), "warehouse_id": w.warehouse_id,
                             "customer_id": int(c), "product_category": cat, "pallets": pallets,
                             "stock_value_usd": round(pallets * rng.uniform(900, 4500), 2)})
    return wh, pd.DataFrame(rows)


def build_employees(rng: np.random.Generator, n: int = 6000) -> pd.DataFrame:
    fake = Faker(["en_US", "nl_NL", "en_GB", "de_DE"])
    fake.seed_instance(99)
    depts = list(DEPARTMENTS)
    rows, emails = [], set()
    for i in range(1, n + 1):
        dept = depts[int(rng.choice(len(depts), p=[0.28, 0.16, 0.18, 0.1, 0.08, 0.1, 0.05, 0.05]))]
        title = DEPARTMENTS[dept][int(rng.integers(len(DEPARTMENTS[dept])))]
        office, pay = OFFICES[int(rng.choice(len(OFFICES), p=[0.32, 0.22, 0.12, 0.14, 0.08, 0.12]))]
        name = fake.name()
        email = f"{name.lower().replace(' ', '.').replace(chr(39), '')}@grandline-shipping.example"
        while email in emails:
            email = email.replace("@", f"{int(rng.integers(10))}@")
        emails.add(email)
        senior = "Manager" in title or "Lead" in title
        salary = rng.normal(98_000 if senior else 62_000, 14_000) * pay
        rows.append({
            "employee_id": i, "full_name": name, "email": email, "department": dept,
            "job_title": title, "office": office,
            "hire_date": date(2008, 1, 1) + timedelta(days=int(rng.integers(0, 6800))),
            "salary_usd": round(max(salary, 24_000), -2),
            "manager_id": int(rng.integers(1, 200)) if i > 200 else None,
            "status": "active" if rng.random() > 0.06 else "left",
        })
    return pd.DataFrame(rows)
