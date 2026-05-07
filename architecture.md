# Architecture — Compliance Validator Agent

## 1. System Overview

The Compliance Validator Agent is a four-stage sequential multi-agent pipeline that ingests Indian GST invoices in any format and produces a structured compliance report with a final decision (APPROVED / REJECTED / ESCALATE_TO_HUMAN / HOLD_FOR_VERIFICATION).

```
┌────────────────────────────────────────────────────────────────────────┐
│                         ENTRY POINT: main.py                           │
│  CLI args: --input <path|dir>  --output <dir>                          │
└────────────────────────┬───────────────────────────────────────────────┘
                         │  collect_invoice_paths()
                         │  load_input() → (raw_invoice, needs_extraction)
                         ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     MASTER DATA (MasterData)                           │
│  vendor_registry.json  │  gst_rates_schedule.csv  │  hsn_sac_codes.json│
│  tds_sections.json     │  company_policy.yaml      │  historical.jsonl  │
└────────────────────────┬───────────────────────────────────────────────┘
                         │ passed as context to Validator / Extractor
                         ▼
          ┌──────────────────────────────────────┐
          │           PIPELINE (per invoice)      │
          │                                       │
          │  Step 1         Step 2                │
          │  Extractor  ──▶ Validator            │
          │  (CrewAI)       (Python class)        │
          │                     │                 │
          │  Step 3         Step 4                │
          │  Reporter   ◀──     Resolver         │
          │  (results)         │
          │      │──────────────▶ (Python)       │
          └──────────────────────────────────────┘
                         │
                         ▼
             reports/<invoice_id>.json
             reports/batch_summary.json
```

---

## 2. Agent Roles

### 2.1 ExtractorAgent (CrewAI Agent)

**File:** `/agents/extractor_agent.py`

**Role:** Converts any invoice format into a structured Python dictionary.

**Tools available:**

| Tool | Trigger | Library |
|------|---------|---------|
| `read_pdf` | `.pdf` extension | pdfplumber |
| `read_image_ocr` | `.png`, `.jpg`, `.jpeg` | pytesseract + Pillow |
| `read_text_file` | `.txt`, `.csv` | built-in |
| `parse_json_invoice` | `.json` | json stdlib |

**LLM:** Groq `llama-3.3-70b-versatile` (temperature=0 for determinism)

The agent is given a CrewAI `Task` (see `extraction_task.py`) that specifies:
- Where to find the invoice (file path or pre-extracted text)
- The exact JSON schema to return
- OCR error-correction rules (O→0, I→1, l→1, S→5)

The agent is capped at `max_iter=3` to prevent runaway loops.

**Bypass condition:** If the input is already a `.json` file, the loader returns `needs_extraction=False` and the Extractor is skipped entirely — the structured dict goes directly to the Validator.

---

### 2.2 ValidatorAgent (Python class)

**File:** `/agents/validator_agent.py`

**Role:** Runs 10 deterministic compliance checks across 5 categories and returns both flat (`raw_results`) and category-grouped (`grouped_results`) dicts.

**Check categories:**

| Category | Checks | Max Score |
|----------|--------|-----------|
| A — Authenticity | A1 Invoice Number, A2 Duplicate | 2 |
| B — GST | B1 GSTIN Format, B7 Tax Split | 2 |
| C — Arithmetic | C1 Line Calc, C2 Subtotal | 2 |
| D — TDS | D1 Applicability, D2 Section | 2 |
| E — Policy | E1 PO Tolerance, E3 Vendor Approved | 2 |

Each check returns a dict with: `score`, `max_score`, `status` (PASS/FAIL/SKIP), and `reason`.

**Master data used:** vendor_registry (A2, D1, E3), company_policy (E1 tolerance), tds_sections (D1).

**Deduplication state:** `seen_invoices` list is maintained in-memory across invoices within a single run, enabling cross-invoice duplicate detection (A2).

---

### 2.3 ResolverAgent (Python class)

**File:** `/agents/resolver_agent.py`

**Role:** Aggregates validation results into a final decision.

**Decision logic (evaluated in priority order):**

```
1. Any FAIL reason contains missing/unknown/unresolvable data?
   → HOLD_FOR_VERIFICATION

2. Any FAIL check (regardless of reason)?
   → REJECTED

3. Confidence (total_score / max_score) < 0.70?
   → ESCALATE_TO_HUMAN

4. All checks passed, confidence ≥ 0.70?
   → APPROVED
```

**Outputs:** decision, confidence (float 0–1), requires_human_review (bool), failed_checks (list), missing_data_checks (list), reason (string).

