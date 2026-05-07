import json
import os
import re

import pdfplumber
import pytesseract
from crewai import Agent
from crewai.tools import tool
from PIL import Image
from tools.llm import get_llm
from utils.logger import get_logger

logger = get_logger("Extractor")
llm = get_llm()


# ── Tools ─────────────────────────────────────────────────────────────────────
# CrewAI tools are plain functions decorated with @tool.
# The agent picks which tool to call based on the task description.

@tool("read_pdf")
def read_pdf(path: str) -> str:
    """
    Extract all text from a PDF invoice file.
    Input: absolute or relative file path to a .pdf file.
    Output: raw extracted text string.
    """
    logger.info(f"read_pdf: {path}")
    try:
        with pdfplumber.open(path) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        text = "\n".join(pages).strip()
        if not text:
            return "ERROR: No text extracted from PDF — may be a scanned image PDF."
        return text
    except Exception as e:
        logger.error(f"read_pdf failed: {e}")
        return f"ERROR: {e}"


@tool("read_image_ocr")
def read_image_ocr(path: str) -> str:
    """
    Extract text from an invoice image (PNG, JPG, JPEG) using OCR.
    Input: absolute or relative file path to an image file.
    Output: OCR-extracted text string.
    Common OCR errors to watch for: O vs 0, I vs 1, l vs 1, S vs 5.
    """
    logger.info(f"read_image_ocr: {path}")
    try:
        img = Image.open(path)
        text = pytesseract.image_to_string(img).strip()
        if not text:
            return "ERROR: OCR returned no text — image may be blank or too low resolution."
        return text
    except Exception as e:
        logger.error(f"read_image_ocr failed: {e}")
        return f"ERROR: {e}"


@tool("read_text_file")
def read_text_file(path: str) -> str:
    """
    Read a plain text (.txt) or CSV invoice file.
    Input: absolute or relative file path.
    Output: file contents as a string.
    """
    logger.info(f"read_text_file: {path}")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except Exception as e:
        logger.error(f"read_text_file failed: {e}")
        return f"ERROR: {e}"


@tool("parse_json_invoice")
def parse_json_invoice(path: str) -> str:
    """
    Load a structured JSON invoice file and return it as a formatted JSON string.
    Input: absolute or relative file path to a .json file.
    Output: pretty-printed JSON string of the invoice data.
    """
    logger.info(f"parse_json_invoice: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return json.dumps(data, indent=2)
    except Exception as e:
        logger.error(f"parse_json_invoice failed: {e}")
        return f"ERROR: {e}"


# ── Agent definition ──────────────────────────────────────────────────────────

extractor_agent = Agent(
    role="Invoice Extraction Specialist",
    goal=(
        "Extract structured invoice data from raw input accurately and return ONLY valid JSON. "
        "Use the appropriate tool based on file type: "
        "read_pdf for PDFs, read_image_ocr for images, "
        "read_text_file for TXT/CSV, parse_json_invoice for JSON files. "
        "Fix common OCR artifacts: O→0, I→1, l→1, S→5 in numeric fields."
    ),
    backstory=(
        "You are an expert in Indian invoice parsing with deep knowledge of GST invoice formats. "
        "You handle messy, scanned, and OCR-corrupted invoices daily. "
        "You always return clean, complete JSON — never partial, never with extra commentary."
    ),
    tools=[read_pdf, read_image_ocr, read_text_file, parse_json_invoice],
    llm=llm,
    verbose=True,
    # Do not allow the agent to keep looping if it gets a good answer
    max_iter=3,
)


# ── Optional helper ───────────────────────────────────────────────────────────

def clean_extracted_json(raw_output: str) -> dict:
    """
    Parse the LLM's text output into a Python dict.
    Handles markdown code fences (```json ... ```) that the LLM may add.
    Raises json.JSONDecodeError if the output cannot be parsed.
    """
    text = raw_output.strip()

    # Strip markdown fences
    if text.startswith("```"):
        # Remove opening fence line
        text = re.sub(r"^```(?:json)?\s*", "", text)
        # Remove closing fence
        text = re.sub(r"\s*```$", "", text)

    return json.loads(text.strip())


def log_invoice(invoice: dict) -> None:
    """Log a structured invoice dict for audit/debugging."""
    logger.info(f"Extracted Invoice: {json.dumps(invoice, indent=2)}")
