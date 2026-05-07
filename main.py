"""
main.py — Compliance Validator Agent
Entry point for the Datamatics Agentic AI Assessment.

Usage:
    python src/main.py --input <path> --output <path>

Examples:
    python src/main.py --input data/invoices/ --output reports/
    python src/main.py --input data/invoices/INV-2024-0001.json --output reports/
"""

import argparse
import json
import os
import sys
import traceback
from datetime import datetime

# ── Agent imports ────────────────────────────────────────────────────────────
from agents.extractor_agent import extractor_agent
from agents.validator_agent import ValidatorAgent
from agents.resolver_agent import ResolverAgent
from agents.reporter_agent import ReporterAgent

# ── Task / loader imports ────────────────────────────────────────────────────
from tasks.extraction_task import create_extraction_task
from utils.loader import load_input
from utils.data_loader import MasterData
from utils.logger import get_logger

logger = get_logger("Main")


# ── Supported invoice file extensions ────────────────────────────────────────
SUPPORTED_EXTENSIONS = {".json", ".pdf", ".txt", ".png", ".jpg", ".jpeg", ".csv"}


def collect_invoice_paths(input_path):
    """Return a list of invoice file paths from a file or directory."""
    if os.path.isfile(input_path):
        return [input_path]

    if os.path.isdir(input_path):
        paths = []
        for fname in sorted(os.listdir(input_path)):
            ext = os.path.splitext(fname)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                paths.append(os.path.join(input_path, fname))
        return paths

    raise FileNotFoundError(f"Input path not found: {input_path}")


def process_invoice(raw_invoice, needs_extraction, master_data, validator, resolver, reporter):
    """
    Full pipeline for a single invoice:
        Extractor → Validator → Resolver → Reporter
    """
    audit_trail = []

    # ── Step 1: Extract (if raw text / image / PDF) ───────────────────────
    if needs_extraction:
        audit_trail.append({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "agent": "ExtractorAgent",
            "action": "Extracting structured data from raw input",
        })

        task = create_extraction_task(extractor_agent, raw_invoice, master_data)

        try:
            from crewai import Crew
            crew = Crew(agents=[extractor_agent], tasks=[task], verbose=False)
            result = crew.kickoff()


            # Parse JSON from LLM output
            raw_text = str(result).strip()
            # Strip markdown code fences if present
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
            invoice = json.loads(raw_text.strip())

            audit_trail.append({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "agent": "ExtractorAgent",
                "action": "Extraction complete",
                "extracted_fields": list(invoice.keys()),
            })

        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Extraction failed: {e}")
            audit_trail.append({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "agent": "ExtractorAgent",
                "action": "Extraction FAILED",
                "error": str(e),
            })
            # Return a HOLD decision — data is unresolvable
            return {
                "invoice_id": "UNKNOWN",
                "overall_decision": "HOLD_FOR_VERIFICATION",
                "compliance_score": 0,
                "confidence": 0.0,
                "requires_human_review": True,
                "validation_results": {},
                "tds_summary": {},
                "gst_summary": {},
                "audit_trail": audit_trail,
                "resolver_reason": f"Extraction failed: {e}",
                "failed_checks": [],
                "critical_failures": [],
            }
    else:
        invoice = raw_invoice
        audit_trail.append({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "agent": "ExtractorAgent",
            "action": "Structured JSON input — extraction skipped",
        })

    # ── Step 2: Validate ─────────────────────────────────────────────────
    audit_trail.append({
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "agent": "ValidatorAgent",
        "action": "Running 10-point compliance checks",
    })

    raw_results, grouped_results = validator.run(invoice, master_data)

    for check_id, result in raw_results.items():
        audit_trail.append({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "agent": "ValidatorAgent",
            "check": check_id,
            "status": result["status"],
            "reason": result["reason"],
        })

    # ── Step 3: Resolve ───────────────────────────────────────────────────
    audit_trail.append({
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "agent": "ResolverAgent",
        "action": "Determining final decision",
    })

    resolver_output = resolver.run(raw_results, invoice=invoice)

    audit_trail.append({
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "agent": "ResolverAgent",
        "action": "Decision reached",
        "decision": resolver_output["decision"],
        "confidence": resolver_output["confidence"],
        "reason": resolver_output["reason"],
    })

    # ── Step 4: Report ────────────────────────────────────────────────────
    report = reporter.run(invoice, grouped_results, resolver_output, audit_trail)
    return report


