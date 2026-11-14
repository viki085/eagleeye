"""Invoices and invoice lines, claims, and bunker fuel purchases."""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from grandline import markets
from grandline import reference as ref

EU_COUNTRIES = {"NL", "BE", "DE", "FR", "ES", "IT", "GR", "PL"}
PORT_COUNTRY = {p[0]: p[2] for p in ref.PORTS}
CHARGES = {
    "OFR": "Ocean freight",
    "BAF": "Bunker adjustment factor",
    "THC": "Terminal handling charge",
    "DOC": "Documentation fee",
    "PSS": "Peak season surcharge",
    "CTG": "Contingency surcharge (Red Sea diversion)",
    "ETS": "EU Emissions Trading System surcharge",
    "DGS": "Dangerous goods surcharge",
    "DND": "Demurrage and detention",
}
BUNKER_PORTS = ("SGSIN", "NLRTM", "AEJEA", "CNSHA", "USHOU", "PABLB", "ESALG", "BRSSZ", "KRPUS")
BUNKER_SUPPLIERS = ("Straits Marine Fuels", "North Sea Bunkering", "Gulf Energy Marine",
                    "Pacific Rim Bunkers", "Atlantic Fuel Supply")


def _today() -> date:
    return ref.END + timedelta(days=14)


def build_invoices(bookings: pd.DataFrame, customers: pd.DataFrame, rng: np.random.Generator):
    b = bookings[bookings["status"].isin(["shipped", "delivered"])].copy()
    terms = customers.set_index("customer_id")["payment_terms_days"]
    n = len(b)
    dep = pd.to_datetime(b["departure"], utc=True).dt.date.to_numpy()
    inv_date = np.array([d + timedelta(days=int(x)) for d, x in zip(dep, rng.integers(0, 4, n))])
    t = terms.loc[b["customer_id"]].to_numpy()
    due = np.array([d + timedelta(days=int(x)) for d, x in zip(inv_date, np.maximum(t, 7))])
    lines = _lines(b, rng)
    totals = lines.groupby("_row")["amount_usd"].sum()
    inv = pd.DataFrame({
        "invoice_id": np.arange(1, n + 1),
        "booking_id": b["booking_id"].to_numpy(),
        "customer_id": b["customer_id"].to_numpy(),
        "invoice_date": inv_date, "due_date": due,
        "amount_usd": np.round(totals.reindex(range(n)).to_numpy(), 2),
    })
    inv.insert(1, "invoice_number",
               [f"GLI-{d.year}-{i:07d}" for d, i in zip(inv_date, inv["invoice_id"])])
    inv = _payment_status(inv, rng)
    lines["invoice_id"] = lines["_row"] + 1
    return inv, lines.drop(columns="_row")[["invoice_id", "line_no", "charge_code", "description",
                                            "amount_usd"]]


