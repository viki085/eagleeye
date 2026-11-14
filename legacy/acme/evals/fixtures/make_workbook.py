"""Builds evals/fixtures/regional_plan.xlsx: two data sheets + one empty sheet + a formula.

uv run --package eagleeye-datasets python evals/fixtures/make_workbook.py
"""

from pathlib import Path

from openpyxl import Workbook

OUT = Path(__file__).with_name("regional_plan.xlsx")
REGIONS = [
    ("EMEA", 7_200_000, 41),
    ("North America", 6_900_000, 38),
    ("UK & Ireland", 4_300_000, 22),
    ("APAC", 2_900_000, 17),
    ("Nordics", 2_200_000, 11),
]


def main() -> None:
    wb = Workbook()
    targets = wb.active
    targets.title = "Region targets"
    targets.append(["Region", "2026 Target (EUR)", "Sales Reps", "Target per Rep"])
    for i, (region, target, reps) in enumerate(REGIONS, start=2):
        targets.append([region, target, reps, f"=B{i}/C{i}"])  # formula: never evaluated
    headcount = wb.create_sheet("Headcount")
    headcount.append(["Quarter", "Region", "Hires", "Leavers"])
    for q in ("2026-Q1", "2026-Q2", "2026-Q3"):
        for j, (region, _, _) in enumerate(REGIONS):
            headcount.append([q, region, 2 + (j + len(q)) % 4, 1 + j % 2])
    wb.create_sheet("Scratch")  # empty: skipped on import
    wb.save(OUT)


if __name__ == "__main__":
    main()
