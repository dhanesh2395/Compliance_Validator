import json
import os
from datetime import datetime
from utils.logger import get_logger

logger = get_logger("Reporter")


class ReporterAgent:
    """
    4th required agent. Assembles the final output JSON per invoice,
    matching the required schema exactly:

    {
      "invoice_id": "...",
      "overall_decision": "APPROVED|REJECTED|ESCALATE_TO_HUMAN|HOLD_FOR_VERIFICATION",
      "compliance_score": <int 0-100>,
      "confidence": <float>,
      "requires_human_review": <bool>,
      "validation_results": {
        "category_a_authenticity": { "score": X, "max_score": Y, "checks": {} },
        "category_b_gst": { ... },
        "category_c_arithmetic": { ... },
        "category_d_tds": { ... },
        "category_e_policy": { ... }
      },
      "tds_summary": {},
      "gst_summary": {},
      "audit_trail": []
    }
    """

    def run(self, invoice, grouped_validation, resolver_output, audit_trail=None):
        logger.info("Reporter: assembling final output")

        invoice_id = invoice.get("invoice_number", "UNKNOWN")

        # Compliance score: percentage of points earned across all categories
        total_score = sum(v["score"] for v in grouped_validation.values())
        total_max = sum(v["max_score"] for v in grouped_validation.values())
        compliance_score = round((total_score / total_max * 100) if total_max else 0)

        # TDS summary
        tds_summary = self._build_tds_summary(invoice, grouped_validation)

        # GST summary
        gst_summary = self._build_gst_summary(invoice, grouped_validation)

        # Audit trail
        if audit_trail is None:
            audit_trail = []

        audit_trail.append({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "agent": "ReporterAgent",
            "action": "Final report assembled",
            "decision": resolver_output["decision"],
            "confidence": resolver_output["confidence"],
        })

        report = {
            "invoice_id": invoice_id,
            "overall_decision": resolver_output["decision"],
            "compliance_score": compliance_score,
            "confidence": resolver_output["confidence"],
            "requires_human_review": resolver_output.get("requires_human_review", False),
            "validation_results": grouped_validation,
            "tds_summary": tds_summary,
            "gst_summary": gst_summary,
            "audit_trail": audit_trail,
            "resolver_reason": resolver_output.get("reason", ""),
            "failed_checks": resolver_output.get("failed_checks", []),
            "critical_failures": resolver_output.get("critical_failures", []),
        }

        logger.info(
            f"Report ready | Invoice: {invoice_id} | "
            f"Decision: {report['overall_decision']} | "
            f"Score: {compliance_score}% | "
            f"Confidence: {resolver_output['confidence']}"
        )

        return report

    def save(self, report, output_dir="reports"):
        """Save report JSON to output directory."""
        os.makedirs(output_dir, exist_ok=True)
        invoice_id = report.get("invoice_id", "UNKNOWN").replace("/", "-")
        path = os.path.join(output_dir, f"{invoice_id}.json")

        with open(path, "w") as f:
            json.dump(report, f, indent=2)

        logger.info(f"Report saved: {path}")
        return path

    def _build_tds_summary(self, invoice, grouped_validation):
        tds = grouped_validation.get("category_d_tds", {})
        d1 = tds.get("checks", {}).get("D1_tds_applicability", {})
        d2 = tds.get("checks", {}).get("D2_tds_section", {})

        return {
            "tds_applicable": d1.get("status") == "PASS",
            "applicability_reason": d1.get("reason", ""),
            "section_determined": d2.get("status") == "PASS",
            "section": d2.get("reason", ""),
            "vendor_gstin": invoice.get("vendor", {}).get("gstin", ""),
            "invoice_amount": invoice.get("total_amount", 0),
        }

    def _build_gst_summary(self, invoice, grouped_validation):
        gst = grouped_validation.get("category_b_gst", {})
        b1 = gst.get("checks", {}).get("B1_gstin_format", {})
        b7 = gst.get("checks", {}).get("B7_tax_split", {})

        return {
            "gstin_valid": b1.get("status") == "PASS",
            "gstin": invoice.get("vendor", {}).get("gstin", ""),
            "tax_split_valid": b7.get("status") == "PASS",
            "cgst": invoice.get("cgst_amount", 0),
            "sgst": invoice.get("sgst_amount", 0),
            "igst": invoice.get("igst_amount", 0),
            "tax_split_reason": b7.get("reason", ""),
        }
