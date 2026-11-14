"""Deterministic documents built straight from warehouse rows: contracts and agreements."""

from datetime import date, timedelta

PORT_NAMES: dict[str, str] = {}  # filled by make_docs from the warehouse


def money(x) -> str:
    return f"USD {float(x):,.0f}"


def service_agreement(k: dict, rates: list[dict]) -> str:
    start, end = k["start_date"], k["end_date"]
    lines = [
        "## 1. Parties",
        f"This Service Agreement (contract {k['contract_number']}) is made between Grand Line "
        f"Shipping Company B.V., Rotterdam (the Carrier), and {k['customer']}, {k['country']} "
        f"(the Merchant).",
        "## 2. Term",
        f"The agreement applies to cargo with a cargo ready date from {start:%d %B %Y} to "
        f"{end:%d %B %Y} inclusive on the {k['lane_name']} trade lane ({k['lane_code']}).",
        "## 3. Volume commitment",
        f"The Merchant commits to tender {k['committed_teu']:,} TEU during the term. The Carrier "
        "commits to provide space for the committed volume, spread evenly by week, subject to "
        "the Peak Season Surcharge and Allocation Policy. If the Merchant ships less than 80% of "
        "the committed volume, the Carrier may adjust rates for the following term.",
        "## 4. Rates",
        ("Rates are " + ("fixed for the term." if k["contract_type"] == "fixed" else
                         "index-linked: they are reviewed monthly and move 50% of the change in "
                         "the Grand Line spot index for the lane.")),
        "Base ocean freight per container, excluding surcharges:",
        "",
        "| Origin | Destination | Container type | Base rate (USD) |",
        "|---|---|---|---|",
    ]
    for r in rates[:48]:
        lines.append(f"| {PORT_NAMES.get(r['origin_port'], r['origin_port'])} ({r['origin_port']}) | "
                     f"{PORT_NAMES.get(r['destination_port'], r['destination_port'])} "
                     f"({r['destination_port']}) | {r['container_type']} | "
                     f"{float(r['base_rate_usd']):,.0f} |")
    lines += [
        "",
        "## 5. Surcharges",
        "The following are charged in addition to the base rate, at the tariff level in force "
        "when the cargo is shipped: bunker adjustment factor (BAF), terminal handling charges "
        "(THC), documentation fee (USD 75 per bill of lading), EU ETS surcharge on EU trades, "
        "contingency surcharge (CTG) while ships are diverted, dangerous goods surcharge (DGS) "
        "and demurrage and detention (DND) beyond free time.",
        "## 6. Free time",
        "Dry containers: 5 days demurrage and 7 days detention. Reefer containers: 3 days "
        "demurrage and 4 days detention, as set in the Demurrage and Detention Policy.",
        "## 7. Payment",
        f"Invoices are payable within {k['payment_terms_days'] or 30} days of the invoice date. "
        "Overdue amounts beyond 30 days may lead to a credit hold on new bookings.",
        "## 8. Liability and claims",
        "Carriage is subject to the Grand Line bill of lading terms and the Hague-Visby Rules. "
        "Claims must be filed within 45 days of delivery.",
        "## 9. Governing law",
        "This agreement is governed by Dutch law; disputes go to the courts of Rotterdam. "
        "For cargo to or from the United States, the Shipping Act and Federal Maritime "
        "Commission rules apply where mandatory.",
        "## 10. Signatures",
        f"Signed for Grand Line Shipping Company B.V. by the Trade Lane Manager "
        f"({k['lane_code']}) and for {k['customer']} by its authorised signatory, on "
        f"{(start - timedelta(days=21)):%d %B %Y}.",
    ]
    return "\n\n".join(x for x in lines if x is not None).replace("\n\n|", "\n|")


def subcontractor_agreement(s: dict, signed: date) -> str:
    kind = s["service_type"]
    scope = {
        "trucking": "inland container haulage between ports, depots and customer premises",
        "rail": "rail transport of containers between ports and inland terminals",
        "depot": "storage, inspection and repair of empty containers",
        "terminal": "stevedoring and terminal handling of Grand Line vessels",
    }[kind]
    return "\n\n".join([
        "## 1. Parties",
        f"Framework agreement between Grand Line Shipping Company B.V. and {s['name']} "
        f"({s['country']}), for {scope}.",
        "## 2. Term",
        f"The agreement starts on {signed:%d %B %Y} and runs for 3 years, renewing yearly "
        "unless either party gives 90 days' notice.",
        "## 3. Service levels",
        "Pickups must be within 4 hours of the agreed time. Performance is rated quarterly "
        f"on a 1 to 5 scale; the current rating is {s['performance_rating']}. A rating below "
        "2.5 for two consecutive quarters triggers a supplier review under the Procurement Policy.",
        "## 4. Insurance",
        "The subcontractor holds cargo liability insurance of at least USD 100,000 per load "
        "and public liability insurance of at least USD 5,000,000.",
        "## 5. Rates and invoicing",
        (f"Rates follow the agreed tariff schedule. Over the agreement period the average job "
         f"cost was {money(s['avg_cost'])} across {s['jobs']:,} jobs." if s["jobs"] else
         "Rates follow the agreed tariff schedule."),
        "## 6. Compliance",
        "The subcontractor complies with the Grand Line Code of Conduct, the Sanctions and "
        "Export Controls Policy and applicable safety law, and allows audits on 10 days' notice.",
        "## 7. Termination",
        "Either party may terminate for material breach not remedied within 30 days.",
    ])
