"""The development world: three tax firms (SKR03 and SKR04), nine clients of very different kinds,
fifteen months of business from July 2025 to September 2026.

July 2025 to June 2026 is history (the firms booked it in DATEV); July to September 2026 are the
months the agent closes. Everything is invented: names, IBANs, VAT ids. Defects a real month has
are put in on purpose: missing receipts, incomplete invoices, meals without details, private card
payments, new suppliers, cash discounts, invoices paid together, foreign suppliers.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from kanzlei_sim.ids import iban, seeded, tax_no, vat_id
from kanzlei_sim.scenario import Client, DocLine, DocSpec, Event, Firm, Party, Truth
from kanzlei_sim.truth import gross_cents

HISTORY = [f"2025-{m:02d}" for m in range(7, 13)] + [f"2026-{m:02d}" for m in range(1, 7)]
DEV = ["2026-07", "2026-08", "2026-09"]
ALL = HISTORY + DEV

NOTE_RC = "Steuerschuldnerschaft des Leistungsempfängers"


@dataclass
class V:
    """A counterparty and how business with it goes."""

    key: str
    name: str
    family: str
    tax: str
    net: float | tuple[float, float]
    freq: float | str = 1.0  # probability per month, or "q" (quarterly), "y" (once a year, in month `day_month`)
    method: str = "ueberweisung"
    formats: dict[str, float] = field(default_factory=lambda: {"pdf": 1.0})
    items: tuple[str, ...] = ("Leistung",)
    country: str = "DE"
    role: str = "supplier"
    day: int = 5
    rates: tuple[tuple[int, float], ...] | None = None  # mixed rates: (rate, share of net)
    skonto: float = 0.0  # probability of paying with 2 % discount (OPOS)
    reference: str = "{doc}"
    per_month: int = 1
    new_each_time: bool = False  # card payments at ever new places
    private: bool = False
    meals_details: float = 0.0
    city: str = ""
    kleinunternehmer: bool = False
    yearly_month: int = 1


def _rng(*parts: object) -> random.Random:
    return seeded("world", *parts)


# --- names for places that change every time (card payments) -------------------------------------

STATIONS = [
    "Tankstelle Nordring",
    "Tankhof Am Wall",
    "Autohof Süd",
    "Tankpunkt Lindenau",
    "Station Elbbrücke",
    "Tankcenter West",
    "Freie Tankstelle Bauer",
    "Tank & Wasch Krüger",
]
RESTAURANTS = [
    "Trattoria Da Paolo",
    "Gasthaus Zum Anker",
    "Bistro Lindenhof",
    "Restaurant Speicher 7",
    "Ristorante Bella Vista",
    "Wirtshaus am Markt",
    "Brasserie Lumière",
    "Sushi Mori",
    "Steakhaus Rindermarkt",
    "Café Ratskeller",
]
HOTELS = [
    "Hotel Am Stadtpark",
    "Hotel Hafenblick",
    "Parkhotel Sonnenhof",
    "Hotel Kranich",
    "Hotel Zur Post",
    "Business Inn Messe",
    "Hotel Altstadtquartier",
]
SUPERMARKETS = [
    "Frischemarkt Hansen",
    "Supermarkt Edelweiß",
    "Nahkauf Lindner",
    "Drogerie Sonnenschein",
    "Biomarkt Grünkorb",
    "Streamflix Abo",
    "Modehaus Behrens",
]
OFFICE = ["Bürowelt Schreiber GmbH", "Papeterie Hofmann", "Büroversand Direkt GmbH"]
TECH = ["Technikhaus Bergmann GmbH", "Computerladen Ost", "IT-Versand Pixelpunkt GmbH"]


def common(
    client_key: str,
    city: str,
    *,
    rent_tax: str = "NONE",
    owner: str | None = None,
    employees: int = 0,
    vat: bool = True,
) -> list[V]:
    v = [
        V(
            "tel",
            "Fernmeldewerk Mitte GmbH",
            "telecom",
            "V19",
            _rng(client_key, "tel").choice([39.90, 49.95, 64.90, 89.90]),
            1.0,
            "lastschrift",
            {"xrechnung-ubl": 0.5, "pdf": 0.5},
            ("Mobilfunk Business Tarif", "Festnetz und Internet Glasfaser"),
            day=12,
            reference="Rechnung {doc} Kundennr 88{n}",
        ),
        V(
            "strom",
            f"Stadtwerke {city}",
            "utilities",
            "V19",
            _rng(client_key, "strom").choice([95.0, 140.0, 210.0, 320.0]),
            1.0,
            "lastschrift",
            {"zugferd": 0.6, "pdf": 0.4},
            ("Abschlag Strom", "Abschlag Gas"),
            day=15,
            reference="Abschlag {month} Vertragskonto 40{n}",
        ),
        V(
            "miete",
            f"Hausverwaltung {_rng(client_key, 'hv').choice(['Krämer', 'Albrecht', 'Neumann', 'Vogel'])} GmbH",
            "rent",
            rent_tax,
            _rng(client_key, "miete").choice([850.0, 1250.0, 1680.0, 2400.0]),
            1.0,
            "ueberweisung",
            {"none": 1.0},
            ("Miete Gewerberäume",),
            day=2,
            reference="Miete {month} Objekt {n}",
        ),
        V(
            "vers",
            "Versicherungskammer Nordost VVaG",
            "insurance",
            "NONE",
            _rng(client_key, "vers").choice([180.0, 245.5, 410.0]),
            "q",
            "lastschrift",
            {"none": 1.0},
            ("Betriebshaftpflicht",),
            day=1,
            reference="Beitrag Betriebshaftpflicht Vers-Nr {n}",
        ),
        V(
            "bank",
            "Entgelte Kontoführung",
            "bank_fees",
            "NONE",
            (8.5, 24.9),
            1.0,
            "lastschrift",
            {"none": 1.0},
            ("Kontoführung",),
            day=30,
            reference="Abrechnung {month} Kontoführung und Buchungsposten",
        ),
        V(
            "buero",
            _rng(client_key, "buero").choice(OFFICE),
            "office_supplies",
            "V19",
            (25.0, 180.0),
            0.45,
            "ueberweisung",
            {"zugferd": 0.3, "pdf": 0.7},
            ("Kopierpapier A4 80g", "Toner schwarz", "Ordner breit", "Haftnotizen", "Briefumschläge DIN lang"),
            day=18,
        ),
        V(
            "post",
            "Kurier24 Paketdienst GmbH",
            "postage",
            "V19",
            (14.0, 95.0),
            0.5,
            "lastschrift",
            {"xrechnung-ubl": 0.5, "pdf": 0.5},
            ("Paketversand national", "Expressversand"),
            day=20,
            reference="Versandrechnung {doc}",
        ),
        V(
            "tank",
            "Tankstelle",
            "fuel",
            "V19",
            (38.0, 92.0),
            0.9,
            "karte",
            {"pdf": 1.0},
            ("Super E10", "Diesel"),
            day=9,
            new_each_time=True,
            per_month=2,
        ),
        V(
            "essen",
            "Restaurant",
            "meals",
            "V19",
            (35.0, 190.0),
            0.45,
            "karte",
            {"pdf": 1.0},
            ("Speisen", "Getränke"),
            day=14,
            new_each_time=True,
            rates=((19, 1.0),),
            meals_details=0.3,
        ),
        V(
            "bahn",
            "Fernzug Reisen AG",
            "travel_transport",
            "V7",
            (29.0, 139.0),
            0.35,
            "karte",
            {"xrechnung-ubl": 0.5, "pdf": 0.5},
            ("Fahrkarte Fernverkehr 2. Klasse",),
            day=6,
        ),
        V(
            "hotel",
            "Hotel",
            "travel_lodging",
            "V7",
            (89.0, 260.0),
            0.25,
            "karte",
            {"pdf": 0.6, "zugferd": 0.4},
            ("Übernachtung", "Frühstück"),
            day=7,
            new_each_time=True,
            rates=((7, 0.86), (19, 0.14)),
        ),
        V(
            "kanzlei",
            "Steuerberatung (eigene Kanzlei)",
            "advice",
            "V19",
            _rng(client_key, "stb").choice([240.0, 380.0, 520.0]),
            1.0,
            "lastschrift",
            {"xrechnung-ubl": 1.0},
            ("Finanzbuchhaltung laut Vergütungsverordnung", "Lohnabrechnung"),
            day=25,
            reference="Honorarrechnung {doc}",
        ),
        V(
            "privat",
            "Einkauf",
            "private_withdrawal",
            "NONE",
            (12.0, 140.0),
            0.25,
            "karte",
            {"none": 1.0},
            ("Einkauf",),
            day=21,
            new_each_time=True,
            private=True,
        ),
    ]
    if vat:
        v.append(
            V(
                "fa_ust",
                f"Finanzamt {city}",
                "vat_payment",
                "NONE",
                (300.0, 2600.0),
                1.0,
                "ueberweisung",
                {"none": 1.0},
                ("Umsatzsteuer",),
                day=10,
                reference="USt-VA {prev} StNr {stnr}",
                role="other",
            )
        )
    if owner:
        v.append(
            V(
                "entnahme",
                owner,
                "private_withdrawal",
                "NONE",
                _rng(client_key, "ent").choice([1500.0, 2200.0, 3000.0]),
                1.0,
                "ueberweisung",
                {"none": 1.0},
                ("Privat",),
                day=28,
                reference="Übertrag privat",
                role="other",
            )
        )
    if employees:
        v += [
            V(
                "lohn",
                "Gehaltszahlung",
                "payroll",
                "NONE",
                (2100.0, 3400.0),
                1.0,
                "ueberweisung",
                {"none": 1.0},
                ("Gehalt",),
                day=27,
                reference="Gehalt {month}",
                per_month=employees,
                role="other",
            ),
            V(
                "kk",
                _rng(client_key, "kk").choice(["AOK Nordost", "Techniker Krankenkasse", "Barmer", "IKK classic"]),
                "social_security",
                "NONE",
                (900.0 * employees, 1300.0 * employees),
                1.0,
                "lastschrift",
                {"none": 1.0},
                ("Beitragsnachweis",),
                day=26,
                reference="Beitragsnachweis {month} Betriebsnr 4{n}",
                role="other",
            ),
            V(
                "fa_lst",
                f"Finanzamt {city}",
                "wage_tax",
                "NONE",
                (180.0 * employees, 420.0 * employees),
                1.0,
                "ueberweisung",
                {"none": 1.0},
                ("Lohnsteuer",),
                day=10,
                reference="LSt-Anmeldung {prev} StNr {stnr}",
                role="other",
            ),
        ]
    return v


CLIENTS: list[dict[str, Any]] = [
    {
        "firm": "hartmann",
        "id": "hp-10101",
        "nr": 10101,
        "name": "Elektro Baumann GmbH",
        "form": "GmbH",
        "industry": "Elektroinstallation",
        "method": "opos",
        "regime": "soll",
        "city": "Leipzig",
        "contact": "Frank Baumann",
        "employees": 4,
        "rent": "V19",
        "own": [
            V(
                "kessler",
                "Elektrogroßhandel Kessler GmbH & Co. KG",
                "goods",
                "V19",
                (380.0, 3600.0),
                1.0,
                "ueberweisung",
                {"zugferd": 0.7, "xrechnung-cii": 0.3},
                (
                    "NYM-J 3x1,5 Ring 100 m",
                    "Schalterprogramm reinweiß",
                    "Unterverteiler 3-reihig",
                    "FI-Schutzschalter 40A",
                    "LED-Panel 62x62",
                ),
                per_month=3,
                skonto=0.6,
                day=4,
                reference="RE {doc} abzgl. Skonto",
            ),
            V(
                "kabelwerk",
                "Kabelwerk Ost GmbH",
                "goods",
                "V19",
                (250.0, 1400.0),
                0.6,
                "ueberweisung",
                {"xrechnung-ubl": 1.0},
                ("Erdkabel NYY-J 5x2,5", "Kabelkanal 60x110"),
                day=11,
            ),
            V(
                "lindner",
                "Montageservice Lindner GmbH",
                "subcontractor",
                "RC_BAU19",
                (1500.0, 5800.0),
                0.5,
                "ueberweisung",
                {"pdf": 0.5, "zugferd": 0.5},
                ("Montage Elektroinstallation Bauvorhaben", "Kabelzug und Unterputzarbeiten"),
                day=16,
            ),
            V(
                "leasing",
                "Autoleasing Nord GmbH",
                "vehicle_leasing",
                "V19",
                389.0,
                1.0,
                "lastschrift",
                {"xrechnung-ubl": 1.0},
                ("Leasingrate Transporter",),
                day=3,
                reference="Leasingrate {month} Vertrag LV{n}",
            ),
            V(
                "werkzeug",
                "Werkzeugzentrum Reuter GmbH",
                "equipment",
                "V19",
                (60.0, 1900.0),
                0.3,
                "ueberweisung",
                {"pdf": 0.5, "zugferd": 0.5},
                ("Akku-Bohrhammer Set", "Leitungssucher", "Installationstester", "Werkzeugkoffer"),
                day=13,
            ),
            V(
                "kunde_wohnbau",
                "Wohnbau Saxonia GmbH",
                "revenue",
                "RC_OUT",
                (4000.0, 16000.0),
                0.6,
                "gutschrift",
                {"zugferd": 1.0},
                ("Elektroinstallation Bauvorhaben Mehrfamilienhaus",),
                role="customer",
                day=8,
            ),
            V(
                "kunde_praxis",
                "Zahnarztpraxis Dr. Ott",
                "revenue",
                "U19",
                (800.0, 4200.0),
                0.7,
                "gutschrift",
                {"xrechnung-ubl": 1.0},
                ("Wartung Elektroanlage", "Installation Beleuchtung"),
                role="customer",
                day=12,
            ),
            V(
                "kunde_hotel",
                "Hotel Am Stadtpark Betriebs GmbH",
                "revenue",
                "U19",
                (600.0, 3000.0),
                0.6,
                "gutschrift",
                {"xrechnung-cii": 1.0},
                ("Störungsbeseitigung", "E-Check Prüfung"),
                role="customer",
                day=17,
            ),
        ],
    },
    {
        "firm": "hartmann",
        "id": "hp-10102",
        "nr": 10102,
        "name": "Nordlicht IT-Beratung UG (haftungsbeschränkt)",
        "form": "UG",
        "industry": "IT-Beratung",
        "method": "direkt",
        "regime": "ist",
        "city": "Leipzig",
        "contact": "Sina Wolf",
        "employees": 2,
        "own": [
            V(
                "cloudbyte",
                "Cloudbyte Ltd",
                "software",
                "RC_EU19",
                (19.0, 68.0),
                1.0,
                "karte",
                {"pdf": 1.0},
                ("Cloud Hosting Plan", "Object Storage"),
                country="IE",
                day=2,
            ),
            V(
                "pixelforge",
                "Pixelforge Inc.",
                "software",
                "RC_DRITT19",
                (12.0, 45.0),
                1.0,
                "karte",
                {"pdf": 1.0},
                ("Design Tool Team Plan",),
                country="US",
                day=4,
            ),
            V(
                "devtools",
                "Devtools Software GmbH",
                "software",
                "V19",
                49.0,
                1.0,
                "lastschrift",
                {"xrechnung-ubl": 1.0},
                ("Lizenz IDE Team 5 Nutzer",),
                day=1,
            ),
            V(
                "technik",
                "Technikhaus Bergmann GmbH",
                "equipment",
                "V19",
                (40.0, 1600.0),
                0.3,
                "ueberweisung",
                {"zugferd": 0.6, "pdf": 0.4},
                ("Notebook 14 Zoll", "Monitor 27 Zoll", "USB-C Dock", "Headset"),
                day=19,
            ),
            V(
                "akademie",
                "Akademie für Softwarearchitektur GmbH",
                "training",
                "V19",
                (290.0, 890.0),
                0.15,
                "ueberweisung",
                {"xrechnung-ubl": 1.0},
                ("Seminar Cloud-Architektur",),
                day=22,
            ),
            V(
                "kunde_hafen",
                "Hafenlogistik Rostock GmbH",
                "revenue",
                "U19",
                (3800.0, 9200.0),
                1.0,
                "gutschrift",
                {"xrechnung-ubl": 1.0},
                ("Beratung Systemintegration",),
                role="customer",
                day=20,
            ),
            V(
                "kunde_bright",
                "Brightwave B.V.",
                "revenue",
                "EU_SVC",
                (2500.0, 6400.0),
                0.8,
                "gutschrift",
                {"pdf": 1.0},
                ("Consulting services data platform",),
                role="customer",
                country="NL",
                day=24,
            ),
        ],
    },
    {
        "firm": "hartmann",
        "id": "hp-10103",
        "nr": 10103,
        "name": "Physiotherapie Sommer",
        "form": "Einzelunternehmen",
        "industry": "Physiotherapie",
        "method": "direkt",
        "regime": "befreit",
        "city": "Leipzig",
        "contact": "Jana Sommer",
        "employees": 3,
        "owner": "Jana Sommer",
        "vat": False,
        "own": [
            V(
                "medbedarf",
                "Medizinbedarf Thalheim GmbH",
                "goods",
                "NONE",
                (60.0, 480.0),
                0.6,
                "ueberweisung",
                {"zugferd": 0.5, "pdf": 0.5},
                ("Massageöl 5 l", "Kinesiotape", "Therapieliegen-Bezug"),
                day=8,
            ),
            V(
                "aok",
                "AOK Nordost Abrechnungszentrum",
                "revenue",
                "FREI",
                (6500.0, 9800.0),
                1.0,
                "gutschrift",
                {"none": 1.0},
                ("Heilmittelabrechnung",),
                role="customer",
                day=21,
                reference="Abrechnung Heilmittel {prev} IK 26{n}",
            ),
            V(
                "privatpat",
                "Privatpatient",
                "revenue",
                "FREI",
                (90.0, 420.0),
                0.8,
                "gutschrift",
                {"pdf": 1.0},
                ("Krankengymnastik 6 Einheiten",),
                role="customer",
                day=16,
                per_month=2,
                new_each_time=True,
            ),
        ],
    },
    {
        "firm": "brandt",
        "id": "bs-20201",
        "nr": 20201,
        "name": "Gartenbau Kröger e.K.",
        "form": "e.K.",
        "industry": "Garten- und Landschaftsbau",
        "method": "direkt",
        "regime": "ist",
        "city": "Hannover",
        "contact": "Ole Kröger",
        "employees": 3,
        "owner": "Ole Kröger",
        "own": [
            V(
                "baumschule",
                "Baumschule Ammerland GmbH",
                "goods",
                "V7",
                (300.0, 2400.0),
                0.8,
                "ueberweisung",
                {"zugferd": 0.5, "pdf": 0.5},
                ("Heckenpflanzen Liguster", "Rasensaat Sport 10 kg", "Obstbäume Halbstamm"),
                day=9,
            ),
            V(
                "wessel",
                "Baustoffhandel Wessel GmbH",
                "goods",
                "V19",
                (180.0, 1900.0),
                0.8,
                "ueberweisung",
                {"xrechnung-ubl": 0.5, "pdf": 0.5},
                ("Pflastersteine grau", "Splitt 2/5", "Randsteine Beton"),
                day=13,
            ),
            V(
                "werkstatt",
                "Autohaus Pieper GmbH",
                "vehicle_repair",
                "V19",
                (140.0, 950.0),
                0.2,
                "ueberweisung",
                {"pdf": 1.0},
                ("Inspektion Transporter", "Reifenwechsel"),
                day=23,
            ),
            V(
                "maschinen",
                "Gartentechnik Hollmann KG",
                "equipment",
                "V19",
                (90.0, 2600.0),
                0.2,
                "ueberweisung",
                {"zugferd": 1.0},
                ("Motorsense", "Rasenmäher Profi", "Heckenschere Akku"),
                day=18,
            ),
            V(
                "sub_pflaster",
                "Pflasterbau Demir",
                "subcontractor",
                "V19",
                (900.0, 3800.0),
                0.3,
                "ueberweisung",
                {"pdf": 1.0},
                ("Pflasterarbeiten Auffahrt",),
                day=27,
            ),
            V(
                "kunde_privat",
                "Privatkunde",
                "revenue",
                "U19",
                (450.0, 3800.0),
                1.0,
                "gutschrift",
                {"pdf": 1.0},
                ("Gartenpflege", "Heckenschnitt", "Neuanlage Rasenfläche"),
                role="customer",
                day=15,
                per_month=3,
                new_each_time=True,
            ),
            V(
                "kunde_wohnungsbau",
                "Wohnungsbaugesellschaft Linden eG",
                "revenue",
                "U19",
                (1200.0, 4800.0),
                0.7,
                "gutschrift",
                {"xrechnung-ubl": 1.0},
                ("Grünflächenpflege Wohnanlage",),
                role="customer",
                day=25,
            ),
        ],
    },
    {
        "firm": "brandt",
        "id": "bs-20202",
        "nr": 20202,
        "name": "Kistenwerk Handels GmbH",
        "form": "GmbH",
        "industry": "Großhandel Verpackungen",
        "method": "opos",
        "regime": "soll",
        "city": "Hannover",
        "contact": "Merve Yıldız",
        "employees": 5,
        "rent": "V19",
        "own": [
            V(
                "lodz",
                "Kartonagen Lodz Sp. z o.o.",
                "goods",
                "IGE19",
                (1800.0, 7400.0),
                0.9,
                "ueberweisung",
                {"pdf": 0.5, "xrechnung-ubl": 0.5},
                ("Faltkartons 400x300x200", "Versandkartons zweiwellig"),
                country="PL",
                day=6,
            ),
            V(
                "hollandia",
                "Verpackung Hollandia B.V.",
                "goods",
                "IGE19",
                (900.0, 3300.0),
                0.6,
                "ueberweisung",
                {"xrechnung-cii": 1.0},
                ("Luftpolsterfolie Rolle", "Stretchfolie"),
                country="NL",
                day=12,
            ),
            V(
                "papierfabrik",
                "Papierfabrik Sachsen GmbH",
                "goods",
                "V19",
                (700.0, 4200.0),
                0.9,
                "ueberweisung",
                {"zugferd": 1.0},
                ("Packpapier Rolle 50 cm", "Seidenpapier"),
                skonto=0.5,
                day=17,
            ),
            V(
                "adnet",
                "Adnet Ireland Ltd",
                "advertising",
                "RC_EU19",
                (150.0, 900.0),
                1.0,
                "karte",
                {"pdf": 1.0},
                ("Online advertising campaign",),
                country="IE",
                day=3,
            ),
            V(
                "shopsoft",
                "Shopsoftware Nord GmbH",
                "software",
                "V19",
                129.0,
                1.0,
                "lastschrift",
                {"xrechnung-ubl": 1.0},
                ("Shop-System Lizenz Business",),
                day=1,
            ),
            V(
                "kunde_logistik",
                "Logistikzentrum Peine GmbH",
                "revenue",
                "U19",
                (2400.0, 9800.0),
                1.0,
                "gutschrift",
                {"xrechnung-ubl": 1.0},
                ("Faltkartons Lieferung",),
                role="customer",
                day=10,
                per_month=2,
            ),
            V(
                "kunde_austria",
                "Versandhaus Alpenkiste GmbH",
                "revenue",
                "IGL",
                (1800.0, 6000.0),
                0.7,
                "gutschrift",
                {"xrechnung-cii": 1.0},
                ("Versandkartons Lieferung",),
                role="customer",
                country="AT",
                day=19,
            ),
        ],
    },
    {
        "firm": "brandt",
        "id": "bs-20203",
        "nr": 20203,
        "name": "Fotostudio Aydın",
        "form": "Einzelunternehmen",
        "industry": "Fotografie",
        "method": "direkt",
        "regime": "klein",
        "city": "Hannover",
        "contact": "Deniz Aydın",
        "employees": 0,
        "owner": "Deniz Aydın",
        "vat": False,
        "own": [
            V(
                "fotolab",
                "Fotolabor Lichtwerk GmbH",
                "goods",
                "V19",
                (45.0, 260.0),
                0.7,
                "ueberweisung",
                {"pdf": 1.0},
                ("Fotoabzüge Fine Art", "Fotobuch Hardcover"),
                day=11,
            ),
            V(
                "kamera",
                "Kamerahaus Seidel GmbH",
                "equipment",
                "V19",
                (80.0, 2100.0),
                0.2,
                "ueberweisung",
                {"zugferd": 0.5, "pdf": 0.5},
                ("Objektiv 50 mm", "Speicherkarte 128 GB", "Studioblitz"),
                day=20,
            ),
            V(
                "kunde_hochzeit",
                "Kundin Hochzeitsfotografie",
                "revenue",
                "NONE",
                (350.0, 1900.0),
                0.9,
                "gutschrift",
                {"pdf": 1.0},
                ("Hochzeitsreportage",),
                role="customer",
                day=14,
                new_each_time=True,
            ),
        ],
    },
    {
        "firm": "yilmaz",
        "id": "ys-30301",
        "nr": 30301,
        "name": "Agentur Fünfeck GmbH",
        "form": "GmbH",
        "industry": "Werbeagentur",
        "method": "opos",
        "regime": "soll",
        "city": "Köln",
        "contact": "Paula Fink",
        "employees": 6,
        "rent": "V19",
        "own": [
            V(
                "koch",
                "Grafikdesign Mira Koch",
                "subcontractor",
                "NONE",
                (600.0, 2400.0),
                0.7,
                "ueberweisung",
                {"pdf": 1.0},
                ("Gestaltung Kampagnenmotive",),
                day=14,
                kleinunternehmer=True,
            ),
            V(
                "feldmann",
                "Texterei Feldmann",
                "subcontractor",
                "V19",
                (450.0, 1800.0),
                0.6,
                "ueberweisung",
                {"xrechnung-ubl": 0.5, "pdf": 0.5},
                ("Texte Website Relaunch", "Konzeption Claims"),
                day=21,
            ),
            V(
                "pixelforge",
                "Pixelforge Inc.",
                "software",
                "RC_DRITT19",
                (36.0, 135.0),
                1.0,
                "karte",
                {"pdf": 1.0},
                ("Design Tool Team Plan",),
                country="US",
                day=4,
            ),
            V(
                "cloudbyte",
                "Cloudbyte Ltd",
                "software",
                "RC_EU19",
                (25.0, 90.0),
                1.0,
                "karte",
                {"pdf": 1.0},
                ("Cloud Hosting Plan",),
                country="IE",
                day=2,
            ),
            V(
                "druck",
                "Druckerei Weißhaupt GmbH",
                "advertising",
                "V19",
                (220.0, 1900.0),
                0.4,
                "ueberweisung",
                {"zugferd": 1.0},
                ("Plakate A1", "Flyer DIN lang 5.000 Stück"),
                day=9,
            ),
            V(
                "kunde_brauerei",
                "Brauhaus Severin GmbH",
                "revenue",
                "U19",
                (3500.0, 12000.0),
                1.0,
                "gutschrift",
                {"xrechnung-ubl": 1.0},
                ("Kampagne Frühjahr Konzeption und Gestaltung",),
                role="customer",
                day=11,
            ),
            V(
                "kunde_nordvik",
                "Studio Nordvik AB",
                "revenue",
                "EU_SVC",
                (2000.0, 5500.0),
                0.6,
                "gutschrift",
                {"pdf": 1.0},
                ("Brand design services",),
                role="customer",
                country="SE",
                day=23,
            ),
        ],
    },
    {
        "firm": "yilmaz",
        "id": "ys-30302",
        "nr": 30302,
        "name": "Weinhandel Lorenz KG",
        "form": "KG",
        "industry": "Weinhandel",
        "method": "direkt",
        "regime": "ist",
        "city": "Köln",
        "contact": "Bernd Lorenz",
        "employees": 2,
        "owner": "Bernd Lorenz",
        "own": [
            V(
                "weingut",
                "Weingut Kessler-Rau",
                "goods",
                "V19",
                (600.0, 4800.0),
                0.9,
                "ueberweisung",
                {"zugferd": 0.5, "pdf": 0.5},
                ("Riesling trocken 0,75 l", "Spätburgunder 0,75 l"),
                day=7,
            ),
            V(
                "bodega",
                "Bodega del Sur S.L.",
                "goods",
                "IGE19",
                (1200.0, 5200.0),
                0.5,
                "ueberweisung",
                {"xrechnung-ubl": 1.0},
                ("Tempranillo Crianza 0,75 l",),
                country="ES",
                day=15,
            ),
            V(
                "kartons",
                "Kistenwerk Handels GmbH",
                "goods",
                "V19",
                (90.0, 420.0),
                0.4,
                "ueberweisung",
                {"xrechnung-ubl": 1.0},
                ("Weinversandkartons 6er",),
                day=12,
            ),
            V(
                "leasing",
                "Autoleasing Nord GmbH",
                "vehicle_leasing",
                "V19",
                329.0,
                1.0,
                "lastschrift",
                {"xrechnung-ubl": 1.0},
                ("Leasingrate Kombi",),
                day=3,
                reference="Leasingrate {month} Vertrag LV{n}",
            ),
            V(
                "kunde_rest",
                "Restaurant",
                "revenue",
                "U19",
                (380.0, 2800.0),
                1.0,
                "gutschrift",
                {"xrechnung-ubl": 0.5, "pdf": 0.5},
                ("Weinlieferung",),
                role="customer",
                day=18,
                per_month=3,
                new_each_time=True,
            ),
        ],
    },
    {
        "firm": "yilmaz",
        "id": "ys-30303",
        "nr": 30303,
        "name": "Rechtsanwältin Dr. Lea Brenner",
        "form": "Einzelunternehmen",
        "industry": "Rechtsanwaltskanzlei",
        "method": "direkt",
        "regime": "ist",
        "vat_period": "quartal",
        "city": "Köln",
        "contact": "Lea Brenner",
        "employees": 1,
        "owner": "Lea Brenner",
        "rent": "V19",
        "own": [
            V(
                "buecher",
                "Fachbuchhandlung Juris & Co. KG",
                "office_supplies",
                "V7",
                (39.0, 240.0),
                0.5,
                "ueberweisung",
                {"xrechnung-ubl": 0.5, "pdf": 0.5},
                ("Kommentar BGB 85. Auflage", "Zeitschrift NJW Abonnement"),
                day=10,
            ),
            V(
                "kammer",
                "Rechtsanwaltskammer Köln",
                "memberships",
                "NONE",
                340.0,
                "y",
                "ueberweisung",
                {"none": 1.0},
                ("Kammerbeitrag",),
                day=15,
                yearly_month=2,
                reference="Kammerbeitrag {year} Mitgliedsnr {n}",
            ),
            V(
                "haftpflicht",
                "Berufshaftpflicht Assekuranz AG",
                "insurance",
                "NONE",
                410.0,
                "q",
                "lastschrift",
                {"none": 1.0},
                ("Berufshaftpflicht",),
                day=1,
            ),
            V(
                "mandant",
                "Mandant",
                "revenue",
                "U19",
                (450.0, 3900.0),
                1.0,
                "gutschrift",
                {"pdf": 0.6, "xrechnung-ubl": 0.4},
                ("Beratung und Vertretung", "Vertragsgestaltung"),
                role="customer",
                day=16,
                per_month=3,
                new_each_time=True,
            ),
        ],
    },
]

FIRMS = {
    "hartmann": ("Steuerkanzlei Hartmann & Partner", "Leipzig", "SKR03", 41230, None),
    "brandt": ("Steuerbüro Brandt", "Hannover", "SKR04", 52740, None),
    "yilmaz": ("Kanzlei Yılmaz Steuerberatung", "Köln", "SKR03", 63815, date(2026, 3, 1)),
}
STAFF = {
    "hartmann": [
        ("c.hartmann", "Claudia Hartmann", "berater"),
        ("t.voss", "Tobias Voss", "buchhaltung"),
        ("n.krause", "Nadine Krause", "buchhaltung"),
    ],
    "brandt": [("m.brandt", "Martin Brandt", "berater"), ("s.akin", "Selin Akın", "buchhaltung")],
    "yilmaz": [("e.yilmaz", "Emre Yılmaz", "berater"), ("j.wagner", "Julia Wagner", "buchhaltung")],
}
GROUP_STAFF = [("l.fde", "Lena Hoffmann", "gruppe")]
PEOPLE = [
    "Anna Schulz",
    "Lukas Becker",
    "Mia Wagner",
    "Jonas Hoffmann",
    "Lea Richter",
    "Finn Klein",
    "Emma Wolf",
    "Paul Schröder",
    "Hanna Neumann",
    "Leon Braun",
    "Sophie Zimmermann",
    "Noah Krüger",
]


def _month_dates(period: str) -> tuple[date, date]:
    y, m = int(period[:4]), int(period[5:7])
    start = date(y, m, 1)
    end = date(y + (m // 12), m % 12 + 1, 1) - timedelta(days=1)
    return start, end


def _prev(period: str) -> str:
    y, m = int(period[:4]), int(period[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def _party_for(client_key: str, v: V, idx: int, rng: random.Random) -> Party:
    if v.new_each_time:
        if v.family == "fuel":
            base = rng.choice(STATIONS)
        elif v.family == "meals":
            base = rng.choice(RESTAURANTS)
        elif v.family == "travel_lodging":
            base = rng.choice(HOTELS)
        elif v.private:
            base = rng.choice(SUPERMARKETS)
        elif v.role == "customer" and v.name in (
            "Privatkunde",
            "Privatpatient",
            "Kundin Hochzeitsfotografie",
            "Mandant",
        ):
            base = rng.choice(PEOPLE)
        elif v.role == "customer":
            base = rng.choice(RESTAURANTS)
        else:
            base = v.name
        city = rng.choice(["Leipzig", "Hannover", "Köln", "Berlin", "Hamburg", "München", "Dresden", "Frankfurt"])
        name = f"{base} {city}" if v.family in ("fuel",) else base
        key = f"{v.key}:{name}"
    else:
        name, key = v.name, v.key
    country = v.country
    person = v.role == "customer" and " " in name and name.split()[0] in {p.split()[0] for p in PEOPLE}
    return Party(
        key=key,
        name=name,
        role=v.role,
        iban=None if v.method == "karte" else iban(country if v.role != "other" else "DE", client_key + key),
        vat_id=None if (person or v.role == "other" or v.kleinunternehmer) else vat_id(country, key),
        tax_no=tax_no(key) if v.kleinunternehmer else None,
        country=country,
        street=f"{rng.choice(['Hauptstraße', 'Industriestraße', 'Am Markt', 'Bahnhofstraße', 'Gewerbering'])} {rng.randrange(1, 120)}",
        postcode=f"{rng.randrange(10000, 99999)}",
        city=rng.choice(["Leipzig", "Hannover", "Köln", "Berlin", "Bremen", "Kassel"])
        if country == "DE"
        else {
            "IE": "Dublin",
            "US": "San Francisco",
            "NL": "Utrecht",
            "PL": "Łódź",
            "AT": "Innsbruck",
            "SE": "Malmö",
            "ES": "Valencia",
        }.get(country, ""),
    )


def build() -> list[Firm]:
    firms: dict[str, Firm] = {}
    for fid, (name, city, ch, nr, llm) in FIRMS.items():
        staff = [{"login": login, "name": n, "role": role} for login, n, role in STAFF[fid]]
        if fid == "hartmann":
            staff += [{"login": login, "name": n, "role": role} for login, n, role in GROUP_STAFF]
        firms[fid] = Firm(fid, name, city, ch, nr, llm, staff)
    for spec in CLIENTS:
        firm = firms[spec["firm"]]
        client = _client(spec, firm)
        firm.clients.append(client)
    return list(firms.values())


def _client(spec: dict[str, Any], firm: Firm) -> Client:
    key = spec["id"]
    rng = _rng(key, "client")
    regime = spec["regime"]
    vendors = (
        common(
            key,
            spec["city"],
            rent_tax=spec.get("rent", "NONE"),
            owner=spec.get("owner"),
            employees=spec.get("employees", 0),
            vat=spec.get("vat", True) and regime not in ("klein", "befreit"),
        )
        + spec["own"]
    )
    if regime in ("klein", "befreit"):
        vendors = [replace_tax(v, regime) for v in vendors]
    accountants = [s["login"] for s in firm.staff if s["role"] == "buchhaltung"]
    client = Client(
        id=key,
        mandant_nr=spec["nr"],
        name=spec["name"],
        legal_form=spec["form"],
        industry=spec["industry"],
        booking_method=spec["method"],
        vat_regime=regime,
        vat_period=spec.get("vat_period", "monat"),
        dauerfrist=rng.random() < 0.5,
        vat_id=vat_id("DE", key) if regime not in ("klein",) else None,
        iban=iban("DE", key + ":own"),
        street=f"Werkstraße {rng.randrange(1, 60)}",
        postcode=f"{rng.randrange(10000, 99999)}",
        city=spec["city"],
        contact_name=spec["contact"],
        contact_email=f"{spec['contact'].split()[0].lower()}@{key}.example",
        assigned=[rng.choice(accountants)],
    )
    _simulate(client, vendors)
    return client


def replace_tax(v: V, regime: str) -> V:
    import dataclasses

    if v.family in (
        "payroll",
        "social_security",
        "wage_tax",
        "vat_payment",
        "private_withdrawal",
        "private_deposit",
        "transfer",
        "insurance",
        "bank_fees",
        "memberships",
        "vehicle_insurance",
    ):
        return v
    if v.role == "customer":
        return dataclasses.replace(v, tax="FREI" if regime == "befreit" else "NONE")
    return dataclasses.replace(v, tax="NONE") if regime in ("klein", "befreit") else v


# --- the timeline ------------------------------------------------------------------------------


def _amount(v: V, rng: random.Random) -> float:
    if isinstance(v.net, tuple):
        lo, hi = v.net
        return round(rng.uniform(lo, hi), 2)
    return float(v.net)


def _due(v: V, period: str) -> bool:
    if v.freq == "q":
        return int(period[5:7]) in (1, 4, 7, 10)
    if v.freq == "y":
        return int(period[5:7]) == v.yearly_month
    return True


def _doc_lines(v: V, net: float, rng: random.Random, doc_tax: str) -> list[DocLine]:
    cat = {
        "RC_EU19": "AE",
        "RC_DRITT19": "O",
        "RC_BAU19": "AE",
        "IGE19": "K",
        "EU_SVC": "AE",
        "IGL": "K",
        "RC_OUT": "AE",
        "FREI": "E",
        "NONE": "E",
    }.get(doc_tax, "S")
    if v.kleinunternehmer:
        cat = "E"
    rate = {"V19": 19, "U19": 19, "V7": 7, "U7": 7}.get(doc_tax, 0)
    if v.rates and cat == "S":
        out = []
        left = net
        for i, (r, share) in enumerate(v.rates):
            part = round(left if i == len(v.rates) - 1 else net * share, 2)
            left = round(left - part, 2)
            out.append(DocLine(v.items[min(i, len(v.items) - 1)], part, r, "S"))
        return out
    if v.family == "equipment":
        # One to three items; the unit price decides small / GWG / asset.
        n = rng.choice([1, 1, 2, 3])
        parts = sorted(rng.random() for _ in range(n - 1))
        cuts = [0.0, *parts, 1.0]
        lines = []
        acc = 0.0
        for i in range(n):
            part = round(net * (cuts[i + 1] - cuts[i]), 2) if i < n - 1 else round(net - acc, 2)
            acc = round(acc + part, 2)
            lines.append(DocLine(rng.choice(v.items), part, rate or 19 if cat == "S" else 0, cat))
        return lines
    if len(v.items) > 1 and net > 200 and rng.random() < 0.5:
        a = round(net * rng.uniform(0.3, 0.7), 2)
        return [DocLine(v.items[0], a, rate, cat), DocLine(rng.choice(v.items[1:]), round(net - a, 2), rate, cat)]
    return [DocLine(rng.choice(v.items), net, rate, cat)]


def gross_of(lines: list[DocLine]) -> float:
    return gross_cents(lines) / 100


def _simulate(client: Client, vendors: list[V]) -> None:
    """Fifteen months of business; OPOS invoices may be paid in the following month."""
    parties: dict[str, Party] = {}
    seq = 0
    pending: list[tuple[date, Event, V, Party]] = []  # OPOS invoices waiting for payment
    owner_iban = iban("DE", client.id + ":private")
    for period in ALL:
        start, end = _month_dates(period)
        rng = _rng(client.id, period)
        events: list[Event] = []
        dev = period in DEV
        for v in vendors:
            if not _due(v, period):
                continue
            prob = v.freq if isinstance(v.freq, float) else 1.0
            for k in range(v.per_month):
                if rng.random() > prob:
                    continue
                party = _party_for(client.id, v, k, rng)
                if v.key == "entnahme":
                    party.iban = owner_iban
                parties.setdefault(party.key, party)
                party = parties[party.key]
                seq += 1
                day = min(max(1, v.day + rng.randrange(-3, 4) + k * 3), end.day)
                on = date(start.year, start.month, day)
                net = _amount(v, rng)
                evs = _make_events(client, v, party, period, on, net, seq, rng, dev)
                for e in evs:
                    if e.kind == "invoice" and client.booking_method == "opos":
                        pending.append((on, e, v, party))
                events += [e for e in evs]
        # OPOS: pay invoices 7..40 days after issue (may fall in the next month).
        still: list[tuple[date, Event, V, Party]] = []
        for issued, inv_ev, v, party in pending:
            assert inv_ev.document is not None
            pay_on = issued + timedelta(days=_rng(inv_ev.id, "pay").randrange(7, 40))
            if pay_on > end:
                still.append((issued, inv_ev, v, party))
                continue
            if pay_on < start:
                pay_on = start
            events.append(_payment_for(client, v, party, inv_ev, pay_on, _rng(inv_ev.id, "skonto")))
        pending = still
        events.sort(key=lambda e: (e.on or start, e.id))
        client.months[period] = events
    client.parties = list(parties.values())


def _ref(v: V, period: str, doc_no: str, rng: random.Random, client: Client) -> str:
    y, m = period[:4], period[5:7]
    return v.reference.format(
        doc=doc_no,
        month=f"{m}/{y}",
        prev=f"{_prev(period)[5:7]}/{_prev(period)[:4]}",
        n=rng.randrange(1000, 9999),
        year=y,
        stnr=tax_no(client.id),
    )


def _make_events(
    client: Client, v: V, party: Party, period: str, on: date, net: float, seq: int, rng: random.Random, dev: bool
) -> list[Event]:
    eid = f"{client.id}-{seq:05d}"
    fmt = rng.choices(list(v.formats), weights=list(v.formats.values()))[0]
    regime = client.vat_regime
    doc_tax = v.tax
    customer = v.role == "customer"
    lines = (
        _doc_lines(
            v,
            net,
            rng,
            doc_tax if not (regime in ("klein", "befreit") and not customer and v.tax == "NONE") else _orig_tax(v),
        )
        if fmt != "none"
        else []
    )
    if regime in ("klein", "befreit") and not customer and fmt != "none":
        # The supplier still charges VAT; the client cannot deduct it.
        lines = _doc_lines(v, net, rng, "V19" if v.family not in ("goods",) or "7" not in str(v.tax) else "V7")
    gross = gross_of(lines) if lines else net
    doc_no = f"{rng.choice(['RE', 'R', 'INV', '2026-', 'RG'])}{rng.randrange(10000, 99999)}"
    if customer:
        doc_no = f"{client.mandant_nr}-{seq:05d}"
    doc = None
    if fmt != "none":
        doc = DocSpec(
            format=fmt,
            number=doc_no,
            issue_date=on - timedelta(days=rng.randrange(0, 6))
            if v.method == "karte"
            else on - timedelta(days=rng.randrange(3, 14)),
            delivery_date=on - timedelta(days=rng.randrange(0, 10)),
            lines=lines,
            layout=rng.randrange(3),
            direction="out" if customer else "in",
            notes=[NOTE_RC]
            if doc_tax in ("RC_BAU19", "RC_OUT") or (doc_tax in ("RC_EU19", "EU_SVC"))
            else (["Kleinunternehmer gemäß § 19 UStG"] if v.kleinunternehmer else []),
            payment_terms="2 % Skonto bei Zahlung innerhalb von 10 Tagen, 30 Tage netto"
            if v.skonto
            else "Zahlbar innerhalb von 14 Tagen ohne Abzug",
        )
        if doc.issue_date and doc.issue_date < _month_dates(period)[0] and client.booking_method == "opos":
            doc.issue_date = _month_dates(period)[0]
        if v.family == "meals" and rng.random() < v.meals_details:
            doc.notes.append(f"Anlass: Projektbesprechung; Teilnehmer: {client.contact_name}, {rng.choice(PEOPLE)}")
    truth_tax = v.tax if regime not in ("klein", "befreit") or customer else "NONE"
    family = v.family
    truth = Truth(
        family=family, tax=truth_tax if not (lines and len({(ln.rate, ln.category) for ln in lines}) > 1) else None
    )
    says: dict[str, Any] = {}
    answers = rng.random() > 0.08

    # Defects (development months and, more rarely, history - which the firm then resolved).
    if (
        doc
        and not customer
        and v.method != "karte"
        and v.family not in ("rent",)
        and rng.random() < (0.07 if dev else 0.0)
    ):
        doc.missing = [rng.choice(["delivery_date", "seller_tax_id", "buyer_name"])]
        if gross > 250 and truth_tax in ("V19", "V7"):
            if rng.random() < 0.6:
                says["invoice_incomplete"] = {"choice": "upload"}
            else:
                says["invoice_incomplete"] = {"choice": "not_available"}
                truth = Truth(family=family, tax="NONE")
        else:
            doc.missing = []
    if doc and not customer and v.family not in ("rent",) and rng.random() < (0.10 if dev else 0.0) and not doc.missing:
        r = rng.random()
        if r < 0.65:
            doc.arrives = "on_request"
            says["missing_receipt"] = {"choice": "upload"}
        else:
            doc.arrives = "never"
            says["missing_receipt"] = {"choice": "no_receipt", "purpose": "Beleg verloren"}
            truth = Truth(family=family, tax="NONE")
    if v.family == "meals":
        says["meals_details"] = {
            "choice": "details",
            "occasion": "Kundengespräch",
            "participants": f"{client.contact_name}, {rng.choice(PEOPLE)}",
        }
        if rng.random() < 0.12:
            says["meals_details"] = {"choice": "private"}
            truth = Truth(family="private_withdrawal", tax="NONE")
    if v.private:
        says["private_or_business"] = {"choice": "private"}
        says["missing_receipt"] = {"choice": "private"}
    if v.role == "customer" and client.booking_method == "direkt" and doc and rng.random() < (0.08 if dev else 0.0):
        doc.arrives = "on_request"  # the client forgot to send the invoice it issued
        says["unknown_credit"] = {"choice": "customer", "invoice_no": doc.number}

    sign = 1 if customer else -1
    if (
        client.booking_method == "opos"
        and doc is not None
        and v.method != "karte"
        and v.role in ("supplier", "customer")
        and v.family not in ("rent", "vehicle_leasing", "telecom", "utilities", "advice", "software", "postage")
    ):
        inv = Event(
            id=eid + "-R",
            kind="invoice",
            party=party.key,
            amount=0.0,
            on=doc.issue_date,
            document=doc,
            truth=truth,
            says=says,
            answers=answers,
        )
        return [inv]
    method = v.method if not customer else "gutschrift"
    ev = Event(
        id=eid,
        kind="payment",
        party=party.key,
        amount=round(sign * gross, 2),
        on=on,
        reference=_ref(v, period, doc_no, rng, client) if not v.private else f"Kartenzahlung {party.name}",
        method=method,
        document=doc,
        truth=truth,
        says=says,
        answers=answers,
    )
    if v.method == "karte" and not v.private:
        ev.reference = f"Kartenzahlung {party.name} {on.strftime('%d.%m.')}"
    return [ev]


def _orig_tax(v: V) -> str:
    return v.tax


def _payment_for(client: Client, v: V, party: Party, inv: Event, on: date, rng: random.Random) -> Event:
    assert inv.document is not None
    gross = gross_of(inv.document.lines)
    customer = inv.document.direction == "out"
    skonto = (
        (not customer) and v.skonto and rng.random() < v.skonto and (on - (inv.document.issue_date or on)).days <= 12
    )
    paid = round(gross * 0.98, 2) if skonto else gross
    ref = f"RE {inv.document.number}" + (" abzgl. 2% Skonto" if skonto else "")
    if customer:
        ref = f"Rechnung {inv.document.number}"
    return Event(
        id=inv.id.replace("-R", "-Z"),
        kind="payment",
        party=party.key,
        amount=round(paid if customer else -paid, 2),
        on=on,
        reference=ref,
        method="gutschrift" if customer else "ueberweisung",
        settles=[inv.id],
        truth=Truth(family="clearing", tax="NONE", note="skonto" if skonto else ""),
    )
