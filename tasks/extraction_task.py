from crewai import Task
from utils.logger import get_logger

logger = get_logger("ExtractorTask")


def create_extraction_task(agent, invoice_input: dict, master_data):
    """
    Build the CrewAI extraction task.

    invoice_input is either:
      - {"path": "/path/to/file.pdf"}  → agent must use a tool to read it
      - {"text": "raw text ..."}        → agent already has the text, no tool needed
    """
    logger.info(f"Creating extraction task | input keys: {list(invoice_input.keys())}")

    # Build context from master data so the LLM can validate vendor names, etc.
    known_vendors = list(master_data.vendor_registry.keys()) if master_data.vendor_registry else []
    vendor_hint = (
        f"Known vendor GSTINs in registry: {known_vendors[:10]}"
        if known_vendors else "No vendor registry available."
    )

    # Tell the agent HOW to get the invoice content
    if "path" in invoice_input:
        file_path = invoice_input["path"]
        source_instruction = (
            f"The invoice is stored at: {file_path}\n"
            f"Use the appropriate tool to read it based on its extension "
            f"(.pdf → read_pdf, .png/.jpg/.jpeg → read_image_ocr, "
            f".txt/.csv → read_text_file, .json → parse_json_invoice)."
        )
    else:
        raw_text = invoice_input.get("text", "")
        source_instruction = (
            f"The invoice text has already been extracted:\n\n{raw_text}"
        )

    return Task(
        description=f"""
Extract structured invoice data and return ONLY a valid JSON object.

{source_instruction}

Context:
{vendor_hint}

Required JSON fields (include all that are present in the invoice):
- invoice_id (string)
- invoice_number (string)
- invoice_date (string, format: YYYY-MM-DD)
- vendor_name (string)
- vendor_gstin (string, 15-char alphanumeric)
- buyer_gstin (string)
- items (list of objects with: description, quantity, rate, amount)
- subtotal (float)
- cgst (float)
- sgst (float)
- igst (float)
- total_amount (float)
- po_number (string or null)
- po_amount (float or 0 if absent)
- description (string — overall service/goods description)
- tds_amount (float or 0)

Rules:
- Return ONLY the JSON object — no markdown, no explanation, no extra text
- Do NOT invent or assume missing values; use null for genuinely absent fields
- Fix OCR artifacts in numeric fields: O→0, I→1, l→1, S→5
- Dates: normalise all formats to YYYY-MM-DD
- If a field is truly absent, omit it rather than guessing
        """,
        agent=agent,
        expected_output=(
            "A single valid JSON object containing the structured invoice data. "
            "No markdown fences, no preamble, no trailing text."
        ),
    )
