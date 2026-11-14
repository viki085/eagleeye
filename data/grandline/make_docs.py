"""Build the Grand Line enterprise document library from the warehouse.

Run from the repo root once the warehouse is loaded (costs a few dollars of LLM use, once;
re-runs reuse the cached text in data/grandline/out/md):
  uv run --package eagleeye-ingest-worker python data/grandline/make_docs.py [--only policies]

Writes data/grandline/out/docs/<category>/<file> and data/grandline/out/manifest.json.
"""

import argparse
import asyncio
import hashlib
import json
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import briefs as B  # noqa: E402
import facts as F  # noqa: E402
import render as R  # noqa: E402
import templates as T  # noqa: E402
from writer import Writer  # noqa: E402

OUT = HERE / "out"
DOCS = OUT / "docs"
PUBLIC = (  # US federal government works: public domain
    ("cbp-reasonable-care", "CBP Informed Compliance Publication: Reasonable Care (2017)",
     "https://www.cbp.gov/sites/default/files/assets/documents/2020-Feb/icprescare2017revision.pdf"),
    ("fmc-demurrage-detention-interpretive-rule-2020", "FMC Interpretive Rule on Demurrage and Detention (Federal Register, 18 May 2020)",
     "https://www.govinfo.gov/content/pkg/FR-2020-05-18/pdf/2020-09370.pdf"),
    ("ocean-shipping-reform-act-2022", "Ocean Shipping Reform Act of 2022 (Public Law 117-146)",
     "https://www.govinfo.gov/content/pkg/PLAW-117publ146/pdf/PLAW-117publ146.pdf"),
    ("49-cfr-176-carriage-by-vessel", "49 CFR Part 176: Carriage by Vessel (hazardous materials)",
     "https://www.govinfo.gov/content/pkg/CFR-2024-title49-vol2/pdf/CFR-2024-title49-vol2-part176.pdf"),
    ("19-cfr-149-importer-security-filing", "19 CFR Part 149: Importer Security Filing",
     "https://www.govinfo.gov/content/pkg/CFR-2024-title19-vol2/pdf/CFR-2024-title19-vol2-part149.pdf"),
    ("46-cfr-545-interpretive-rules", "46 CFR Part 545: Interpretations and Statements of Policy",
     "https://www.govinfo.gov/content/pkg/CFR-2024-title46-vol9/pdf/CFR-2024-title46-vol9-part545.pdf"),
    ("46-cfr-541-demurrage-detention-billing", "46 CFR Part 541: Demurrage and Detention Billing Requirements",
     "https://www.govinfo.gov/content/pkg/CFR-2024-title46-vol9/pdf/CFR-2024-title46-vol9-part541.pdf"),
    ("46-cfr-520-carrier-tariffs", "46 CFR Part 520: Carrier Automated Tariffs",
     "https://www.govinfo.gov/content/pkg/CFR-2024-title46-vol9/pdf/CFR-2024-title46-vol9-part520.pdf"),
)


def _meta(slug: str, title: str, m: dict) -> R.Meta:
    num = "GL-" + hashlib.sha1(slug.encode()).hexdigest()[:6].upper()
    return R.Meta(num, title, m["classification"], m["version"], m["effective"], m["owner"])


def _save(manifest: list, slug: str, title: str, m: dict, md: str, facts=()) -> None:
    meta = _meta(slug, title, m)
    data = R.RENDERERS[m["fmt"]](meta, md)
    folder = DOCS / m["category"]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{slug}.{R.EXTENSION[m['fmt']]}"
    path.write_bytes(data)
    manifest.append({"slug": slug, "title": title, "category": m["category"], "format": m["fmt"],
                     "classification": m["classification"], "doc_number": meta.doc_number,
                     "path": str(path.relative_to(OUT)).replace("\\", "/"), "facts": list(facts),
                     "source": "generated"})


