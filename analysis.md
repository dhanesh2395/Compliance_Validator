# Approach & Analysis

## Design Decisions

### Why 4 agents with clear separation?
Each agent has a single responsibility. The Validator uses pure deterministic Python (not LLM) for the 10 checks — this ensures reproducibility and auditability. The LLM is used only in the Extractor where judgment over unstructured text is needed.

### Why not use LLM for all validation?
LLMs can hallucinate on arithmetic (C1, C2) and rule-based checks (B7, E1). Deterministic code gives auditable, consistent results. Confidence scoring is more meaningful when the checks themselves are deterministic.

### Historical data handling
`historical_decisions.jsonl` is explicitly NOT used as a training signal. As per the challenge spec, 15% of historical decisions are incorrect. The validation logic is derived purely from regulations.

## Edge Cases Handled

- **OCR errors**: The LLM extractor is prompted to interpret common OCR artifacts (O vs 0, I vs 1)
- **Missing GSTIN**: Validator explicitly handles empty/None GSTIN with clear fail messages
- **No PO linked**: E1 skips PO tolerance check when `po_amount = 0`
- **Empty description**: D2 fails with a clear message rather than defaulting to a wrong section
- **High-value invoices**: ResolverAgent escalates invoices > ₹10L to human review regardless of check results
- **Batch arrays in single JSON**: `main.py` handles both single-invoice and array JSON files
- **File load errors**: Never crash the batch — log error and produce HOLD_FOR_VERIFICATION report
- **LLM extraction failure**: Caught in try/except; returns HOLD_FOR_VERIFICATION with error in audit trail

## Confidence Score Interpretation

| Confidence | Decision |
|---|---|
| 1.00 | All checks passed |
| 0.70 – 0.99 | Minor issues and greater than 10Lakhs invoive amount — ESCALATE_TO_HUMAN |
| < 0.70 | Low confidence — ESCALATE_TO_HUMAN |
| Critical check failed | REJECTED (regardless of confidence) |
| Data unresolvable | HOLD_FOR_VERIFICATION |

## Known Limitations

- D2 (TDS section) relies on keyword matching in the description field; complex or abbreviated descriptions may not match
- B7 tax split validation does not verify rates against HSN codes (B6, out of scope for this submission)
- Aggregate TDS threshold tracking (D6) is not implemented in this submission scope

Note: E1- if po amount is not there it is skipping


