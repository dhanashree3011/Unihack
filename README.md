# TraceForge Product Intelligence

TraceForge finds manufacturer pages and technical documents for component part
numbers, extracts structured product facts, and exports them in the exact
spreadsheet format your catalog requires. It combines a FastAPI backend with a
React workbench, web search, PDF/OCR processing, classic information retrieval,
rule-based extraction, and a self-learning review cache.

**No LLMs. No opaque guesses. Every extracted value can carry confidence,
source evidence, and a human review path.**

## Why It Is Useful

- **Catalog-ready output**: load CSV/XLSX input and export CSV/XLSX using a
  supplied or bundled header template.
- **Evidence-first enrichment**: retain source URLs, supporting snippets, and
  confidence scores alongside extracted values.
- **Live or offline runs**: use the web when available, or run against cached
  documents for repeatable development and testing.
- **Human review that compounds**: corrections are stored in SQLite and can
  improve related rows in later batches.
- **Built for technical documents**: fetch HTML and PDFs, extract text with
  PyMuPDF, and use Tesseract when a PDF needs OCR.
- **Fast batch processing**: concurrent workers handle I/O-heavy web requests
  while server-sent events stream progress to the frontend.

## Pipeline

```text
CSV/XLSX
   |
   v
Search manufacturer sources --> Fetch HTML/PDF --> Text extraction + OCR
                                                        |
                                                        v
                 BM25+ knowledge base --> Rules + normalization --> Classification
                                                        |
                                                        v
                         Confidence + evidence --> Review --> CSV/XLSX export
                                                        |
                                                        v
                                             SQLite learning cache
```

The extraction path is deliberately inspectable: search results are scored by
source trust, documents are chunked into a small per-part knowledge base, and
fields are populated by anchored patterns and deterministic templates. TF-IDF
plus Logistic Regression provides the optional taxonomy classifier; no
generative model is part of the pipeline.

## Product Workflow

The React workbench is designed around the real catalog workflow:

- upload a component list and optional output template;
- configure live/offline mode, concurrency, and enrichment depth;
- watch row-level progress as the batch runs;
- filter products by status, category, confidence, or review state;
- edit flagged values with their evidence visible;
- download enriched data and the review log.

## Quick Start

### 1. Install Python dependencies

```bash
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS/Linux
source .venv/bin/activate
```

Then install the project packages:

```bash
pip install -r requirements.txt
```

### 2. Install the OCR binary (optional)

`pytesseract` is included in the Python dependencies, but Tesseract itself is
installed separately. OCR is only needed for scanned or image-only PDFs.

