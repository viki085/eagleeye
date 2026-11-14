# Public data and documents used in the Grand Line demo

Grand Line Shipping Company is fictional. Its own records are generated
(`infra/warehouse/generate.py`, `data/grandline/`). The material below is real and public; it is
used as reference material the company would hold, or as a real input to the generated numbers.

| Material | Source | Licence |
|---|---|---|
| Daily Brent crude oil spot price (`brent_daily_fred.csv`); drives Grand Line's simulated fuel prices and bunker surcharges | US Energy Information Administration, series RBRTE, retrieved via FRED (series DCOILBRENTEU): https://fred.stlouisfed.org/series/DCOILBRENTEU | US government work, public domain |
| Port names and codes | UN/LOCODE, UNECE | free to use |
| CBP Informed Compliance Publication: Reasonable Care (2017) | https://www.cbp.gov/sites/default/files/assets/documents/2020-Feb/icprescare2017revision.pdf | US government work, public domain |
| FMC interpretive rule on demurrage and detention (Federal Register, 18 May 2020) | https://www.govinfo.gov/content/pkg/FR-2020-05-18/pdf/2020-09370.pdf | US government work, public domain |
| Ocean Shipping Reform Act of 2022 (Public Law 117-146) | https://www.govinfo.gov/content/pkg/PLAW-117publ146/pdf/PLAW-117publ146.pdf | US government work, public domain |
| 49 CFR Part 176, Carriage by Vessel | https://www.govinfo.gov/content/pkg/CFR-2024-title49-vol2/pdf/CFR-2024-title49-vol2-part176.pdf | US government work, public domain |
| 19 CFR Part 149, Importer Security Filing | https://www.govinfo.gov/content/pkg/CFR-2024-title19-vol2/pdf/CFR-2024-title19-vol2-part149.pdf | US government work, public domain |
| 46 CFR Parts 520, 541 and 545 (FMC tariffs, demurrage and detention billing, interpretive rules) | https://www.govinfo.gov/app/collection/cfr | US government work, public domain |

EU regulations (EU ETS for shipping, FuelEU Maritime) are reusable with attribution, but EUR-Lex
blocks automated downloads, so they are referred to by name only in Grand Line's own policies.
