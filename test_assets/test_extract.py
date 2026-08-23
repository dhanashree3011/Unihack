import sys
sys.path.insert(0, '.')
from src import kb_index as kbi, extract as ex, config

spec_text = '''FRIGIDAIRE Professional Series Dishwasher PDSH4816AF
Specification Sheet

Electrical Specifications
Voltage Rating: 120 V
Amperage Rating: 15 A
Frequency: 60 Hz

Performance
Number of Wash Cycles: 5
Sound Level: 47 dBA
Mounting Type: Leg

Construction
Material: Stainless Steel
Series: Professional Series
Depth With Door Open: 50-1/4 in
Size: 24 in W x 24-1/4 in D

Warranty
Warranty: 1 Year Manufacturer, 1 Year Labor and Parts
'''
docs = [{'url': 'https://www.frigidaire.com/support/spec.pdf', 'text': spec_text}]
kb = kbi.build_part_kb('PDSH4816AF', docs)

targets = ['Voltage Rating', 'Amperage Rating', 'Sound Level', 'Material', 'Series',
           'Mounting Type', 'Number of Wash Cycles', 'Depth']
for label in targets:
    spec = config.ATTRIBUTE_QUERIES[label]
    r = ex.extract_attribute(kb, label, spec)
    if r:
        print(f"{label:25s} -> value={r.value!r:20s} unit={r.unit!r:6s} conf={r.confidence}  src={r.source_url}")
    else:
        print(f"{label:25s} -> NOT FOUND")

print()
print("dimension parse:", ex.parse_dimension_string('24 in W x 24-1/4 in D'))

ground_truth = {
    'Voltage Rating': ('120', 'V'), 'Amperage Rating': ('15', 'A'), 'Sound Level': ('47', 'dBA'),
    'Material': ('Stainless Steel', ''), 'Mounting Type': ('Leg', ''), 'Number of Wash Cycles': ('5', ''),
}
print()
print("=== accuracy check vs real ground-truth row ===")
hits = 0
for label, (gt_val, gt_unit) in ground_truth.items():
    spec = config.ATTRIBUTE_QUERIES[label]
    r = ex.extract_attribute(kb, label, spec)
    got_val = r.value if r else None
    got_unit = r.unit if r else None
    ok = bool(r) and got_val.strip().lower() == gt_val.lower() and (got_unit == gt_unit or not gt_unit)
    hits += int(ok)
    status = "OK" if ok else "MISS"
    print(f"{label:25s} GT=({gt_val!r},{gt_unit!r})  GOT=({got_val!r},{got_unit!r})  {status}")
print(f"\n{hits}/{len(ground_truth)} exact matches")
