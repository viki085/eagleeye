"""Fixed reference data: real ports (UN/LOCODE), trade lanes and Grand Line's service network.

Port coordinates are approximate (to about 0.1 degree). Everything else about the company is
fictional.
"""

from dataclasses import dataclass
from datetime import date

START = date(2024, 1, 1)
END = date(2026, 10, 31)  # last day with completed activity ("today" is mid-November 2026)

# code, name, country code, country, region, latitude, longitude
PORTS: tuple[tuple[str, str, str, str, str, float, float], ...] = (
    ("CNSHA", "Shanghai", "CN", "China", "Asia", 31.23, 121.47),
    ("CNNGB", "Ningbo-Zhoushan", "CN", "China", "Asia", 29.87, 121.55),
    ("CNYTN", "Yantian (Shenzhen)", "CN", "China", "Asia", 22.57, 114.27),
    ("CNTAO", "Qingdao", "CN", "China", "Asia", 36.07, 120.32),
    ("CNXMN", "Xiamen", "CN", "China", "Asia", 24.48, 118.08),
    ("CNTXG", "Tianjin", "CN", "China", "Asia", 39.00, 117.72),
    ("CNNSA", "Nansha (Guangzhou)", "CN", "China", "Asia", 22.75, 113.62),
    ("HKHKG", "Hong Kong", "HK", "Hong Kong", "Asia", 22.30, 114.17),
    ("KRPUS", "Busan", "KR", "South Korea", "Asia", 35.10, 129.04),
    ("JPTYO", "Tokyo", "JP", "Japan", "Asia", 35.62, 139.78),
    ("JPNGO", "Nagoya", "JP", "Japan", "Asia", 35.05, 136.88),
    ("JPUKB", "Kobe", "JP", "Japan", "Asia", 34.68, 135.20),
    ("TWKHH", "Kaohsiung", "TW", "Taiwan", "Asia", 22.61, 120.28),
    ("SGSIN", "Singapore", "SG", "Singapore", "Asia", 1.26, 103.84),
    ("MYPKG", "Port Klang", "MY", "Malaysia", "Asia", 3.00, 101.39),
    ("MYTPP", "Tanjung Pelepas", "MY", "Malaysia", "Asia", 1.36, 103.55),
    ("THLCH", "Laem Chabang", "TH", "Thailand", "Asia", 13.08, 100.88),
    ("VNCMT", "Cai Mep", "VN", "Vietnam", "Asia", 10.53, 107.03),
    ("VNHPH", "Haiphong", "VN", "Vietnam", "Asia", 20.86, 106.68),
    ("PHMNL", "Manila", "PH", "Philippines", "Asia", 14.60, 120.96),
    ("IDTPP", "Tanjung Priok (Jakarta)", "ID", "Indonesia", "Asia", -6.10, 106.88),
    ("LKCMB", "Colombo", "LK", "Sri Lanka", "Asia", 6.95, 79.84),
    ("INNSA", "Nhava Sheva", "IN", "India", "Asia", 18.95, 72.95),
    ("INMUN", "Mundra", "IN", "India", "Asia", 22.74, 69.70),
    ("PKKHI", "Karachi", "PK", "Pakistan", "Asia", 24.83, 66.98),
    ("AEJEA", "Jebel Ali", "AE", "United Arab Emirates", "Middle East", 25.01, 55.06),
    ("OMSLL", "Salalah", "OM", "Oman", "Middle East", 16.94, 54.00),
    ("SAJED", "Jeddah", "SA", "Saudi Arabia", "Middle East", 21.47, 39.17),
    ("EGPSD", "Port Said", "EG", "Egypt", "Middle East", 31.25, 32.30),
    ("NLRTM", "Rotterdam", "NL", "Netherlands", "Europe", 51.95, 4.05),
    ("BEANR", "Antwerp-Bruges", "BE", "Belgium", "Europe", 51.28, 4.33),
    ("DEHAM", "Hamburg", "DE", "Germany", "Europe", 53.54, 9.97),
    ("DEBRV", "Bremerhaven", "DE", "Germany", "Europe", 53.56, 8.55),
    ("GBFXT", "Felixstowe", "GB", "United Kingdom", "Europe", 51.95, 1.33),
    ("GBSOU", "Southampton", "GB", "United Kingdom", "Europe", 50.90, -1.43),
    ("FRLEH", "Le Havre", "FR", "France", "Europe", 49.48, 0.15),
    ("PLGDN", "Gdansk", "PL", "Poland", "Europe", 54.40, 18.67),
    ("ESVLC", "Valencia", "ES", "Spain", "Europe", 39.44, -0.32),
    ("ESALG", "Algeciras", "ES", "Spain", "Europe", 36.13, -5.43),
    ("ITGOA", "Genoa", "IT", "Italy", "Europe", 44.40, 8.92),
    ("GRPIR", "Piraeus", "GR", "Greece", "Europe", 37.94, 23.62),
    ("TRMER", "Mersin", "TR", "Turkey", "Europe", 36.80, 34.63),
    ("MAPTM", "Tanger Med", "MA", "Morocco", "Africa", 35.89, -5.50),
    ("ZADUR", "Durban", "ZA", "South Africa", "Africa", -29.87, 31.03),
    ("ZACPT", "Cape Town", "ZA", "South Africa", "Africa", -33.91, 18.43),
    ("KEMBA", "Mombasa", "KE", "Kenya", "Africa", -4.06, 39.67),
    ("NGLOS", "Lagos (Apapa)", "NG", "Nigeria", "Africa", 6.44, 3.37),
    ("GHTEM", "Tema", "GH", "Ghana", "Africa", 5.63, 0.01),
    ("USLAX", "Los Angeles", "US", "United States", "North America", 33.73, -118.26),
    ("USLGB", "Long Beach", "US", "United States", "North America", 33.75, -118.20),
    ("USOAK", "Oakland", "US", "United States", "North America", 37.80, -122.32),
    ("USSEA", "Seattle", "US", "United States", "North America", 47.58, -122.35),
    ("USNYC", "New York / New Jersey", "US", "United States", "North America", 40.67, -74.15),
    ("USSAV", "Savannah", "US", "United States", "North America", 32.13, -81.14),
    ("USCHS", "Charleston", "US", "United States", "North America", 32.85, -79.93),
    ("USORF", "Norfolk", "US", "United States", "North America", 36.90, -76.33),
    ("USHOU", "Houston", "US", "United States", "North America", 29.73, -95.02),
    ("USMIA", "Miami", "US", "United States", "North America", 25.77, -80.17),
    ("CAVAN", "Vancouver", "CA", "Canada", "North America", 49.29, -123.10),
    ("CAMTR", "Montreal", "CA", "Canada", "North America", 45.55, -73.53),
    ("MXZLO", "Manzanillo", "MX", "Mexico", "Latin America", 19.07, -104.30),
    ("PABLB", "Balboa", "PA", "Panama", "Latin America", 8.95, -79.57),
    ("COCTG", "Cartagena", "CO", "Colombia", "Latin America", 10.40, -75.53),
    ("JMKIN", "Kingston", "JM", "Jamaica", "Latin America", 17.97, -76.80),
    ("BRSSZ", "Santos", "BR", "Brazil", "Latin America", -23.98, -46.30),
    ("BRPNG", "Paranagua", "BR", "Brazil", "Latin America", -25.50, -48.52),
    ("BRRIG", "Rio Grande", "BR", "Brazil", "Latin America", -32.05, -52.08),
    ("ARBUE", "Buenos Aires", "AR", "Argentina", "Latin America", -34.58, -58.37),
    ("UYMVD", "Montevideo", "UY", "Uruguay", "Latin America", -34.90, -56.21),
    ("CLSAI", "San Antonio", "CL", "Chile", "Latin America", -33.59, -71.62),
    ("PECLL", "Callao", "PE", "Peru", "Latin America", -12.05, -77.15),
    ("AUMEL", "Melbourne", "AU", "Australia", "Oceania", -37.83, 144.92),
    ("AUSYD", "Sydney (Botany)", "AU", "Australia", "Oceania", -33.97, 151.21),
    ("NZAKL", "Auckland", "NZ", "New Zealand", "Oceania", -36.84, 174.78),
)
PORT_REGION = {p[0]: p[4] for p in PORTS}

