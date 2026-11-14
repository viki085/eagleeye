"""Document briefs built from warehouse facts: what each LLM-written document must say."""

from datetime import date

from facts import Facts, quarter_label
from policies import POLICIES
from writer import Brief

LANE_NAMES = {"AEU": "Asia - North Europe", "AMD": "Asia - Mediterranean",
              "TPW": "Transpacific", "AUE": "Asia - US East Coast",
              "ECS": "Asia - South America East Coast", "TAT": "Transatlantic",
              "AMI": "Asia - Middle East and India", "IAS": "Intra-Asia"}


def pct(x) -> str:
    return f"{float(x) * 100:.1f}%"


def usd(x) -> str:
    return f"USD {float(x):,.0f}"


def policy_briefs() -> list[tuple[Brief, dict]]:
    out = []
    for p in POLICIES:
        words = 1600 if p.fmt in ("pdf", "docx") else 700
        out.append((Brief(p.slug, p.title, "company policy or standard operating procedure",
                          "Grand Line employees", p.sections, p.facts, words),
                    {"category": "policies", "fmt": p.fmt, "owner": p.owner,
                     "classification": p.classification, "version": "3.1",
                     "effective": "2026-01-01"}))
    return out


def incident_briefs(f: Facts) -> list[tuple[Brief, dict]]:
    out = []
    for i, inc in enumerate(f.incidents[:120]):
        when = inc["started_at"]
        facts = (
            f"Incident number {inc['incident_number']}.",
            f"Vessel {inc['vessel']} on voyage {inc['voyage_number']} (service {inc['service_code']}).",
            f"Location: {inc['port_name']} ({inc['port_code']}), starting {when:%d %B %Y}.",
            f"Cause: {inc['cause']}. Severity: {inc['severity']}.",
            f"The ship was {float(inc['delay_hours']):.1f} hours behind schedule.",
            f"{inc['bookings_affected']:,} bookings totalling {float(inc['teu_affected']):,.0f} TEU were on board.",
        ) + (("The voyage was routed via the Cape of Good Hope because of the Red Sea crisis.",)
             if inc["routing"] != "standard" else ())
        out.append((Brief(f"incident-{inc['incident_number'].lower()}",
                          f"Incident Investigation Report {inc['incident_number']}: {inc['cause']} at {inc['port_name']}",
                          "incident investigation report", "network operations and customer service",
                          ("Summary", "Timeline", "Impact on customers and cargo", "Root cause analysis",
                           "Corrective and preventive actions", "Lessons learned"), facts, 900),
                    {"category": "incident-reports", "fmt": "docx" if i % 2 else "pdf",
                     "owner": "Head of Network Operations", "classification": "Internal",
                     "version": "1.0", "effective": f"{when:%Y-%m-%d}"}))
    return out


