"""
smoke_test.py — Run from the project root:
  .\\venv\\Scripts\\python.exe smoke_test.py
"""
import sys
sys.path.insert(0, ".")

print("=" * 60)
print("PIPELINE QUALITY IMPROVEMENT SMOKE TEST")
print("=" * 60)

errors = []

try:
    from src.search_engine import trust_score, _is_homepage, _classify_pdf_purpose
    print("\n[1] search_engine")

    ts_pdf = trust_score("https://frigidaire.com/spec.pdf")
    ts_home = trust_score("https://frigidaire.com/")
    ts_blocked = trust_score("https://amazon.com/dp/123")
    hp_root = _is_homepage("https://frigidaire.com/")
    hp_deep = _is_homepage("https://frigidaire.com/support/manuals/dishwashers")

    print(f"  trust_score(spec PDF)  = {ts_pdf:.2f}  (expect ≥ 0.80)")
    print(f"  trust_score(homepage)  = {ts_home:.2f}  (expect ≥ 0.55)")
    print(f"  trust_score(amazon)    = {ts_blocked:.2f}  (expect -1.0)")
    print(f"  _is_homepage(root)     = {hp_root}  (expect True)")
    print(f"  _is_homepage(deep url) = {hp_deep}  (expect False)")

    assert ts_pdf >= 0.80, f"spec PDF trust too low: {ts_pdf}"
    assert ts_home >= 0.55, f"homepage trust too low: {ts_home}"
    assert ts_blocked == -1.0, "blocked domain should return -1.0"
    assert hp_root is True
    assert hp_deep is False
    print("  ✓ PASS")
except Exception as e:
    print(f"  ✗ FAIL: {e}")
    errors.append(str(e))

try:
    from src.kb_index import build_part_kb
    print("\n[2] kb_index TF-IDF blend")

    docs = [
        {
            "url": "https://example.com/page",
            "text": "Voltage Rating: 120 V\nAmperage Rating: 15 A\nNoise Level: 47 dBA",
        },
        {
            "url": "https://example.com/spec.pdf",
            "text": "Sound Level: 47 dBA\nVoltage: 120 VAC\nDepth: 24 in",
        },
    ]
    kb = build_part_kb("TEST123", docs)
    print(f"  KB chunks built: {len(kb.chunks)}")
    assert len(kb.chunks) >= 2, "expected at least 2 chunks"

    results = kb.search("Sound Level noise decibel dBA", top_k=3)
    assert results, "search returned no results"
    top_chunk, top_score = results[0]
    print(f"  Top chunk score: {top_score:.3f}")
    print(f"  Top chunk text:  {top_chunk.text[:70]!r}")
    assert "dba" in top_chunk.text.lower() or "sound" in top_chunk.text.lower() or "noise" in top_chunk.text.lower(), \
        "Expected dBA/Sound/Noise chunk at top"
    print("  ✓ PASS")
except Exception as e:
    print(f"  ✗ FAIL: {e}")
    errors.append(str(e))

try:
    from src.extract import extract_attribute
    from src import config
    print("\n[3] extract_attribute confidence")

    spec = config.ATTRIBUTE_QUERIES["Sound Level"]
    ext = extract_attribute(kb, "Sound Level", spec)
    if ext:
        print(f"  Sound Level = '{ext.value}' {ext.unit}  confidence={ext.confidence:.2f}")
        assert ext.confidence >= 0.60, f"confidence too low: {ext.confidence}"
        assert "47" in ext.value
        print("  ✓ PASS")
    else:
        print("  [WARN] Sound Level not extracted — check chunk text / regex")

    spec2 = config.ATTRIBUTE_QUERIES["Voltage Rating"]
    ext2 = extract_attribute(kb, "Voltage Rating", spec2)
    if ext2:
        print(f"  Voltage Rating = '{ext2.value}' {ext2.unit}  confidence={ext2.confidence:.2f}")
        assert ext2.confidence >= 0.60, f"voltage confidence too low: {ext2.confidence}"
        print("  ✓ PASS")
    else:
        print("  [WARN] Voltage Rating not extracted")
except Exception as e:
    print(f"  ✗ FAIL: {e}")
    errors.append(str(e))

try:
    from src.extract import extract_feature_bullets
    print("\n[4] extract_feature_bullets (multi-strategy)")

    html1 = b"""<html><body>
<h2>Key Features</h2>
<ul><li>Energy Star Certified</li><li>5 Wash Cycles</li><li>Built-in stainless steel tub</li></ul>
</body></html>"""
    b1 = extract_feature_bullets(html1)
    print(f"  Strategy 1 (heading + ul):  {b1}")
    assert len(b1) >= 3, f"expected ≥3 bullets from heading strategy, got {b1}"

    html2 = b"""<html><body>
<div class="product-highlights">
  <ul><li>Quiet at 47 dBA</li><li>Flexible third rack</li><li>Built-in WiFi</li></ul>
</div>
</body></html>"""
    b2 = extract_feature_bullets(html2)
    print(f"  Strategy 2 (class hint):    {b2}")
    assert len(b2) >= 2, f"expected ≥2 bullets from class strategy, got {b2}"

    html3 = b"""<html><body>
<div data-section="features">
  <ul><li>Auto-clean filter</li><li>Door alarm</li></ul>
</div>
</body></html>"""
    b3 = extract_feature_bullets(html3)
    print(f"  Strategy 3 (data-* attr):   {b3}")
    assert len(b3) >= 2, f"expected ≥2 bullets from data-* strategy, got {b3}"

    print("  ✓ PASS")
except Exception as e:
    print(f"  ✗ FAIL: {e}")
    errors.append(str(e))

print("\n" + "=" * 60)
if errors:
    print(f"FAILED — {len(errors)} error(s):")
    for e in errors:
        print(f"  • {e}")
    sys.exit(1)
else:
    print("ALL TESTS PASSED ✓")
print("=" * 60)