def _lines(b: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    n = len(b)
    rows = np.arange(n)
    count = b["container_count"].to_numpy()
    feu = b["teu"].to_numpy() / 2
    day = pd.to_datetime(b["cargo_ready_date"]).to_numpy()
    eu = b["origin_port"].map(PORT_COUNTRY).isin(EU_COUNTRIES) | b["destination_port"].map(
        PORT_COUNTRY).isin(EU_COUNTRIES)
    cape = (b["routing"] != "standard").to_numpy()
    baf = markets.vlsfo_price(day) * np.where(cape, 1.05, 0.7) * feu
    parts = [
        ("OFR", rows, b["freight_revenue_usd"].to_numpy()),
        ("BAF", rows, baf),
        ("THC", rows, count * rng.uniform(160, 320, n)),
        ("DOC", rows, np.full(n, 75.0)),
    ]
    months = pd.DatetimeIndex(day).month
    pss = b["headhaul"].to_numpy() & np.isin(months, [8, 9, 10])
    parts.append(("PSS", rows[pss], (feu * rng.uniform(300, 700, n))[pss]))
    ctg = cape & b["lane"].isin(["AEU", "AMD"]).to_numpy()
    parts.append(("CTG", rows[ctg], (feu * rng.uniform(500, 1400, n))[ctg]))
    years = pd.DatetimeIndex(day).year.to_numpy()
    ets_rate = np.select([years == 2024, years == 2025], [14.0, 26.0], 38.0)
    parts.append(("ETS", rows[eu.to_numpy()], (feu * ets_rate)[eu.to_numpy()]))
    dg = b["is_hazardous"].to_numpy()
    parts.append(("DGS", rows[dg], (count * rng.uniform(150, 400, n))[dg]))
    dnd = rng.random(n) < 0.07
    parts.append(("DND", rows[dnd], (count * rng.gamma(2.0, 220, n))[dnd]))
    df = pd.concat([pd.DataFrame({"_row": r, "charge_code": c, "amount_usd": np.round(a, 2)})
                    for c, r, a in parts], ignore_index=True)
    df = df.sort_values(["_row"], kind="stable")
    df["line_no"] = df.groupby("_row").cumcount() + 1
    df["description"] = df["charge_code"].map(CHARGES)
    return df


def _payment_status(inv: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    n = len(inv)
    today = _today()
    lateness = np.rint(rng.normal(3, 12, n)).astype(int)
    paid = np.array([d + timedelta(days=int(x)) for d, x in zip(inv["due_date"], lateness)])
    disputed = rng.random(n) < 0.015
    written_off = rng.random(n) < 0.002
    never = rng.random(n) < 0.01  # chronic late payers
    is_paid = (paid <= today) & ~disputed & ~written_off & ~never
    status = np.where(is_paid, "paid",
                      np.where(disputed, "disputed",
                               np.where(written_off & (inv["due_date"] < today - timedelta(days=180)),
                                        "written_off",
                                        np.where(inv["due_date"] < today, "overdue", "open"))))
    inv["status"] = status
    inv["paid_date"] = np.where(is_paid, paid, None)
    return inv


def build_claims(bookings, bc, fleet, rng: np.random.Generator) -> pd.DataFrame:
    delivered = bookings[bookings["status"] == "delivered"]
    lessor = fleet.set_index("container_number")["lessor"]
    bad = bc[bc["container_number"].map(lessor).eq(ref.REEFER_FAULT_LESSOR)
             & bc["container_type"].str.endswith("RF")]["booking_id"].unique()
    ready = delivered["cargo_ready_date"]
    fault = delivered["booking_id"].isin(bad) & ready.between(*ref.REEFER_FAULT)
    p = np.where(fault, 0.22, np.where(delivered["is_reefer"], 0.02, 0.009))
    c = delivered[rng.random(len(delivered)) < p].copy()
    n = len(c)
    fault_c = c["booking_id"].isin(bad) & c["cargo_ready_date"].between(*ref.REEFER_FAULT)
    kinds = rng.choice(["Cargo damage", "Shortage", "Delay", "Contamination", "Theft"], n,
                       p=[0.45, 0.2, 0.2, 0.1, 0.05])
    kinds = np.where(c["is_reefer"] & (rng.random(n) < 0.7), "Reefer temperature deviation", kinds)
    kinds = np.where(fault_c, "Reefer temperature deviation", kinds)
    arrival = pd.to_datetime(c["arrival"], utc=True).dt.date.to_numpy()
    filed = np.array([d + timedelta(days=int(x)) for d, x in zip(arrival, rng.integers(2, 40, n))])
    claimed = np.round(c["freight_revenue_usd"].to_numpy() * rng.uniform(0.6, 6.0, n), 2)
    today = _today()
    age = np.array([(today - f).days for f in filed])
    settled = (age > 45) & (rng.random(n) < 0.8)
    rejected = settled & (rng.random(n) < 0.22)
    status = np.where(rejected, "rejected", np.where(settled, "settled", "open"))
    root = np.where(fault_c, "Faulty reefer controller (Coldline Leasing batch CL-2207)",
                    np.where(kinds == "Reefer temperature deviation", "Power interruption at terminal",
                             None))
    return pd.DataFrame({
        "claim_id": np.arange(1, n + 1),
        "claim_number": [f"GLCL-{f.year}-{i:05d}" for f, i in zip(filed, range(1, n + 1))],
        "booking_id": c["booking_id"].to_numpy(), "customer_id": c["customer_id"].to_numpy(),
        "claim_type": kinds, "filed_date": filed, "claimed_amount_usd": claimed,
        "settled_amount_usd": np.where(status == "settled",
                                       np.round(claimed * rng.uniform(0.35, 0.95, n), 2), None),
        "status": status,
        "settled_date": np.where(status != "open",
                                 [f + timedelta(days=int(x)) for f, x in zip(filed, rng.integers(30, 120, n))],
                                 None),
        "root_cause": root,
    })


def build_bunkers(voyages: pd.DataFrame, emissions: pd.DataFrame, vessels: pd.DataFrame,
                  rng: np.random.Generator) -> pd.DataFrame:
    v = voyages.merge(emissions[["voyage_id", "fuel_consumed_mt"]], on="voyage_id")
    v = v[v["status"] == "completed"]
    fuel = vessels.set_index("vessel_id")["fuel_type"]
    rows = []
    for r in v.itertuples(index=False):
        stops = 1 if r.fuel_consumed_mt < 2500 else 2
        for k in range(stops):
            day = r.departure_date + timedelta(days=int(rng.integers(0, 10)) + 12 * k)
            grade = {"LNG dual-fuel": "LNG", "HSFO with scrubber": "HSFO"}.get(fuel[r.vessel_id], "VLSFO")
            price = float(markets.vlsfo_price([day])[0])
            price *= {"LNG": 1.05, "HSFO": 0.78}.get(grade, 1.0) * rng.uniform(0.96, 1.05)
            rows.append({
                "vessel_id": r.vessel_id,
                "port_code": BUNKER_PORTS[int(rng.integers(len(BUNKER_PORTS)))],
                "purchase_date": day, "fuel_grade": grade,
                "quantity_mt": round(r.fuel_consumed_mt / stops * rng.uniform(0.9, 1.1), 1),
                "price_usd_per_mt": round(price, 2),
                "supplier": BUNKER_SUPPLIERS[int(rng.integers(len(BUNKER_SUPPLIERS)))],
            })
    df = pd.DataFrame(rows)
    df.insert(0, "purchase_id", np.arange(1, len(df) + 1))
    return df
