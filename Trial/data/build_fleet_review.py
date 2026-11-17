"""Build documents/fleet-and-market-review-2025.pdf: a company report with tables and charts.

  evals/multimodal/.venv/Scripts/python.exe Trial/data/build_fleet_review.py

The demo's multimodal questions are asked about it (apps/web/src/lib/demo-questions.ts). Every
figure comes from the demo data files (vessel_fuel_and_emissions.csv,
voyage_utilisation_by_week.csv, brent_crude_daily.csv), so answers can be checked against them.
Charts are drawn with reportlab and embedded as pictures (rendered with pypdfium2), as in
most real reports. Needs reportlab and pypdfium2 (the multimodal eval's venv has both).
Prints the key figures for the questions.
"""

import csv
import io
from collections import defaultdict
from pathlib import Path
from statistics import mean

import pypdfium2 as pdfium
from reportlab.graphics import renderPDF
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HERE = Path(__file__).parent
FILES = HERE / "data-files"
OUT = HERE / "documents" / "fleet-and-market-review-2025.pdf"
YEAR = "2025"
GOLD = colors.HexColor("#9E8253")
INK = colors.HexColor("#1C1B18")


def rows(name: str) -> list[dict]:
    with (FILES / name).open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def emissions_by_class(voyages: list[dict]) -> list[list[str]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for v in voyages:
        groups[v["vessel_class"]].append(v)
    out = []
    for cls in sorted(groups):
        g = groups[cls]
        out.append(
            [
                cls,
                f"{len(g):,}",
                f"{mean(float(v['avg_speed_knots']) for v in g):.1f}",
                f"{sum(float(v['fuel_consumed_mt']) for v in g):,.0f}",
                f"{sum(float(v['co2_tonnes']) for v in g):,.0f}",
                f"{mean(float(v['co2_grams_per_teu_km']) for v in g):.1f}",
            ]
        )
    return out


def routing(voyages: list[dict]) -> list[list[str]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for v in voyages:
        groups[v["routing"]].append(v)
    names = {"standard": "Standard (Suez Canal)", "cape_of_good_hope": "Cape of Good Hope"}
    return [
        [
            names.get(r, r),
            f"{len(g):,}",
            f"{mean(float(v['distance_nm']) for v in g):,.0f}",
            f"{mean(float(v['fuel_consumed_mt']) for v in g):,.0f}",
            f"{mean(float(v['co2_tonnes']) for v in g):,.0f}",
        ]
        for r, g in sorted(groups.items())
    ]


def utilisation(weeks: list[dict]) -> list[tuple[str, float]]:
    groups: dict[str, list[float]] = defaultdict(list)
    for w in weeks:
        if w["week_start"].startswith(YEAR) and w["direction"] == "headhaul":
            groups[w["service_code"]].append(float(w["utilisation"]))
    return sorted(((s, round(mean(u) * 100, 1)) for s, u in groups.items()), key=lambda x: x[0])


def brent_monthly(days: list[dict]) -> list[tuple[str, float]]:
    groups: dict[str, list[float]] = defaultdict(list)
    for d in days:
        if d["date"][:4] in ("2024", YEAR):
            groups[d["date"][:7]].append(float(d["brent_usd_per_barrel"]))
    return [(m, round(mean(p), 2)) for m, p in sorted(groups.items())]


def bar_chart(data: list[tuple[str, float]]) -> Drawing:
    d = Drawing(16 * cm, 8 * cm)
    chart = VerticalBarChart()
    chart.x, chart.y, chart.width, chart.height = 40, 40, 16 * cm - 60, 8 * cm - 70
    chart.data = [[v for _, v in data]]
    chart.categoryAxis.categoryNames = [s for s, _ in data]
    chart.valueAxis.valueMin, chart.valueAxis.valueMax, chart.valueAxis.valueStep = 0, 100, 20
    chart.bars[0].fillColor = GOLD
    chart.barLabelFormat = "%.1f"
    chart.barLabels.nudge = 7
    chart.barLabels.fontSize = 7
    d.add(chart)
    d.add(
        String(
            8 * cm,
            8 * cm - 14,
            f"Average headhaul utilisation by service, {YEAR} (%)",
            textAnchor="middle",
            fontSize=10,
            fillColor=INK,
        )
    )
    return d


def line_chart(data: list[tuple[str, float]]) -> Drawing:
    d = Drawing(16 * cm, 8 * cm)
    plot = LinePlot()
    plot.x, plot.y, plot.width, plot.height = 45, 40, 16 * cm - 70, 8 * cm - 70
    plot.data = [[(i, v) for i, (_, v) in enumerate(data)]]
    plot.lines[0].strokeColor = GOLD
    plot.lines[0].strokeWidth = 2
    plot.xValueAxis.valueMin, plot.xValueAxis.valueMax = 0, len(data) - 1
    plot.xValueAxis.valueSteps = list(range(0, len(data), 3))
    plot.xValueAxis.labelTextFormat = lambda i: data[int(i)][0]
    plot.xValueAxis.labels.fontSize = 7
    plot.yValueAxis.valueMin, plot.yValueAxis.valueMax = 60, 100
    d.add(plot)
    d.add(
        String(
            8 * cm,
            8 * cm - 14,
            "Brent crude, monthly average (USD per barrel), 2024-2025",
            textAnchor="middle",
            fontSize=10,
            fillColor=INK,
        )
    )
    return d


def picture(drawing: Drawing) -> Image:
    """The chart as an embedded PNG (2x), the way charts usually arrive in company reports."""
    vector = io.BytesIO(renderPDF.drawToString(drawing))
    page = pdfium.PdfDocument(vector)[0]
    png = io.BytesIO()
    page.render(scale=2.5).to_pil().save(png, format="PNG")
    png.seek(0)
    return Image(png, width=drawing.width, height=drawing.height)


def table(header: list[str], body: list[list[str]], widths: list[float]) -> Table:
    t = Table([header, *body], colWidths=[w * cm for w in widths])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), INK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F1EA")]),
            ]
        )
    )
    return t