def special_reports(f: Facts) -> list[tuple[Brief, dict]]:
    outage = {r["booking_date"]: r["bookings"] for r in f.outage}
    before = [v for d, v in outage.items() if date(2025, 6, 3) <= d <= date(2025, 6, 9)]
    after = [v for d, v in outage.items() if date(2025, 6, 15) <= d <= date(2025, 6, 17)]
    reefer = f.reefer_claims
    total_ctrl = sum(r["controller_claims"] for r in reefer)
    peak = max(reefer, key=lambda r: r["claims"]) if reefer else None
    q1 = [r for r in f.lanes_by_month if r["lane_code"] == "AEU" and r["month"].year == 2024
          and r["month"].month <= 3 and r["on_time"] is not None]
    aeu_q1 = sum(float(r["on_time"]) for r in q1) / max(len(q1), 1)
    reports = [
        ("cyber-incident-june-2025", "Post-Incident Review: Booking Platform Outage, 10-14 June 2025",
         ("Executive summary", "Timeline", "Business impact", "Technical root cause", "Response and recovery",
          "Actions and owners"),
         ("The booking platform was unavailable from 10 June 2025 to 14 June 2025 after a ransomware attack on a third-party integration server.",
          f"Before the outage Grand Line took on average {sum(before) / max(len(before), 1):,.0f} bookings per day (3 to 9 June 2025).",
          f"After restoration the backlog produced {max(after or [0]):,} bookings on a single day.",
          "Manual booking by email (business continuity template BC-07) was activated after 4 hours.",
          "No customer data was exfiltrated, as confirmed by the external forensic investigation."),
         "Confidential"),
        ("reefer-controller-failures-2025", "Investigation Report: Reefer Controller Failures, Coldline Leasing Batch CL-2207",
         ("Summary", "Background", "Claims and cost", "Technical findings", "Commercial recovery from the lessor",
          "Actions"),
         (f"Between June and December 2025, {total_ctrl:,} reefer claims were traced to faulty controllers in Coldline Leasing batch CL-2207.",
          (f"Reefer claims peaked in {peak['month']:%B %Y} with {peak['claims']:,} claims filed." if peak else
           "Reefer claims peaked in autumn 2025."),
          "Affected cargo had cargo ready dates from 1 August 2025 to 30 September 2025.",
          "All CL-2207 units were withdrawn from service in October 2025 and replaced by owned units."),
         "Confidential"),
        ("us-east-coast-strike-2024", "Operational Review: US East and Gulf Coast Port Strike, October 2024",
         ("Summary", "Timeline", "Impact on services AUX and TAX", "Customer communication", "Recovery", "Lessons"),
         ("Port labour action closed US East and Gulf Coast ports from 1 October 2024 to 3 October 2024.",
          "Grand Line services AUX and TAX were affected at New York / New Jersey, Savannah, Charleston and Houston.",
          "Ships waited at anchor and schedules took about two weeks to recover."),
         "Internal"),
        ("red-sea-diversion-q1-2024", "Network Review: Red Sea Diversion and Schedule Reliability, Q1 2024",
         ("Summary", "What happened", "Effect on schedule reliability", "Fleet and cost impact",
          "Customer measures", "Outlook"),
         ("From 1 January 2024 AEX and AMX voyages sailed via the Cape of Good Hope.",
          "Schedules for January and early February 2024 departures had been planned via Suez, so those voyages arrived about 11 days late.",
          f"Asia - North Europe schedule reliability averaged {pct(aeu_q1)} in Q1 2024.",
          "Two extra ships were chartered on each of AEX and AMX from 15 January 2024."),
         "Confidential"),
    ]
    out = []
    for slug, title, sections, facts, cls in reports:
        out.append((Brief(slug, title, "investigation or review report", "the executive team",
                          sections, facts, 1400),
                    {"category": "incident-reports", "fmt": "pdf", "owner": "Chief Operating Officer",
                     "classification": cls, "version": "1.0", "effective": "2025-11-01"}))
    return out


def monthly_tables(f: Facts) -> dict[date, str]:
    """Markdown tables for each monthly report (computed, never LLM-written)."""
    lanes: dict[date, list[dict]] = {}
    for r in f.lanes_by_month:
        lanes.setdefault(r["month"], []).append(r)
    out = {}
    for m in f.months:
        rows = ["| Lane | TEU | Freight revenue per TEU | On-time arrivals |", "|---|---|---|---|"]
        for r in lanes.get(m["month"], []):
            ot = pct(r["on_time"]) if r["on_time"] is not None else "n/a"
            rows.append(f"| {LANE_NAMES[r['lane_code']]} | {float(r['teu']):,.0f} | "
                        f"{usd(r['rev_per_teu'])} | {ot} |")
        out[m["month"]] = "\n".join(rows)
    return out


