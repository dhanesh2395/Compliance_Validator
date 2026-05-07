from utils.logger import get_logger

logger = get_logger("Resolver")


class ResolverAgent:

    def __init__(self):

        self.data_issue_phrases = [
            "unknown",
            "not found",
            "missing",
            "unclear",
            "unresolvable"
        ]

    def run(self, validation_results, invoice=None):

        logger.info("Running resolver")

        total_score = 0
        max_score = 0

        failed_checks = []
        missing_data_checks = []

        # =========================================
        # PROCESS VALIDATION RESULTS
        # =========================================
        for check, result in validation_results.items():

            score = result.get("score", 0)
            max_s = result.get("max_score", 1)

            total_score += score
            max_score += max_s

            status = result.get("status", "FAIL")

            logger.debug(
                f"{check} | Status={status} | "
                f"Score={score}/{max_s}"
            )

            # -------------------------------------
            # FAILED CHECKS
            # -------------------------------------
            if status == "FAIL":

                failed_checks.append(check)

                reason = str(
                    result.get("reason", "")
                ).lower()

                # Missing/unresolvable data detection
                if any(
                    phrase in reason
                    for phrase in self.data_issue_phrases
                ):
                    missing_data_checks.append(check)

        # =========================================
        # CONFIDENCE SCORE
        # =========================================
        confidence = (
            total_score / max_score
            if max_score else 0
        )

        # =========================================
        # FINAL DECISION LOGIC
        # =========================================

        # -------------------------------------
        # HOLD FOR VERIFICATION
        # Missing or unresolved data
        # -------------------------------------
        if missing_data_checks:

            decision = "HOLD_FOR_VERIFICATION"

            reason = (
                "Missing or unresolvable data detected in checks: "
                f"{missing_data_checks}"
            )

        # -------------------------------------
        # REJECTED
        # Any failed compliance rule
        # -------------------------------------
        elif failed_checks:

            decision = "REJECTED"

            reason = (
                "Compliance validation failed for checks: "
                f"{failed_checks}"
            )

        # -------------------------------------
        # LOW CONFIDENCE
        # -------------------------------------
        elif confidence < 0.7:

            decision = "ESCALATE_TO_HUMAN"

            reason = (
                f"Low confidence score "
                f"({round(confidence, 2)})"
            )

        # -------------------------------------
        # APPROVED
        # -------------------------------------
        else:

            decision = "APPROVED"

            reason = (
                "All compliance checks passed"
            )

        logger.info(
            f"Decision={decision} | "
            f"Confidence={confidence:.2f}"
        )

        # =========================================
        # FINAL RESPONSE
        # =========================================
        return {

            "decision": decision,

            "confidence": round(confidence, 2),

            "requires_human_review": (
                decision in [
                    "ESCALATE_TO_HUMAN",
                    "HOLD_FOR_VERIFICATION"
                ]
            ),

            "failed_checks": failed_checks,

            "missing_data_checks": missing_data_checks,

            "reason": reason
        }