---

### 2.4 ReporterAgent (Python class)

**File:** `/agents/reporter_agent.py`

**Role:** Assembles the final output JSON and writes it to disk.

**Outputs:**
- `compliance_score` — percentage of points earned across all 10 checks
- `tds_summary` — TDS applicability, section, GSTIN, invoice amount
- `gst_summary` — GSTIN validity, CGST/SGST/IGST breakdown
- `audit_trail` — timestamped log of every agent action and check result
- Full pass-through of resolver outputs (decision, confidence, failed_checks, critical_failures)

Reports are saved as `reports/<invoice_id>.json`.

---

## 3. Data Flow Diagram

```
Invoice File
     │
     ▼
loader.py ──────────────────────────────────────────────────────────┐
  • .json  → raw dict,  needs_extraction=False                      │
  • .pdf   → {text: ...}, needs_extraction=True                     │
  • .txt   → {text: ...}, needs_extraction=True                     │
  • image  → {text: OCR}, needs_extraction=True                     │
     │                                                               │
     ▼                                                               │
[needs_extraction=True?]                                            │
     │                                                               │
    YES                          NO ──────────────────────────────▶ │
     │                                                               │
     ▼                                                               ▼
ExtractorAgent (CrewAI)                                    raw dict (invoice)
  LLM: llama-3.3-70b                                               │
  Tools: read_pdf, read_image_ocr,                                 │
         read_text_file, parse_json_invoice                        │
  Output: JSON string → parsed to dict                             │
     │                                                              │
     └──────────────────────────────────────────────────────────▶  │
                                                                    ▼
                                                         ValidatorAgent.run()
                                                           ├─ A1 invoice number
                                                           ├─ A2 duplicate
                                                           ├─ B1 GSTIN format
                                                           ├─ B7 tax split
                                                           ├─ C1 line calc
                                                           ├─ C2 subtotal
                                                           ├─ D1 TDS applicability
                                                           ├─ D2 TDS section
                                                           ├─ E1 PO tolerance
                                                           └─ E3 vendor approved
                                                                    │
                                                         raw_results + grouped_results
                                                                    │
                                                                    ▼
                                                         ResolverAgent.run()
                                                           → decision
                                                           → confidence
                                                           → failed_checks
                                                                    │
                                                                    ▼
                                                         ReporterAgent.run()
                                                           → compliance_score
                                                           → tds_summary
                                                           → gst_summary
                                                           → audit_trail
                                                                    │
                                                                    ▼
                                                     reports/<invoice_id>.json
```

---

## 4. Tools Used

| Tool / Library | Purpose |
|---------------|---------|
| **CrewAI** | Agent orchestration framework for the ExtractorAgent |
| **Groq API** (`llama-3.3-70b-versatile`) | LLM backbone for invoice extraction |
| **pdfplumber** | Text extraction from PDF files |
| **pytesseract + Pillow** | OCR for image-based invoices |
| **pandas** | Loading `gst_rates_schedule.csv` from master data |
| **PyYAML** | Loading `company_policy.yaml` |
| **Python stdlib** (`json`, `re`, `difflib`, `datetime`) | All validation logic — no external dependencies |
| **Python `logging`** | Structured dual-output logging (stdout + `logs/app.log`) |

---

## 5. Error Handling Strategy

The pipeline is designed to never crash the entire batch due to a single invoice failure:

- **File load failure** → HOLD_FOR_VERIFICATION report written, processing continues
- **Extraction failure** (LLM returns invalid JSON) → HOLD_FOR_VERIFICATION with error details in audit_trail
- **Validation exception** → propagated up to `process_invoice`, caught in main loop → error report written
- **Individual check exception** → ValidatorAgent lets it propagate so the invoice is flagged rather than silently passing

All decisions, errors, and check results are recorded in the `audit_trail` array of every report.

---

## 6. Key Design Decisions

**Why CrewAI only for extraction?** The validator, resolver, and reporter are deterministic — they don't need LLM reasoning. Using Python classes keeps them fast, testable, and free of hallucination risk.

**Why Groq / llama-3.3-70b?** High throughput, low latency, and free tier available — suitable for batch invoice processing. Temperature=0 ensures deterministic extraction outputs.

**Why `needs_extraction` flag?** Structured JSON invoices are already machine-readable. Running them through the LLM would add latency and introduce hallucination risk with no benefit.

**Why in-memory `seen_invoices` for deduplication?** Keeps A2 stateless between runs (each batch starts fresh) while still catching duplicates within a single batch. For production, this should be backed by a persistent store (Redis, PostgreSQL).