def main() -> None:
    voyages = [
        v for v in rows("vessel_fuel_and_emissions.csv") if v["departure_date"].startswith(YEAR)
    ]
    by_class = emissions_by_class(voyages)
    by_route = routing(voyages)
    util = utilisation(rows("voyage_utilisation_by_week.csv"))
    brent = brent_monthly(rows("brent_crude_daily.csv"))

    s = getSampleStyleSheet()
    body = s["BodyText"]
    story = [
        Paragraph("Grand Line Shipping Company B.V.", s["Normal"]),
        Paragraph(f"Fleet and Market Review {YEAR}", s["Title"]),
        Paragraph(
            "Prepared by Fleet Performance for the Executive Committee. This review summarises "
            f"the fleet's fuel use and emissions, vessel utilisation by service and the oil price "
            f"in {YEAR}. All figures are from the voyage and market records for the year.",
            body,
        ),
        Spacer(1, 0.4 * cm),
        Paragraph("1. Fuel and emissions by vessel class", s["Heading2"]),
        Paragraph(
            f"Table 1 shows the {YEAR} voyages by vessel class. Carbon intensity is the average of "
            "each voyage's grams of CO2 per TEU-kilometre.",
            body,
        ),
        Spacer(1, 0.2 * cm),
        Paragraph(f"Table 1: Fuel and emissions by vessel class, {YEAR}", s["Italic"]),
        Spacer(1, 0.3 * cm),
        table(
            ["Vessel class", "Voyages", "Avg speed (kn)", "Fuel (t)", "CO2 (t)", "gCO2 per TEU-km"],
            by_class,
            [3.4, 2, 2.6, 2.6, 2.6, 3],
        ),
        Spacer(1, 0.5 * cm),
        Paragraph("2. Vessel utilisation by service", s["Heading2"]),
        Paragraph(
            "Figure 1 shows the average share of slots filled on headhaul voyages for each "
            "service over the year.",
            body,
        ),
        picture(bar_chart(util)),
        Paragraph(f"Figure 1: Average headhaul utilisation by service, {YEAR}", s["Italic"]),
        Spacer(1, 0.5 * cm),
        Paragraph("3. Red Sea diversions", s["Heading2"]),
        Paragraph(
            "Services that avoided the Red Sea sailed around the Cape of Good Hope. Table 2 "
            "compares an average voyage on each routing.",
            body,
        ),
        Spacer(1, 0.2 * cm),
        Paragraph(f"Table 2: Average voyage by routing, {YEAR}", s["Italic"]),
        Spacer(1, 0.3 * cm),
        table(
            ["Routing", "Voyages", "Avg distance (nm)", "Avg fuel (t)", "Avg CO2 (t)"],
            by_route,
            [4.6, 2.2, 3.4, 3, 3],
        ),
        Spacer(1, 0.5 * cm),
        Paragraph("4. Oil price", s["Heading2"]),
        Paragraph(
            "Figure 2 shows the monthly average Brent crude price, which drives bunker "
            "costs and the bunker adjustment factor.",
            body,
        ),
        picture(line_chart(brent)),
        Paragraph("Figure 2: Brent crude, monthly average, 2024-2025", s["Italic"]),
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(
        str(OUT),
        pagesize=A4,
        title=f"Fleet and Market Review {YEAR}",
        author="Grand Line Shipping - Fleet Performance",
    ).build(story)

    print(OUT)
    print("Table 1:", *by_class, sep="\n  ")
    print("Table 2:", *by_route, sep="\n  ")
    print("Figure 1:", util)
    top = max(brent, key=lambda x: x[1])
    low = min(brent, key=lambda x: x[1])
    print(
        "Figure 2: high",
        top,
        "low",
        low,
        f"{YEAR} months:",
        [b for b in brent if b[0].startswith(YEAR)],
    )


if __name__ == "__main__":
    main()