LANES: tuple[tuple[str, str], ...] = (
    ("AEU", "Asia - North Europe"),
    ("AMD", "Asia - Mediterranean"),
    ("TPW", "Transpacific (Asia - US West Coast)"),
    ("AUE", "Asia - US East Coast"),
    ("ECS", "Asia - East Coast South America"),
    ("TAT", "Transatlantic"),
    ("AMI", "Asia - Middle East and India"),
    ("IAS", "Intra-Asia"),
)


@dataclass(frozen=True)
class Service:
    code: str
    name: str
    lane: str
    vessel_teu: int
    vessels: int
    headhaul: tuple[tuple[str, int], ...]  # (port, days from previous port)
    backhaul: tuple[tuple[str, int], ...]
    suez: bool = False  # diverted via the Cape of Good Hope during the Red Sea crisis
    cape_extra_days: int = 0
    headhaul_share: float = 0.68  # share of the service's cargo moving on the headhaul leg
    letters: tuple[str, str] = ("W", "E")  # voyage-number suffix for headhaul / backhaul

    @property
    def round_trip_days(self) -> int:
        return sum(d for _, d in self.headhaul) + sum(d for _, d in self.backhaul)


SERVICES: tuple[Service, ...] = (
    Service(
        "AEX", "Asia - North Europe Express", "AEU", 8500, 11,
        (("CNSHA", 0), ("CNNGB", 1), ("CNYTN", 3), ("SGSIN", 4), ("NLRTM", 21),
         ("DEHAM", 2), ("BEANR", 2), ("GBFXT", 1)),
        (("GBFXT", 0), ("NLRTM", 1), ("SGSIN", 22), ("CNYTN", 4), ("CNSHA", 3)),
        suez=True, cape_extra_days=11,
    ),
    Service(
        "AMX", "Asia - Mediterranean Express", "AMD", 6500, 9,
        (("CNTAO", 0), ("CNSHA", 2), ("CNXMN", 2), ("SGSIN", 4), ("GRPIR", 15),
         ("ITGOA", 3), ("ESVLC", 2), ("ESALG", 1)),
        (("ESALG", 0), ("GRPIR", 4), ("SGSIN", 16), ("CNTAO", 7)),
        suez=True, cape_extra_days=9,
    ),
    Service(
        "TPX", "Transpacific Express", "TPW", 6000, 6,
        (("CNYTN", 0), ("CNXMN", 1), ("CNSHA", 2), ("KRPUS", 2), ("USLAX", 11), ("USOAK", 2)),
        (("USOAK", 0), ("KRPUS", 12), ("CNYTN", 4)),
        headhaul_share=0.72, letters=("E", "W"),
    ),
    Service(
        "AUX", "Asia - US East Coast via Panama", "AUE", 5500, 9,
        (("CNNGB", 0), ("CNSHA", 1), ("KRPUS", 2), ("PABLB", 21), ("USSAV", 4),
         ("USCHS", 1), ("USNYC", 2)),
        (("USNYC", 0), ("USSAV", 2), ("PABLB", 5), ("KRPUS", 22), ("CNNGB", 3)),
        headhaul_share=0.7, letters=("E", "W"),
    ),
    Service(
        "ESX", "Asia - South America East Coast", "ECS", 4800, 8,
        (("CNSHA", 0), ("CNNGB", 1), ("SGSIN", 5), ("BRSSZ", 22), ("BRPNG", 1), ("ARBUE", 3),
         ("UYMVD", 1)),
        (("UYMVD", 0), ("BRSSZ", 3), ("SGSIN", 21), ("CNSHA", 5)),
        headhaul_share=0.64,
    ),
    Service(
        "TAX", "Transatlantic Express", "TAT", 3500, 5,
        (("NLRTM", 0), ("DEBRV", 1), ("FRLEH", 2), ("USNYC", 9), ("USSAV", 3), ("USHOU", 3)),
        (("USHOU", 0), ("USNYC", 5), ("NLRTM", 10)),
        headhaul_share=0.58,
    ),
    Service(
        "MEX", "Asia - Middle East and India Express", "AMI", 4500, 6,
        (("CNSHA", 0), ("CNNGB", 1), ("SGSIN", 5), ("MYPKG", 1), ("INNSA", 6), ("AEJEA", 3)),
        (("AEJEA", 0), ("OMSLL", 2), ("SGSIN", 8), ("CNSHA", 6)),
        headhaul_share=0.7,
    ),
    Service(
        "IAX", "Intra-Asia Shuttle", "IAS", 1700, 4,
        (("SGSIN", 0), ("MYPKG", 1), ("THLCH", 3), ("VNCMT", 2), ("HKHKG", 3), ("CNSHA", 2)),
        (("CNSHA", 0), ("KRPUS", 2), ("JPTYO", 2), ("TWKHH", 4), ("SGSIN", 4)),
        headhaul_share=0.55, letters=("N", "S"),
    ),
)