def monthly_briefs(f: Facts) -> list[tuple[Brief, dict]]:
    out = []
    for m in f.months:
        d = m["month"]
        facts = [
            f"Volume in {d:%B %Y}: {float(m['teu']):,.0f} TEU from {m['bookings']:,} bookings.",
            f"Ocean freight revenue: {usd(m['rev'])}; average {usd(float(m['rev']) / float(m['teu']))} per TEU.",
        ]
        if m["on_time"] is not None:
            facts.append(f"Schedule reliability (arrivals within 24 hours of schedule): {pct(m['on_time'])}.")
        if m["incidents"]:
            facts.append(f"{m['incidents']} delay incidents were logged, {m['severe'] or 0} of them major or critical.")
        if m["fuel_price"]:
            facts.append(f"Average bunker price paid: USD {float(m['fuel_price']):,.2f} per tonne.")
        if m["claims"]:
            facts.append(f"{m['claims']} cargo claims were filed.")
        if m["rolled"]:
            facts.append(f"{m['rolled']:,} bookings were rolled to a later voyage.")
        out.append((Brief(f"monthly-ops-{d:%Y-%m}", f"Monthly Operations Report - {d:%B %Y}",
                          "monthly operations report commentary", "the management team",
                          ("Highlights", "Volume and revenue", "Network performance", "Fuel and cost",
                           "Customers and claims", "Outlook for next month"), tuple(facts), 650),
                    {"category": "monthly-reports", "fmt": "pdf", "owner": "Head of Business Performance",
                     "classification": "Internal", "version": "1.0",
                     "effective": f"{d.year + (d.month == 12)}-{d.month % 12 + 1:02d}-10",
                     "table_month": d}))
    return out


def quarterly_briefs(f: Facts) -> list[tuple[Brief, dict]]:
    out = []
    for q in f.quarters:
        label = quarter_label(q["quarter"])
        facts = [f"{label} volume: {float(q['teu']):,.0f} TEU.",
                 f"{label} ocean freight revenue: {usd(q['rev'])}."]
        if q["on_time"] is not None:
            facts.append(f"{label} schedule reliability: {pct(q['on_time'])}.")
        if q["fuel_cost"]:
            facts.append(f"{label} bunker fuel cost: {usd(q['fuel_cost'])}.")
        if q["at_risk"]:
            facts.append(f"Overdue or disputed invoices at quarter end: {usd(q['at_risk'])}.")
        if q["co2"]:
            facts.append(f"{label} fleet CO2 emissions: {float(q['co2']):,.0f} tonnes.")
        out.append((Brief(f"qbr-{q['quarter']:%Y}-q{(q['quarter'].month - 1) // 3 + 1}",
                          f"Quarterly Business Review - {label}", "slide deck (one '##' heading per slide, 4-6 bullets each)",
                          "the executive committee",
                          ("Quarter at a glance", "Volume and revenue", "Network reliability", "Cost and fuel",
                           "Cash and credit", "Sustainability", "Risks", "Priorities for next quarter"),
                          tuple(facts), 700),
                    {"category": "board-and-strategy", "fmt": "slides", "owner": "Chief Financial Officer",
                     "classification": "Confidential", "version": "1.0",
                     "effective": f"{q['quarter']:%Y-%m-%d}"}))
    return out


STRATEGY = (
    ("strategy-2026-2030", "Grand Line Strategy 2026-2030", ("Where we are", "Market outlook", "Strategic pillars", "Network", "Customers", "Decarbonisation", "Digital", "Financial targets"),
     ("Grand Line operates 8 weekly services and about 60 container ships.", "The decarbonisation target is a 20% cut in carbon intensity by 2030 against 2024.")),
    ("fleet-renewal-2026", "Fleet Renewal Programme 2026", ("Current fleet", "Charter exposure", "Newbuild options", "Fuel technology choice", "Financing", "Recommendation"),
     ("Dual-fuel LNG and methanol ships joined the fleet in 2024 and 2025.",)),
    ("decarbonisation-roadmap", "Decarbonisation Roadmap", ("Why it matters", "EU ETS and FuelEU Maritime", "Fleet measures", "Operational measures", "Customer offer", "Milestones"),
     ("EU ETS covers 40% of 2024 emissions, 70% of 2025 and 100% from 2026 for in-scope voyages.",)),
    ("digital-strategy", "Digital and Data Strategy", ("Today", "Customer platform", "Data platform", "AI assistant (EagleEye)", "Cybersecurity", "Roadmap"),
     ("The June 2025 booking platform outage lasted from 10 to 14 June 2025.",)),
    ("budget-2026", "Budget 2026", ("Assumptions", "Volume", "Rates", "Costs", "Capex", "Risks"),
     ("Industry fleet growth is expected to keep freight rates under pressure in 2026.",)),
    ("red-sea-board-update", "Board Update: Red Sea Situation", ("Situation", "Our response", "Cost", "Customer impact", "Return to Suez"),
     ("AEX and AMX voyages departing from January 2024 to June 2025 sailed via the Cape of Good Hope.",)),
    ("customer-concentration-review", "Customer Concentration Review", ("Purpose", "Top customers", "Concentration risk", "Contract coverage", "Actions"),
     ()),
    ("enterprise-risk-register", "Enterprise Risk Register Review", ("Method", "Top risks", "Cyber", "Geopolitical", "Market", "Mitigations"),
     ()),
    ("cyber-board-briefing", "Board Briefing: Cyber Incident June 2025", ("What happened", "Impact", "Response", "Regulatory notifications", "Investment needed"),
     ("The booking platform was unavailable from 10 June 2025 to 14 June 2025.",)),
    ("pricing-strategy-2026", "Pricing Strategy 2026", ("Market", "Contract versus spot", "Index-linked contracts", "Surcharges", "Targets"),
     ("Transpacific and Asia - US East Coast contracts run from 1 May to 30 April.",)),
    ("network-redesign-proposal", "Network Redesign Proposal 2027", ("Current network", "Performance by service", "Options", "Recommended network", "Financial case"),
     ()),
    ("annual-report-2025-summary", "Annual Performance Summary 2025", ("Overview", "Volume and revenue", "Operations", "People", "Sustainability", "Outlook"),
     ()),
)


