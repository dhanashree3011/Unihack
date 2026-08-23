"""
config.py
---------
Single source of truth for all the "knobs" the pipeline needs that are not
row-specific: which units are valid, which domains to trust, which
attributes to go looking for, and where things live on disk.

Design intent: none of this is hardcoded logic in the pipeline itself -
it's data the pipeline reads. If TraceForge's official reference files
(UOM standards, Manufacturer/Brand list, LOV vocabulary) get dropped into
data/, loader functions below prefer them automatically and these
defaults become a fallback rather than the only source. This is what
keeps the system "dynamic" rather than tuned to the 1000-row sample.
"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
DOC_CACHE_DIR = os.path.join(CACHE_DIR, "documents")
DB_PATH = os.path.join(CACHE_DIR, "traceforge_cache.sqlite3")

for _d in (DATA_DIR, CACHE_DIR, DOC_CACHE_DIR):
    os.makedirs(_d, exist_ok=True)

OPTIONAL_REFERENCE_FILES = {
    "uom_standards": "Unilog_Master_UOM_Standards_Abbreviations_and_Terms.xlsx",
    "manufacturer_brand_list": "UniCat_Manufacturer_and_Brand_List.xlsx",
    "lov_vocab": "Unicat_Lov_v1_0_Updated_With_Remarks.xlsx",
    "content_guidelines": "UNILOG_INTERNAL_CONTENT_GUIDELINES.docx",
    "decimal_fraction": "Decimal_Fraction.xlsx",
    "ground_truth_200": "Unilog-Sample_200_Items-Input-vs-Output.xlsx",
}

PLACEHOLDER_VALUES = {
    "-- unbranded --",
    "-- no unilog brand --",
    "-- no dib brand --",
    "-- none --",
    "n/a",
    "na",
    "none",
    "",
}

BLOCKED_DOMAINS = {
    "github.com", "github.io", "githubusercontent.com", "gitlab.com", "bitbucket.org",
    "sourceforge.net", "npmjs.com", "pypi.org", "stackoverflow.com", "stackexchange.com",
    "scribd.com", "slideshare.net", "docplayer.net", "issuu.com", "coursehero.com",
    "chegg.com", "studocu.com", "academia.edu", "researchgate.net",
    "manualslib.com", "manuals.plus", "manymanuals.com", "manualpdf.in", "manualzz.com",
    "manualowl.com", "guide-manual.com", "manualsbrain.com", "user-manual.info",
    "safe-manuals.com", "usermanual.wiki", "manualmachine.com", "central-manuals.com",
    "amazon.com", "amazon.in", "amazon.co.uk", "amazon.de", "amazon.ca",
    "ebay.com", "ebay.co.uk", "walmart.com", "alibaba.com", "aliexpress.com",
    "homedepot.com", "lowes.com", "grainger.com", "mcmaster.com", "menards.com",
    "zoro.com", "wayfair.com", "target.com", "etsy.com", "sears.com", "bestbuy.com",
    "costco.com", "newegg.com", "dhgate.com", "wish.com",
    "houzz.com", "overstock.com", "webstaurantstore.com", "globalindustrial.com",
    "pinterest.com", "facebook.com", "instagram.com", "reddit.com", "youtube.com",
    "twitter.com", "x.com", "linkedin.com", "tiktok.com", "medium.com", "quora.com",
    "wikipedia.org", "wikihow.com", "archive.org",
    "apify.com", "cloudflare.com", "recaptcha.net", "stereophile.com", "soundguys.com",
}

BLOCKED_BRAND_NAMES = {
    "github", "scribd", "manualslib", "slideshare", "almart", "walmart",
    "amazon", "apify", "intel", "manualsplus", "manymanuals", "pdf",
    "manual", "document", "item", "product", "privacy policy", "copyright",
    "javascript", "unknown", "none", "n/a", "na", "null", "undefined",
    "true", "false", "default", "brand", "manufacturer"
}

ITEM_TYPE_HINTS = {
    "belt", "disc", "disk", "sheet", "roll", "wheel", "pad", "strip",
    "sleeve", "drum", "cone", "screen", "brush", "stone",
    "blade", "bit", "drill", "saw", "wrench", "hammer", "screwdriver",
    "chisel", "file", "knife", "clamp", "vise", "grinder", "sander",
    "dishwasher", "refrigerator", "washer", "dryer", "range", "oven",
    "microwave", "freezer", "cooktop", "hood",
    "faucet", "valve", "pump", "fan", "light", "fixture", "motor",
    "switch", "outlet", "filter", "hose", "cable", "fitting",
    "connector", "bracket", "gasket", "seal", "bearing", "nozzle",
    "adapter", "coupler",
    "bolt", "screw", "nut", "anchor", "hinge", "handle", "knob",
    "lock", "latch",
}

TRUSTED_DOC_HINTS = (
    "manual", "spec", "datasheet", "data-sheet", "product-support",
    "specification", "install", "owners", "user-guide", "support",
    "documentation", "downloads",
)

DOCUMENT_EXTENSIONS = (".pdf",)

ATTRIBUTE_QUERIES = {
    "Voltage Rating":        {"synonyms": ["voltage", "volts", "rated voltage"], "units": ["V", "VAC", "VDC"]},
    "Amperage Rating":       {"synonyms": ["amperage", "amps", "current rating"], "units": ["A", "mA"]},
    "Wattage":               {"synonyms": ["wattage", "power rating", "watts"], "units": ["W", "kW"]},
    "Frequency":             {"synonyms": ["frequency", "hertz"], "units": ["Hz"]},
    "Sound Level":           {"synonyms": ["sound level", "noise level", "decibel"], "units": ["dBA", "dB"]},
    "Weight":                {"synonyms": ["weight", "net weight", "shipping weight"], "units": ["lb", "oz", "kg", "g"]},
    "Length":                {"synonyms": ["length", "overall length"], "units": ["in", "ft", "mm", "cm"]},
    "Width":                 {"synonyms": ["width", "overall width"], "units": ["in", "ft", "mm", "cm"]},
    "Height":                {"synonyms": ["height", "overall height"], "units": ["in", "ft", "mm", "cm"]},
    "Depth":                 {"synonyms": ["depth", "overall depth"], "units": ["in", "ft", "mm", "cm"]},
    "Diameter":              {"synonyms": ["diameter", "dia."], "units": ["in", "mm"]},
    "Material":              {"synonyms": ["material", "construction", "body material"], "units": []},
    "Color":                 {"synonyms": ["color", "colour", "finish"], "units": []},
    "Capacity":              {"synonyms": ["capacity", "volume capacity"], "units": ["gal", "L", "qt", "cu ft"]},
    "Pressure Rating":       {"synonyms": ["pressure rating", "psi rating", "max pressure"], "units": ["psi", "bar", "kPa"]},
    "Temperature Rating":    {"synonyms": ["temperature rating", "operating temperature"], "units": ["F", "C"]},
    "Thread Size":           {"synonyms": ["thread size", "npt", "thread"], "units": ["in", "NPT"]},
    "Connection Type":       {"synonyms": ["connection type", "fitting type", "port type"], "units": []},
    "Mounting Type":         {"synonyms": ["mounting type", "mounting style", "mount"], "units": []},
    "Series":                {"synonyms": ["series", "product series", "collection"], "units": []},
    "Model":                 {"synonyms": ["model number", "model"], "units": []},
    "Number of Wash Cycles": {"synonyms": ["wash cycles", "number of cycles"], "units": []},
    "Plug Type":             {"synonyms": ["plug type", "plug"], "units": []},
}

UNIT_TOKENS = sorted(
    ["dBA", "dB", "VAC", "VDC", "cu ft", "sq ft", "fl oz", "NPT",
     "V", "A", "W", "kW", "Hz", "in", "ft", "mm", "cm", "m",
     "lb", "lbs", "oz", "kg", "g", "gal", "L", "mL", "qt",
     "psi", "bar", "kPa", "F", "C"],
    key=len, reverse=True,
)

DEFAULT_UOM_MAP = {
    "inch": "in", "inches": "in", "in.": "in", "\"": "in", "IN": "in",
    "foot": "ft", "feet": "ft", "ft.": "ft",
    "millimeter": "mm", "millimeters": "mm", "mm.": "mm",
    "centimeter": "cm", "centimeters": "cm",
    "meter": "m", "meters": "m", "metre": "m",
    "pound": "lb", "pounds": "lb", "lbs.": "lb", "lbs": "lb",
    "ounce": "oz", "ounces": "oz",
    "kilogram": "kg", "kilograms": "kg", "kgs": "kg",
    "gram": "g", "grams": "g",
    "volt": "V", "volts": "V", "voltage": "V",
    "amp": "A", "amps": "A", "ampere": "A", "amperes": "A",
    "watt": "W", "watts": "W",
    "kilowatt": "kW", "kilowatts": "kW",
    "hertz": "Hz",
    "gallon": "gal", "gallons": "gal",
    "liter": "L", "liters": "L", "litre": "L",
    "milliliter": "mL", "milliliters": "mL",
    "quart": "qt", "quarts": "qt",
    "fluid ounce": "fl oz", "fluid ounces": "fl oz",
    "pounds per square inch": "psi",
    "kilopascal": "kPa", "kilopascals": "kPa",
    "decibel": "dB", "decibels": "dB",
    "fahrenheit": "F", "celsius": "C",
}

def _build_fraction_table():
    from fractions import Fraction
    table = {}
    for n in range(1, 64):
        f = Fraction(n, 64)
        table[round(n / 64, 6)] = f"{f.numerator}/{f.denominator}"
    return table

FRACTION_TABLE = _build_fraction_table()

UNIT_TOKENS_LOWER = {t.lower(): t for t in UNIT_TOKENS}

MAX_REF_URLS = 5
MAX_ATTRIBUTES = 50

ENABLE_DYNAMIC_ENRICHMENT = True
ENRICHMENT_CONFIDENCE_THRESHOLD = 0.45
ENRICHMENT_MIN_MISSING = 3
ENRICHMENT_MAX_LABELS = 5
ENRICHMENT_MAX_NEW_URLS = 4

MAX_DOCUMENT_ERRORS_KEPT = 10
