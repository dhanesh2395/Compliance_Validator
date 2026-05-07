# Compliance Validator Agent

An agentic AI pipeline that validates Indian GST invoices for compliance, authenticity, arithmetic correctness, TDS applicability, and company policy adherence. Built for the Datamatics Agentic AI Assessment.

---

## Architecture Overview

```
Invoice File(s)
      │
      ▼
┌─────────────┐     ┌─────────────────┐     ┌──────────────┐     ┌───────────────┐
│  Extractor  │────▶│    Validator    │────▶│   Resolver   │────▶│   Reporter    │
│  (CrewAI)   │     │  (10 checks)    │     │  (decision)  │     │  (JSON out)   │
└─────────────┘     └─────────────────┘     └──────────────┘     └───────────────┘
                            │
                    Master Data (JSON/CSV/YAML)
```

Four agents work sequentially per invoice:
1. **ExtractorAgent** — reads PDF / image / text / JSON → structured dict
2. **ValidatorAgent** — runs 10 compliance checks across 5 categories
3. **ResolverAgent** — aggregates scores → final decision
4. **ReporterAgent** — emits the output JSON report

---

## Prerequisites

- Python 3.10+
- Tesseract OCR installed on the system

### Install Tesseract

**Ubuntu / Debian:**
```bash
sudo apt-get update && sudo apt-get install -y tesseract-ocr
```

**macOS (Homebrew):**
```bash
brew install tesseract
```

**Windows:**
Download installer from https://github.com/UB-Mannheim/tesseract/wiki and add to PATH.

---

## Installation

```bash
# 1. Clone the repository
git clone <repo-url>
cd compliance-validator

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # Linux / macOS
# venv\Scripts\activate.bat     # Windows

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Edit .env and add your GROQ_API_KEY
```

---

## Project Structure

```
compliance-validator/

   ├── main.py                    # Entry point
   ├── agents/
   │   ├── extractor_agent.py     # CrewAI extraction agent
   │   ├── validator_agent.py     # 10-check compliance validator
   │   ├── resolver_agent.py      # Decision resolver
   │   └── reporter_agent.py      # Report assembler
   ├── tasks/
   │   └── extraction_task.py     # CrewAI task definition
   ├── tools/
   │   └── llm.py                 # LLM provider (Groq / llama-3.3-70b)
   └── utils/
   │    ├── loader.py              # Invoice file loader
   │    ├── data_loader.py         # Master data loader
   │    └── logger.py              # Structured logger
   ├── data/
   │   ├── vendor_registry.json
   │   ├── gst_rates_schedule.csv
   │   ├── hsn_sac_codes.json
   │   ├── tds_sections.json
   │   ├── company_policy.yaml
   │   └── historical_decisions.jsonl
   ├── output/
   ├── input                      
   ├── logs/                          
   ├── checks_manifest.json
   ├── architecture.md
   ├── requirements.txt
   ├── .env.example
   └── README.md
```

---
## Usage

### Process a single invoice
```bash
python main.py --input "D:\dhanesh\compliance_validator_original\input\ INV-2024-0001.json" --output "D:\dhanesh\compliance_validator_original\output" ```

### Process a directory of invoices
```bash
python main.py --input "D:\dhanesh\compliance_validator_original\input" --output "D:\dhanesh\compliance_validator_original\output" ```

### Supported input formats
| Format | Notes |
|--------|-------|
| `.json` | Structured invoice — extraction skipped |
| `.pdf` | Text or text-over-image PDF |
| `.txt` / `.csv` | Plain-text invoice |
| `.png` / `.jpg` / `.jpeg` | OCR via Tesseract |

---

## Output

Each invoice produces a JSON report in `--output`:

```json
{
  "invoice_id": "INV-2024-0001",
  "overall_decision": "APPROVED",
  "compliance_score": 95,
  "confidence": 0.95,
  "requires_human_review": false,
  "validation_results": { ... },
  "tds_summary": { ... },
  "gst_summary": { ... },
  "audit_trail": [ ... ]
}
```

A `batch_summary.json` is also written to `--output` after all invoices are processed.

### Decision values
| Decision | Meaning |
|----------|---------|
| `APPROVED` | All checks passed, confidence ≥ 0.7 |
| `REJECTED` | One or more compliance checks failed |
| `ESCALATE_TO_HUMAN` | No failures but confidence < 0.7 |
| `HOLD_FOR_VERIFICATION` | Missing or unresolvable data detected |

---

## Master Data Setup

Place the following files in `data/` before running:

| File | Format | Description |
|------|--------|-------------|
| `vendor_registry.json` | JSON | Approved vendors with GSTIN, PAN, TDS section, LDC |
| `gst_rates_schedule.csv` | CSV | HSN-wise GST rates |
| `hsn_sac_codes.json` | JSON | HSN / SAC code descriptions |
| `tds_sections.json` | JSON | TDS section rules and thresholds |
| `company_policy.yaml` | YAML | PO tolerance, approval limits, etc. |
| `historical_decisions.jsonl` | JSONL | Past invoice decisions (one per line) |

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | Yes | API key for Groq (LLM provider) |

---

## Logs

Logs are written to `logs/app.log` and to stdout. Log level is `DEBUG`.

---

## Running Tests

```bash
pytest tests/ -v
```