# Red Sea crisis: Suez services sail via the Cape of Good Hope for departures in this window.
RED_SEA_DIVERSION = (date(2024, 1, 1), date(2025, 6, 30))
# Grand Line booking-platform outage (cyber incident, see the incident report).
CYBER_OUTAGE = (date(2025, 6, 10), date(2025, 6, 14))
# Labour action at US East and Gulf Coast ports.
US_EAST_STRIKE = (date(2024, 10, 1), date(2024, 10, 3))
US_EAST_PORTS = ("USNYC", "USSAV", "USCHS", "USORF", "USHOU", "USMIA")
# Faulty reefer controllers from one leasing batch (claims spike).
REEFER_FAULT = (date(2025, 8, 1), date(2025, 9, 30))
REEFER_FAULT_LESSOR = "Coldline Leasing"
# Port congestion episodes: port, start, end, extra waiting hours (mean).
CONGESTION = (
    ("SGSIN", date(2024, 5, 15), date(2024, 7, 31), 40.0),
    ("NLRTM", date(2024, 6, 1), date(2024, 8, 31), 30.0),
    ("DEHAM", date(2024, 6, 1), date(2024, 9, 15), 36.0),
    ("BEANR", date(2025, 4, 1), date(2025, 6, 15), 28.0),
    ("CNSHA", date(2026, 1, 10), date(2026, 2, 20), 20.0),
)