def strategy_briefs(f: Facts) -> list[tuple[Brief, dict]]:
    y25 = [q for q in f.quarters if q["quarter"].year == 2025]
    teu25 = sum(float(q["teu"]) for q in y25)
    rev25 = sum(float(q["rev"]) for q in y25)
    top = f.customers[:5]
    extra = {
        "annual-report-2025-summary": (f"2025 volume: {teu25:,.0f} TEU.", f"2025 ocean freight revenue: {usd(rev25)}."),
        "customer-concentration-review": tuple(
            f"{c['name']} ({c['country']}) shipped {float(c['teu_2025']):,.0f} TEU in 2025 for {usd(c['rev_2025'])} of ocean freight."
            for c in top),
        "budget-2026": (f"2025 volume: {teu25:,.0f} TEU.",),
    }
    out = []
    for slug, title, sections, facts in STRATEGY:
        out.append((Brief(slug, title, "slide deck (one '##' heading per slide, 4-6 bullets each)",
                          "the board of directors", sections, tuple(facts) + extra.get(slug, ()), 800),
                    {"category": "board-and-strategy", "fmt": "slides", "owner": "Chief Executive Officer",
                     "classification": "Confidential", "version": "1.0", "effective": "2026-02-15"}))
    return out


TRAINING = ("Introduction to Container Shipping for New Starters", "Reading a Bill of Lading",
            "Dangerous Goods Awareness", "Reefer Monitoring Centre Induction",
            "Customer Service Booking Workflow", "Pricing Fundamentals", "Credit Control Basics",
            "Cybersecurity Awareness 2026", "Verified Gross Mass and SOLAS",
            "US Importer Security Filing Basics", "EU ICS2 Basics", "Port Operations Basics",
            "Vessel Stowage Planning Basics", "EU ETS and FuelEU Maritime Explained",
            "Claims Handling Essentials")
RUNBOOKS = ("Booking Platform Restart", "EDI Message Feed Failure", "Container Tracking Feed Delay",
            "Operations Warehouse Nightly Load Failure", "Remote Access VPN Outage",
            "Suspected Phishing Email", "Reefer Telemetry Gateway Down", "Monthly Invoice Run Failure",
            "Quarterly Backup Restore Test", "Customer Portal Login Problems",
            "Vessel Schedule Publication Error", "EagleEye Assistant Incident Response")