def main():
    try:
        parser = argparse.ArgumentParser(
            description="Compliance Validator Agent — Invoice Compliance Checker"
        )
        parser.add_argument(
            "--input", required=True,
            help="Path to an invoice file or directory of invoices"
        )
        parser.add_argument(
            "--output", required=True,
            help="Directory to write output JSON reports"
        )
        args = parser.parse_args()

        logger.info(f"Starting Compliance Validator | Input: {args.input} | Output: {args.output}")

        # ── Load master data ─────────────────────────────────────────────────
        master_data = MasterData()
        try:
            master_data.load_all()
        except Exception as e:
            logger.error(f"Failed to load master data: {e}")
            sys.exit(1)

        # ── Initialise agents ─────────────────────────────────────────────────
        validator = ValidatorAgent()
        resolver = ResolverAgent()
        reporter = ReporterAgent()

        # ── Collect invoice paths ─────────────────────────────────────────────
        try:
            invoice_paths = collect_invoice_paths(args.input)
        except FileNotFoundError as e:
            logger.error(str(e))
            sys.exit(1)

        logger.info(f"Found {len(invoice_paths)} invoice(s) to process")

        os.makedirs(args.output, exist_ok=True)

        # ── Batch summary counters ────────────────────────────────────────────
        summary = {"APPROVED": 0, "REJECTED": 0, "ESCALATE_TO_HUMAN": 0, "HOLD_FOR_VERIFICATION": 0}
        all_reports = []

        for path in invoice_paths:
            logger.info(f"Processing: {path}")

            try:
                raw_invoice, needs_extraction = load_input(path)
            except Exception as e:
                logger.error(f"Failed to load {path}: {e}")
                # Do NOT crash — continue to next invoice
                error_report = {
                    "invoice_id": os.path.basename(path),
                    "overall_decision": "HOLD_FOR_VERIFICATION",
                    "compliance_score": 0,
                    "confidence": 0.0,
                    "requires_human_review": True,
                    "validation_results": {},
                    "tds_summary": {},
                    "gst_summary": {},
                    "audit_trail": [{
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "agent": "Main",
                        "action": "File load FAILED",
                        "error": str(e),
                    }],
                    "resolver_reason": f"Could not load file: {e}",
                    "failed_checks": [],
                    "critical_failures": [],
                }
                all_reports.append(error_report)
                reporter.save(error_report, args.output)
                summary["HOLD_FOR_VERIFICATION"] += 1
                continue

            # Normalize to list (clean design)
            invoices = raw_invoice if isinstance(raw_invoice, list) else [raw_invoice]


            logger.info(f"Total invoices in file: {len(invoices)}")

            for idx, inv in enumerate(invoices):
                logger.info(f"Processing invoice #{idx}")

                try:
                    report = process_invoice(
                        inv, needs_extraction if not isinstance(raw_invoice, list) else False,
                        master_data, validator, resolver, reporter
                    )



                    #  Ensure invoice_id exists (important for filename safety)
                    invoice_id = report.get("invoice_id", f"UNKNOWN_{idx}")

                    #  Save report
                    reporter.save(report, args.output)

                    all_reports.append(report)

                    summary[report["overall_decision"]] = summary.get(
                        report["overall_decision"], 0
                    ) + 1

                except Exception as e:
                    logger.error(f"Invoice #{idx} FAILED: {e}")
                    logger.debug(traceback.format_exc())

                    error_report = {
                        "invoice_id": inv.get("invoice_id", f"UNKNOWN_{idx}"),
                        "overall_decision": "HO00000LD_FOR_VERIFICATION",
                        "compliance_score": 0,
                        "confidence": 0.0,
                        "requires_human_review": True,
                        "validation_results": {},
                        "tds_summary": {},
                        "gst_summary": {},
                        "audit_trail": [{
                            "timestamp": datetime.utcnow().isoformat() + "Z",
                            "agent": "Main",
                            "action": "Processing FAILED",
                            "error": str(e),
                        }],
                        "resolver_reason": str(e),
                        "failed_checks": [],
                        "critical_failures": [],
                    }

                    reporter.save(error_report, args.output)
                    all_reports.append(error_report)

                    summary["HOLD_FOR_VERIFICATION"] += 1

        # ── Batch summary report ──────────────────────────────────────────────
        # ── Detailed Batch Summary ────────────────────────────────────────────

        decision_wise_reports = {
            "APPROVED": [],
            "REJECTED": [],
            "ESCALATE_TO_HUMAN": [],
            "HOLD_FOR_VERIFICATION": []
        }

        for report in all_reports:

            decision = report.get(
                "overall_decision",
                "UNKNOWN"
            )

            report_entry = {

                "invoice_id": report.get(
                    "invoice_id"
                ),

                "confidence": report.get(
                    "confidence"
                ),

                "reason": report.get(
                    "resolver_reason"
                ),

                "requires_human_review": report.get(
                    "requires_human_review"
                ),

                "failed_checks": report.get(
                    "failed_checks",
                    []
                )
            }

            if decision in decision_wise_reports:
                decision_wise_reports[decision].append(
                    report_entry
                )

        # Final batch summary
        batch_summary = {

            "processed_files": len(invoice_paths),

            "processed_invoices": len(all_reports),

            "summary_counts": summary,

            "decision_wise_reports": decision_wise_reports,

            "reports_saved_to": args.output,

            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

        summary_path = os.path.join(
            args.output,
            "batch_summary.json"
        )

        with open(summary_path, "w") as f:
            json.dump(
                batch_summary,
                f,
                indent=2
            )

        logger.info(f"Batch complete: {summary}")
        logger.info(f"Summary written to: {summary_path}")

        logger.info(f"Batch complete: {summary}")
        logger.info(f"Summary written to: {summary_path}")
        print(f"\nDone. Results in: {args.output}")
        print(json.dumps(summary, indent=2))
    except Exception as e:
        traceback.print_exception(e)
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    main()