CONTAINER_TYPES = ("20DV", "40DV", "40HC", "20RF", "40RF", "20TK", "40OT")
CONTAINER_TEU = {"20DV": 1.0, "40DV": 2.0, "40HC": 2.0, "20RF": 1.0, "40RF": 2.0,
                 "20TK": 1.0, "40OT": 2.0}

COMMODITIES = (
    # name, reefer, hazardous, weight
    ("Consumer electronics", False, False, 9),
    ("Furniture", False, False, 7),
    ("Apparel and footwear", False, False, 9),
    ("Auto parts", False, False, 7),
    ("Machinery and equipment", False, False, 6),
    ("Toys and sporting goods", False, False, 5),
    ("Household appliances", False, False, 6),
    ("Plastics and rubber", False, False, 5),
    ("Paper and pulp", False, False, 4),
    ("Steel products", False, False, 4),
    ("Building materials", False, False, 4),
    ("Cotton and textiles", False, False, 3),
    ("Wine and beverages", False, False, 2),
    ("Industrial chemicals", False, True, 3),
    ("Lithium-ion batteries", False, True, 2),
    ("Paints and coatings", False, True, 1),
    ("Frozen meat", True, False, 3),
    ("Fresh fruit", True, False, 3),
    ("Seafood", True, False, 2),
    ("Pharmaceuticals", True, False, 2),
    ("Dairy products", True, False, 1),
)

INDUSTRIES = ("Retail", "Electronics", "Automotive", "Chemicals", "Food and beverage",
              "Pharmaceuticals", "Apparel", "Industrial machinery", "Furniture",
              "Agriculture", "Freight forwarding", "Building materials")

INCOTERMS = ("FOB", "CIF", "CFR", "EXW", "DAP", "DDP", "FCA")