async def llm_docs(writer: Writer, f: F.Facts, only: str | None, manifest: list) -> None:
    groups = {
        "policies": B.policy_briefs(), "incidents": B.incident_briefs(f) + B.special_reports(f),
        "monthly": B.monthly_briefs(f), "quarterly": B.quarterly_briefs(f),
        "strategy": B.strategy_briefs(f), "training": B.training_and_runbooks(),
        "minutes": B.minutes_briefs(f), "ports": B.port_briefs(f),
    }
    tables = B.monthly_tables(f)
    todo = [(b, m) for name, items in groups.items() if not only or name == only for b, m in items]
    print(f"  writing {len(todo)} documents with the LLM", flush=True)
    done = 0

    async def one(brief, m):
        nonlocal done
        md = await writer.write(brief)
        if "table_month" in m:  # monthly report: computed KPI table first, then commentary
            md = f"## Key figures by trade lane\n\n{tables[m['table_month']]}\n\n{md}"
        _save(manifest, brief.slug, brief.title, m, md, brief.facts)
        done += 1
        if done % 25 == 0:
            print(f"    {done}/{len(todo)} written (LLM cost so far USD {writer.cost_usd:.2f})", flush=True)

    await asyncio.gather(*(one(b, m) for b, m in todo))


def template_docs(f: F.Facts, manifest: list) -> None:
    T.PORT_NAMES.update({p["port_code"]: p["name"] for p in f.ports})
    for k in f.contracts:
        m = {"category": "customer-contracts", "fmt": "pdf", "owner": "Head of Pricing",
             "classification": "Confidential", "version": "1.0", "effective": f"{k['start_date']}"}
        title = f"Service Agreement {k['contract_number']}: {k['customer']} ({k['lane_name']})"
        md = T.service_agreement(k, f.rates.get(k["contract_id"], []))
        facts = (f"Contract {k['contract_number']} commits {k['customer']} to {k['committed_teu']:,} TEU.",)
        _save(manifest, f"contract-{k['contract_number'].lower()}", title, m, md, facts)
    for i, s in enumerate(f.subcontractors):
        signed = date(2023, 1, 9) + timedelta(days=37 * i)
        m = {"category": "supplier-agreements", "fmt": "pdf", "owner": "Chief Procurement Officer",
             "classification": "Confidential", "version": "1.0", "effective": f"{signed}"}
        title = f"Framework Agreement: {s['name']} ({s['service_type'].title()} Services)"
        _save(manifest, f"supplier-{s['subcontractor_id']:03d}", title, m,
              T.subcontractor_agreement(s, signed))


def public_docs(manifest: list) -> None:
    folder = DOCS / "public-reference"
    folder.mkdir(parents=True, exist_ok=True)
    for slug, title, url in PUBLIC:
        path = folder / f"{slug}.pdf"
        if not path.exists():
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - fixed https URLs
                path.write_bytes(resp.read())
        manifest.append({"slug": slug, "title": title, "category": "public-reference",
                         "format": "pdf", "classification": "Public", "doc_number": "",
                         "path": str(path.relative_to(OUT)).replace("\\", "/"), "facts": [],
                         "source": url})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="one LLM group: policies, incidents, monthly, quarterly, "
                                   "strategy, training, minutes, ports")
    args = ap.parse_args()
    t = time.monotonic()
    f = asyncio.run(F.load())
    print(f"Loaded warehouse facts ({time.monotonic() - t:.0f}s)", flush=True)
    manifest: list = []
    writer = Writer(OUT / "md")
    asyncio.run(llm_docs(writer, f, args.only, manifest))
    if not args.only:
        template_docs(f, manifest)
        public_docs(manifest)
    manifest.sort(key=lambda d: (d["category"], d["slug"]))
    if not args.only:
        (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"Done: {len(manifest)} documents, {writer.calls} LLM calls, "
          f"USD {writer.cost_usd:.2f}, {time.monotonic() - t:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
