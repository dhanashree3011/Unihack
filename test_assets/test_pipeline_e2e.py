import sys
sys.path.insert(0, '.')
from src import pipeline, cache_store, fetch as fetch_mod

cache_store.init_db()


frigidaire_spec_text = """FRIGIDAIRE Professional Series Dishwasher PDSH4816AF
Specification Sheet

Electrical Specifications
Voltage Rating: 120 V
Amperage Rating: 15 A

Performance
Number of Wash Cycles: 5
Sound Level: 47 dBA
Mounting Type: Leg

Construction
Material: Stainless Steel
Series: Professional Series
Depth With Door Open: 50-1/4 in
Size: 24 in W x 24-1/4 in D

Certifications
This unit is ASSE 1006 certified, CEE Tier 2 Qualified, cUL Listed,
ENERGY STAR Certified, NSF Certified, and UL Listed.

Warranty: 1 Year Manufacturer, 1 Year Labor and Parts
"""

frigidaire_page_text = """
The PDSH4816AF Professional Series dishwasher With CleanBoost delivers
powerful cleaning performance for the modern kitchen.
"""

frigidaire_html = b"""
<html><head><meta property="og:site_name" content="Frigidaire"></head>
<body><h2>Overview</h2>
<p>The PDSH4816AF Professional Series dishwasher With CleanBoost delivers
powerful cleaning performance for the modern kitchen.</p>
</body></html>
"""

whirlpool_spec_text = """Whirlpool Eco Series Dishwasher WDTS7024RZ
Specification Sheet

Electrical Specifications
Voltage Rating: 120 V
Amperage Rating: 10 A

Performance
Sound Level: 41 dBA
Mounting Type: Built-in

Construction
Material: Stainless Steel
Color: Stainless Steel
Series: Eco Series
Depth With Door Open: 50-3/16 in
Minimum Height: 33-7/16 in
Size: 33-7/16 in H x 23-7/8 in W x 22-5/8 in D
"""

whirlpool_html = b"""
<html><head><meta property="og:site_name" content="Whirlpool"></head>
<body>
<p>Load more and run less with our quietest and largest capacity dishwasher.
With Washing 3rd Rack, Water Repellent Silverware Basket for better cleaning.</p>
<h2>Features</h2>
<ul>
<li>3rd rack with extra wash action</li>
<li>Adjustable 2nd Rack</li>
<li>41 dBA</li>
<li>Moisture Repellent Silverware Basket</li>
<li>Sensor cycle</li>
<li>Sani Rinse Option</li>
<li>Leak Detection System</li>
<li>Folding Tines</li>
<li>Normal cycle</li>
<li>Triple Wash Spray</li>
<li>Quick Wash Cycle</li>
</ul>
</body></html>
"""

test_cases = [
    {
        "row": {
            "Mfg_Part_Num": "PDSH4816AF", "Part_Desc": "PDSH4816AF Dishwasher SS - Display Only",
            "E1_Brand": "-- Unbranded --", "Unilog_Brand": "-- No Unilog Brand --",
            "DIB_Brand": "-- No DIB Brand --", "Part_Manuf": "Appliance Dealers Cooperative (APPDE)",
        },
        "documents": [
            {"url": "https://www.frigidaire.com/support/spec.pdf", "text": frigidaire_spec_text, "raw_html": None},
            {"url": "https://www.frigidaire.com/en/p/PDSH4816AF", "text": frigidaire_page_text, "raw_html": frigidaire_html},
        ],
        "expect": {
            "MANUFACTURER_NAME": None, "BRAND_NAME": None,
            "INVOICE_DESC": "DISHWASHER LEG 5 SST 120V 15A 50-1/4IN",
            "SHORT_DESC": "FRIGIDAIRE Professional Series PDSH4816AF Dishwasher With CleanBoost, Leg Mounting, 5-Wash Cycle, Stainless Steel",
        },
    },
    {
        "row": {
            "Mfg_Part_Num": "WDTS7024RZ", "Part_Desc": "WDTS7024RZ Dishwasher SS - Display Only",
            "E1_Brand": "-- Unbranded --", "Unilog_Brand": "-- No Unilog Brand --",
            "DIB_Brand": "-- No DIB Brand --", "Part_Manuf": "Appliance Dealers Cooperative (APPDE)",
        },
        "documents": [
            {"url": "https://www.whirlpool.com/content/dam/spec.pdf", "text": whirlpool_spec_text, "raw_html": None},
            {"url": "https://www.whirlpool.com/wdts7024rz", "text": "", "raw_html": whirlpool_html},
        ],
        "expect": {},
    },
]

for case in test_cases:
    for doc in case["documents"]:
        doc["meta"] = fetch_mod.extract_page_meta(doc["raw_html"]) if doc.get("raw_html") else {}

    print("=" * 100)
    print("PART:", case["row"]["Mfg_Part_Num"])
    r = pipeline.process_row(case["row"], live=False, injected_documents=case["documents"])
    for name in ["MFR URL", "MANUFACTURER_NAME", "BRAND_NAME", "Product Name", "Standard/Approvals",
                 "With", "Warranty", "INVOICE_DESC", "MOBILE_DESC", "SHORT_DESC", "LONG_DESC1", "RETAIL_DESC"]:
        fr = r.fields.get(name)
        if fr and fr.value:
            print(f"  {name:20s} conf={fr.confidence:.2f}  {fr.value}")
    print("  -- attributes --")
    for i in range(1, 16):
        lab = r.fields.get(f"ATTRIBUTE_LABEL {i}")
        val = r.fields.get(f"ATTRIBUTE_VALUE {i}")
        uom = r.fields.get(f"ATTRIBUTE_UOM {i}")
        if lab and lab.value:
            print(f"  [{i}] {lab.value:25s} = {val.value if val else '':25s} {uom.value if uom else ''}")
    print("  -- features --")
    for i in range(1, 12):
        f = r.fields.get(f"ITEM_FEATURES_{i}")
        if f and f.value:
            print(f"  [{i}] {f.value}")
    print("  review flags:", r.review_flags)