def training_and_runbooks() -> list[tuple[Brief, dict]]:
    out = []
    for i, t in enumerate(TRAINING):
        out.append((Brief(f"training-{_slug(t)}", f"Training Module: {t}", "training module",
                          "new and existing employees",
                          ("Learning objectives", "Key concepts", "Step by step", "Common mistakes",
                           "Knowledge check questions"), (), 1100),
                    {"category": "training", "fmt": "docx" if i % 2 else "pdf", "owner": "Head of Learning",
                     "classification": "Internal", "version": "2.0", "effective": "2025-09-01"}))
    for t in RUNBOOKS:
        out.append((Brief(f"runbook-{_slug(t)}", f"IT Runbook: {t}", "IT operations runbook",
                          "IT support and on-call engineers",
                          ("Symptoms", "Impact", "Diagnosis", "Resolution steps", "Escalation", "Post-incident"),
                          ("Security incidents must be reported to the Security Operations Centre within 1 hour.",),
                          600),
                    {"category": "it-runbooks", "fmt": "md", "owner": "Head of IT Operations",
                     "classification": "Internal", "version": "1.4", "effective": "2026-03-01"}))
    return out


def minutes_briefs(f: Facts) -> list[tuple[Brief, dict]]:
    out = []
    picks = [m for m in f.months if m["month"].month in (1, 4, 7, 10)]
    for m in picks:
        d = m["month"]
        facts = [f"Volume in {d:%B %Y}: {float(m['teu']):,.0f} TEU."]
        if m["on_time"] is not None:
            facts.append(f"Schedule reliability in {d:%B %Y}: {pct(m['on_time'])}.")
        out.append((Brief(f"minutes-network-ops-{d:%Y-%m}", f"Minutes: Network Operations Review, {d:%B %Y}",
                          "meeting minutes (attendees by role, agenda items, decisions, action items with owners and due dates)",
                          "the network operations team",
                          ("Attendees", "Agenda", "Discussion", "Decisions", "Action items"), tuple(facts), 600),
                    {"category": "meeting-minutes", "fmt": "txt" if d.month == 7 else "docx",
                     "owner": "Head of Network Operations", "classification": "Internal", "version": "1.0",
                     "effective": f"{d:%Y-%m}-28"}))
    special = (
        ("minutes-red-sea-taskforce-2024-01", "Minutes: Red Sea Task Force, 3 January 2024",
         ("AEX and AMX voyages will sail via the Cape of Good Hope from 1 January 2024.",
          "Two extra ships will be chartered on each of AEX and AMX.")),
        ("minutes-crisis-team-2025-06", "Minutes: Crisis Team, 11 June 2025",
         ("The booking platform has been unavailable since 10 June 2025.",
          "Manual booking by email (template BC-07) is active.")),
        ("minutes-reefer-taskforce-2025-10", "Minutes: Reefer Task Force, 6 October 2025",
         ("All Coldline Leasing batch CL-2207 units will be withdrawn from service in October 2025.",)),
    )
    for slug, title, facts in special:
        out.append((Brief(slug, title, "meeting minutes (attendees by role, decisions, action items)",
                          "the management team", ("Attendees", "Situation", "Decisions", "Action items"),
                          facts, 600),
                    {"category": "meeting-minutes", "fmt": "docx", "owner": "Chief Operating Officer",
                     "classification": "Confidential", "version": "1.0", "effective": "2025-10-06"}))
    return out


def port_briefs(f: Facts) -> list[tuple[Brief, dict]]:
    out = []
    for p in f.ports:
        facts = [f"{p['name']} ({p['port_code']}), {p['country']}, region {p['region']}.",
                 f"Grand Line services calling: {p['services']}.",
                 f"Port calls recorded since January 2024: {p['calls']:,}.",
                 f"Container moves (loaded plus discharged) since January 2024: {int(p['moves'] or 0):,}.",
                 f"Share of calls arriving within 24 hours of schedule: {pct(p['on_time'])}.",
                 f"Average time in port per call: {float(p['avg_port_hours']):.1f} hours."]
        out.append((Brief(f"port-profile-{p['port_code'].lower()}", f"Port Profile: {p['name']} ({p['port_code']})",
                          "port profile for operations staff", "operations and customer service staff",
                          ("Overview", "Grand Line services", "Performance", "Operational notes", "Local contacts and procedures"),
                          tuple(facts), 450),
                    {"category": "port-profiles", "fmt": "md", "owner": "Head of Network Operations",
                     "classification": "Internal", "version": "2026.1", "effective": "2026-10-31"}))
    return out


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in text.lower()).strip("-").replace("--", "-")