- **Windows**: install the [UB Mannheim Tesseract build](https://github.com/UB-Mannheim/tesseract/wiki)
- **Ubuntu/Debian**: `sudo apt install tesseract-ocr`
- **macOS**: `brew install tesseract`

If Tesseract is not on `PATH`, set `TESSERACT_CMD` to its executable path.

### 3. Start the backend

From the repository root:

```bash
uvicorn main:app --reload --port 8000
```

The API is available at `http://localhost:8000`. Interactive API docs are at
`http://localhost:8000/docs`.

### 4. Start the frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` requests to the backend on
port `8000`.

## Free Deployment

The simplest low-cost setup is:

- **Render** for the FastAPI backend
- **Vercel** or **Cloudflare Pages** for the Vite frontend

Both offer free plans suitable for demos and small personal projects. Free
backend instances may sleep when idle, and local files are not durable, so the
SQLite learning cache and downloaded documents should be treated as disposable
unless you attach persistent storage or move them to a hosted database/object
store.

### Deploy the backend to Render

1. Push this repository to GitHub.
2. In Render, choose **New > Blueprint** and select the repository.
3. Render detects [`render.yaml`](render.yaml) and creates the `traceforge-api`
  web service.
4. After deployment, copy the service URL, for example:
  `https://traceforge-api.onrender.com`.
5. Set the Render environment variable `FRONTEND_ORIGINS` to the URL where you
  will host the frontend.

The backend start command is:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

### Deploy the frontend to Vercel

1. Import the same GitHub repository into Vercel.
2. Set the project root to `frontend`.
3. Use `npm run build` as the build command and `dist` as the output directory.
4. Add `VITE_API_URL` with the Render service root URL, without `/api`, for
  example: `https://traceforge-api.onrender.com`.
5. Deploy, then add the final Vercel URL to Render’s `FRONTEND_ORIGINS`.

For Cloudflare Pages, use `frontend` as the root directory, `npm run build` as
the build command, `dist` as the output directory, and define the same
`VITE_API_URL` environment variable.

The free Render service can take several seconds to wake after inactivity. Run
the frontend and backend locally first, then test the deployed API at
`/docs` before troubleshooting the browser app.

## API Surface

| Area | Endpoints |
| --- | --- |
| Health | `GET /health` |
| Uploads | `POST /api/upload`, `POST /api/upload_template` |
| Jobs | `POST /api/jobs`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/stream` |
| Results | `GET /api/jobs/{id}/results`, `PATCH /api/jobs/{id}/results/{result_id}` |
| Exports | `GET /api/jobs/{id}/export?fmt=csv\|xlsx\|review_log` |
| Evaluation | `GET /api/jobs/{id}/evaluate` |
| Cache | `GET /api/cache/stats`, `DELETE /api/cache` |

## Repository Layout

```text
main.py                         FastAPI application and API routes
requirements.txt                Python runtime dependencies
frontend/                       React + Vite review workbench
  src/api.js                    API client and SSE stream handling
  src/App.jsx                   Application state and workflow
  src/components/               Product, field, and overview components
src/                            Framework-free pipeline modules
  search_engine.py              Manufacturer-focused web search
  fetch.py                      HTML/PDF retrieval and disk cache
  ocr.py                        PDF rasterization and Tesseract fallback
  kb_index.py                   Per-part BM25+ retrieval
  extract.py                    Anchored rule-based extraction
  normalize.py                  Manufacturer, brand, UOM normalization
  classify.py                   TF-IDF taxonomy classification
  pipeline.py                   Batch orchestration and confidence scoring
  output_writer.py              Template-driven CSV/XLSX export
templates/                      Bundled expected-output header template
data/                           Optional catalog reference files
cache/                          Runtime SQLite and fetched-document cache
test_assets/                    Extraction and end-to-end checks
smoke_test.py                   Fast pipeline smoke test
```

## Optional Reference Data

The pipeline works without proprietary reference files, using sensible
fallbacks. Add the following files under `data/` to improve catalog-specific
accuracy:

| File | Purpose |
| --- | --- |
| `Unilog_Master_UOM_Standards_Abbreviations_and_Terms.xlsx` | Approved UOM vocabulary |
| `UniCat_Manufacturer_and_Brand_List.xlsx` | Authoritative manufacturer and brand resolution |
| Any CSV/XLSX with descriptions and `Classpath` | Taxonomy training data |

Category-specific attribute templates can also be added to extend the seeded
Dishwashers example to the rest of a catalog.

## Testing

Run the lightweight smoke test from the repository root:

```bash
python smoke_test.py
```

Run the focused extraction and pipeline checks:

```bash
python test_assets/test_extract.py
python test_assets/test_pipeline_e2e.py
```

Build the frontend:

```bash
cd frontend
npm run build
```

## Design Decisions

| Problem | Approach |
| --- | --- |
| Web discovery | DuckDuckGo queries with manufacturer and PDF preferences |
| Document parsing | Trafilatura for HTML, PyMuPDF for PDFs, Tesseract fallback |
| Retrieval | BM25+ for small per-part document collections |
| Extraction | Regex and line-anchored `Label: Value` rules |
| Normalization | Lookup tables plus RapidFuzz matching |
| Classification | TF-IDF features with Logistic Regression |
| Descriptions | Deterministic string templates |
| Learning | SQLite cache keyed by reusable product-family signals |

## Current Scope and Limitations

The strongest coverage is for manufacturer, brand, taxonomy, descriptions,
dimensions, certifications, warranty, images, manuals, and fixed-slot
attributes. Internal identifiers such as `PART_NUMBER`, pricing, EAN, and
UNSPSC are intentionally left blank when there is no trustworthy external
signal.

Accuracy improves substantially with the official manufacturer, UOM, taxonomy,
and category-template files. Without them, manufacturer-of-record resolution
and category-specific attribute ordering remain inherently limited. Live search
also depends on network access and the availability of manufacturer websites.

## License

No license file is currently included. Add the license that matches your
intended distribution before publishing this repository publicly.