import re
from utils.logger import get_logger
from datetime import datetime
from difflib import SequenceMatcher

logger = get_logger("Validator")

GSTIN_REGEX = r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[A-Z0-9]{1}Z[A-Z0-9]{1}$'


class ValidatorAgent:

    def __init__(self):
        self.seen_invoices = []

        self.policy = {
            "duplicate_rules": {
                "duplicate_fields": ["invoice_number", "vendor_gstin", "total_amount"],
                "duplicate_window_days": 365,
                "near_duplicate_threshold": 0.95,
            }
        }

    # ================= RUN =================
    def run(self, invoice, master_data):
        inv_no = (invoice.get("invoice_id") or "").strip()

        logger.info(f"Starting validation for invoice: {inv_no}")
        logger.debug(f"Invoice payload: {invoice}")

        try:
            raw_results = {
                "A1_invoice_number": self.check_invoice_number(invoice),
                "A2_duplicate": self.check_duplicate(invoice),

                "B1_gstin_format": self.check_gstin(invoice),
                "B7_tax_split": self.check_tax_split(invoice),

                "C1_line_calc": self.check_line_calc(invoice),
                "C2_subtotal": self.check_subtotal(invoice),

                "D1_tds_applicability": self.check_tds_applicability(invoice, master_data),
                "D2_tds_section": self.check_tds_section(invoice),

                "E1_po_tolerance": self.check_po_tolerance(invoice),
                "E3_vendor_approved": self.check_vendor_approved(invoice, master_data),
            }

            grouped = self._group_by_category(raw_results)

            logger.info(" Validation completed")
            logger.debug(f" Raw Results: {raw_results}")
            logger.debug(f"Grouped Results: {grouped}")


            return raw_results, grouped

        except Exception as e:
            logger.exception(f" VALIDATION CRASHED for invoice: {inv_no}")
            raise

    # ================= GROUP =================
    def _group_by_category(self, raw_results):
        category_map = {
            "category_a_authenticity": ["A1_invoice_number", "A2_duplicate"],
            "category_b_gst": ["B1_gstin_format", "B7_tax_split"],
            "category_c_arithmetic": ["C1_line_calc", "C2_subtotal"],
            "category_d_tds": ["D1_tds_applicability", "D2_tds_section"],
            "category_e_policy": ["E1_po_tolerance", "E3_vendor_approved"],
        }

        grouped = {}

        for category, checks in category_map.items():
            score = sum(raw_results[c]["score"] for c in checks)
            max_score = sum(raw_results[c]["max_score"] for c in checks)

            grouped[category] = {
                "score": score,
                "max_score": max_score,
                "checks": {c: raw_results[c] for c in checks},
            }

        return grouped

    # ================= HELPERS =================
    def similarity(self, a, b):
        return SequenceMatcher(None, str(a), str(b)).ratio()

    def pass_check(self, msg):
        if isinstance(msg, dict):
            return {"score": 1, "max_score": 1, "status": "PASS",
                    "reason": msg.get("reason", "Check passed"), **msg}
        return {"score": 1, "max_score": 1, "status": "PASS", "reason": msg}

    def fail_check(self, msg):
        if isinstance(msg, dict):
            return {"score": 0, "max_score": 1, "status": "FAIL",
                    "reason": msg.get("reason", "Check failed"), **msg}
        return {"score": 0, "max_score": 1, "status": "FAIL", "reason": msg}

    def skip_check(self, msg):
        if isinstance(msg, dict):
            return {"score": 0, "max_score": 0, "status": "SKIP",
                    "reason": msg.get("reason", "Check skipped"), **msg}
        return {"score": 0, "max_score": 0, "status": "SKIP", "reason": msg}

    # ================= A1 =================
    def check_invoice_number(self, invoice):
        logger.info("A1: Invoice Number Check")

        inv = (invoice.get("invoice_number") or "").strip()
        logger.debug(f"Invoice number: {inv}")

        if re.match(r'^[A-Z0-9\-\/]{3,20}$', inv):
            return self.pass_check("Valid invoice number")

        logger.warning("Invalid invoice number format")
        return self.fail_check(f"Invalid format: {inv}")

    # ================= A2 =================
    def check_duplicate(self, invoice):
        logger.info("A2: Duplicate Check")

        rules = self.policy["duplicate_rules"]

        # -----------------------------
        # Normalize fields
        # -----------------------------
        vendor_gstin = (
                invoice.get("vendor_gstin")
                or invoice.get("vendor", {}).get("gstin")
                or ""
        ).strip().upper()

        invoice_number = (invoice.get("invoice_number") or "").strip()

        invoice_amount = float(
            invoice.get("total_amount") or 0
        )

        invoice_date_str = (invoice.get("invoice_date") or "").strip()

        if not invoice_date_str:
            return self.fail_check("Missing invoice_date")

        try:
            invoice_date = datetime.strptime(invoice_date_str, "%Y-%m-%d")
        except:
            return self.fail_check("Invalid invoice_date format")

        # -----------------------------
        # Build duplicate key
        # -----------------------------
        key = (vendor_gstin, invoice_number, invoice_amount)

        logger.debug(f"Duplicate Key: {key}")

        # -----------------------------
        # Duplicate comparison (invoice vs invoice)
        # -----------------------------
        for record in self.seen_invoices:

            record_date = record["date"]

            # WINDOW CHECK BETWEEN TWO INVOICES
            date_diff = abs((invoice_date - record_date).days)

            if date_diff > rules["duplicate_window_days"]:
                continue  # skip old invoices

            # -------------------------
            # EXACT DUPLICATE
            # -------------------------
            if key == record["key"]:
                return self.fail_check("Exact duplicate invoice detected")

            # -------------------------
            # NEAR DUPLICATE (same vendor only)
            # -------------------------
            if vendor_gstin == record["vendor"]:

                score = (
                        self.similarity(invoice_number, record["invoice_number"]) * 0.4 +
                        self.similarity(
                            " ".join([str(i.get("description", "")) for i in invoice.get("line_items", [])]),
                            record["description"]
                        ) * 0.4 +
                        (1 - abs(invoice_amount - record["amount"]) / max(invoice_amount, 1)) * 0.2
                )

                logger.debug(f"Near duplicate score: {score}")

                if score >= rules["near_duplicate_threshold"]:
                    return self.fail_check(f"Near duplicate invoice ({score:.2f})")

        # -----------------------------
        # STORE CURRENT INVOICE
        # -----------------------------
        self.seen_invoices.append({
            "key": key,
            "vendor": vendor_gstin,
            "invoice_number": invoice_number,
            "amount": invoice_amount,
            "date": invoice_date,
            "description": " ".join([
                str(invoice.get("description") or ""),
                *[str(i.get("description") or "") for i in invoice.get("line_items", [])]
            ])
        })

        return self.pass_check("No duplicate detected")

    # ================= B1 =================
    def check_gstin(self, invoice):

        logger.info("B1: GSTIN Check")

        vendor = invoice.get("vendor", {})

        # =============================
        # ORIGINAL VALUE
        # =============================
        gstin_raw = (vendor.get("gstin") or "").strip()

        # validation copy only
        gstin_for_validation = gstin_raw.upper()

        country_raw = (vendor.get("country") or "").strip().lower()

        logger.debug(f"Original GSTIN: {gstin_raw}")
        logger.debug(f"Validation GSTIN: {gstin_for_validation}")

        # -----------------------------
        # INDIA DETECTION
        # -----------------------------
        is_india_from_gstin = bool(
            gstin_for_validation and
            re.match(GSTIN_REGEX, gstin_for_validation)
        )

        is_india_from_country = country_raw in [
            "india",
            "in",
            "bharat"
        ]

        is_india = is_india_from_gstin or is_india_from_country

        # -----------------------------
        # CASE 1: NON-INDIA VENDOR
        # -----------------------------
        if not is_india:
            return self.pass_check({
                "reason": (
                    "GSTIN validation skipped because vendor "
                    "appears to be non-India"
                ),
                "flag": "NON_INDIA_VENDOR"
            })

        # -----------------------------
        # CASE 2: MISSING GSTIN
        # -----------------------------
        if not gstin_raw:
            return self.fail_check({
                "reason": "Missing GSTIN for India vendor",
                "flag": "MISSING_GSTIN"
            })

        # -----------------------------
        # CASE 3: INVALID GSTIN FORMAT
        # -----------------------------
        if not re.match(GSTIN_REGEX, gstin_for_validation):
            return self.fail_check({
                "reason": "Invalid GSTIN format",
                "provided_value": gstin_raw,
                "flag": "INVALID_GSTIN"
            })

        # -----------------------------
        # CASE 4: LOWERCASE / MIXED CASE
        # -----------------------------
        if gstin_raw != gstin_for_validation:
            return {
                "score": 0,
                "max_score": 1,
                "status": "ESCALATE_TO_HUMAN",
                "reason": (
                    "GSTIN contains lowercase characters. "
                    "Possible OCR or extraction issue."
                ),
                "provided_value": gstin_raw,
                "normalized_value": gstin_for_validation,
                "flag": "GSTIN_CASE_MISMATCH"
            }

        # -----------------------------
        # CASE 5: VALID GSTIN
        # -----------------------------
        return self.pass_check({
            "reason": "Valid GSTIN",
            "gstin": gstin_raw,
            "flag": "VALID_GSTIN"
        })

    # ================= B7 =================
    def check_tax_split(self, invoice):
        logger.info("B7: Tax Split Check")

        cgst = invoice.get("cgst_rate", 0)
        sgst = invoice.get("sgst_rate", 0)
        igst = invoice.get("igst_rate", 0)

        logger.debug(f"CGST={cgst}, SGST={sgst}, IGST={igst}")

        if igst == 0 and cgst > 0 and sgst > 0:
            return self.pass_check("Valid intra-state") if abs(cgst - sgst) <= 0.01 else self.fail_check("Mismatch")

        if cgst == 0 and sgst == 0 and igst > 0:
            return self.pass_check("Valid inter-state")

        if cgst == sgst == igst == 0:
            return self.pass_check("No tax")

        return self.fail_check("Invalid tax structure")

    # ================= C1 =================
    def check_line_calc(self, invoice):
        logger.info("C1: Line Calc Check")

        items = invoice.get("items", [])

        for i, item in enumerate(items):
            qty = item.get("quantity", 1)
            rate = item.get("rate", 0)
            amt = item.get("amount", 0)

            expected = round(qty * rate, 2)

            logger.debug(f"Item {i+1}: expected={expected}, actual={amt}")

            if abs(expected - amt) > 1:
                return self.fail_check(f"Mismatch line {i+1}")

        return self.pass_check({
            "reason": f"All line items verified → quantity × rate matches amount for each item → no arithmetic mismatch found"
        })

    # ================= C2 =================
    def check_subtotal(self, invoice):
        logger.info("C2: Subtotal Check")

        items = invoice.get("items") or invoice.get("line_items", [])

        if not items:
            return self.fail_check("No items")

        subtotal = round(sum(i.get("amount", 0) for i in items), 2)
        declared = round(invoice.get("subtotal", subtotal), 2)
        tax = round(invoice.get("total_tax", 0), 2)
        total = round(invoice.get("total_amount", 0), 2)

        logger.debug(f"subtotal={subtotal}, declared={declared}, tax={tax}, total={total}")

        if abs(subtotal - declared) > 1:
            return self.fail_check("Subtotal mismatch")

        if abs((declared + tax) - total) > 1:
            return self.fail_check("Total mismatch")

        return self.pass_check("Totals correct")

    #     # ---------------- D1 ----------------
    def check_tds_applicability(self, invoice, master_data):
        """
        Production-grade TDS applicability engine.

        Decision layers:
          1. Identity resolution (GSTIN / PAN / vendor_type / country)
          2. Registry lookup — GSTIN/PAN for domestic; name/tax_id for foreign
          3. Vendor status validation
          4. Foreign vendor Section 195 path (registry-enriched when found)
          5. TDS section applicability (domestic)
          6. LDC (Lower Deduction Certificate) modifier
          7. 206AB penalty modifier
          8. Final structured decision output
        """

        vendor_info = invoice.get("vendor", {})

        # -------------------------------
        # 1. NORMALIZE IDENTIFIERS
        # -------------------------------
        gstin = str(vendor_info.get("gstin") or "").strip().upper() or None
        pan = str(vendor_info.get("pan") or "").strip().upper() or None

        inv_vendor_name = str(
            vendor_info.get("name") or vendor_info.get("legal_name") or ""
        ).strip().lower()
        inv_tax_id = str(vendor_info.get("tax_id") or "").strip().upper()

        # -------------------------------
        # 2. FOREIGN VENDOR DETECTION (multi-signal)
        #
        # Invoices often omit vendor_type entirely. We score all available
        # signals and treat the vendor as foreign if any strong signal fires.
        #
        # DEFINITIVE signals (any one is sufficient):
        #   • vendor.vendor_type == "FOREIGN_VENDOR"
        #   • vendor.country present and not "INDIA"
        #
        # SUPPORTING signals (used when definitive signals are absent):
        #   • no GSTIN AND no PAN AND tax_id has a known foreign prefix
        #
        # Registry re-confirmation (Step 3b) can further upgrade is_foreign
        # after lookup, covering cases where the invoice has no country field.
        # -------------------------------
        _country = (vendor_info.get("country") or "").strip().upper()
        _vendor_type_hint = (vendor_info.get("vendor_type") or "").strip().upper()

        # Extend this tuple as new jurisdictions are onboarded
        _FOREIGN_TAX_PREFIXES = (
            "US-EIN", "US-SSN", "VAT-", "ABN-", "ACN-",
            "GST-NZ", "BN-", "TIN-", "EIN-",
        )

        _definitive_foreign = (
            _vendor_type_hint == "FOREIGN_VENDOR"
            or (_country and _country != "INDIA")
        )

        _supporting_foreign = (
            not gstin
            and not pan
            and any(inv_tax_id.startswith(pfx) for pfx in _FOREIGN_TAX_PREFIXES)
        )

        is_foreign = _definitive_foreign or _supporting_foreign

        logger.debug(
            f"Foreign detection → vendor_type='{_vendor_type_hint}' | "
            f"country='{_country}' | gstin={gstin} | pan={pan} | "
            f"tax_id='{inv_tax_id}' | "
            f"definitive={_definitive_foreign} | supporting={_supporting_foreign} | "
            f"is_foreign={is_foreign}"
        )

        # -------------------------------
        # 3. RESOLVE VENDOR FROM REGISTRY
        # -------------------------------
        logger.debug(
            f"Vendor lookup — GSTIN: {gstin} | PAN: {pan} | "
            f"Name: {inv_vendor_name} | TaxID: {inv_tax_id}"
        )

        vendor = None
        registry = master_data.vendor_registry

        if isinstance(registry, dict) and "vendors" in registry:
            logger.debug("Registry is dict with 'vendors' key")
            vendor_list = registry["vendors"]
        elif isinstance(registry, list):
            logger.debug("Registry is direct list")
            vendor_list = registry
        else:
            logger.warning(f"Invalid registry structure: {type(registry)}")
            vendor_list = []

        for idx, v in enumerate(vendor_list):
            v_gstin = (v.get("gstin") or "").strip().upper()
            v_pan = (v.get("pan") or "").strip().upper()

            logger.debug(f"Checking vendor[{idx}] -> GSTIN: {v_gstin} | PAN: {v_pan}")

            if gstin and v_gstin == gstin:
                logger.debug("Match found using GSTIN")
                vendor = v
                break

            if pan and v_pan == pan:
                logger.debug("Match found using PAN")
                vendor = v
                break

        # -------------------------------
        # 3b. FALLBACK LOOKUP FOR FOREIGN VENDORS
        #     (GSTIN/PAN are null for foreign vendors — match by tax_id or legal name)
        # -------------------------------
        if not vendor and is_foreign:
            for idx, v in enumerate(vendor_list):
                v_tax_id = (v.get("tax_id") or "").strip().upper()
                v_name = (
                    v.get("legal_name") or v.get("trade_name") or ""
                ).strip().lower()

                logger.debug(
                    f"Foreign fallback vendor[{idx}] -> TaxID: {v_tax_id} | Name: {v_name}"
                )

                if inv_tax_id and v_tax_id and inv_tax_id == v_tax_id:
                    logger.debug("Foreign vendor match found using tax_id")
                    vendor = v
                    break

                if inv_vendor_name and v_name and inv_vendor_name == v_name:
                    logger.debug("Foreign vendor match found using legal_name")
                    vendor = v
                    break

        # -------------------------------
        # 3c. REGISTRY RE-CONFIRMATION OF is_foreign
        #     If the invoice had no country/vendor_type but the registry entry
        #     explicitly marks this vendor as FOREIGN_VENDOR, upgrade the flag.
        # -------------------------------
        if vendor and not is_foreign:
            reg_type = (vendor.get("vendor_type") or "").strip().upper()
            if reg_type == "FOREIGN_VENDOR":
                is_foreign = True
                logger.debug(
                    "is_foreign upgraded to True based on registry vendor_type"
                )

        # -------------------------------
        # 4. FOREIGN VENDOR PATH (Section 195)
        #    Use registry data when found; fall back to invoice-level data when not.
        # -------------------------------
        if is_foreign:
            flags = ["FOREIGN_VENDOR"]
            vendor_name = inv_vendor_name.title()

            if vendor:
                # Registry found — validate status first
                status = vendor.get("status", "").upper()
                if status in ("SUSPENDED", "CANCELLED"):
                    return self.fail_check({
                        "tds_applicable": None,
                        "vendor": vendor.get("legal_name"),
                        "status": status,
                        "reason": "Foreign vendor blocked due to compliance status",
                        "flags": ["FOREIGN_VENDOR", "VENDOR_BLOCKED"]
                    })

                # Enrich from registry
                rate = vendor.get("withholding_tax_rate", 10.0)
                vendor_name = vendor.get("legal_name") or vendor_name
                tax_treaty = vendor.get("tax_treaty_country")
                form_10f = vendor.get("form_10f_available", False)

                if tax_treaty:
                    flags.append(f"TAX_TREATY_{tax_treaty.upper()}")
                if form_10f:
                    flags.append("FORM_10F_AVAILABLE")
                else:
                    flags.append("FORM_10F_MISSING")

                logger.debug(
                    f"Foreign vendor found in registry: rate={rate}%, "
                    f"treaty={tax_treaty}, form_10f={form_10f}"
                )
            else:
                # Not in registry — use invoice-level hint, flag for manual review
                rate = vendor_info.get("withholding_tax_rate", 10.0)
                flags.append("VENDOR_NOT_IN_REGISTRY")
                flags.append("MANUAL_REVIEW_REQUIRED")
                logger.warning(
                    f"Foreign vendor not found in registry — "
                    f"Name: {inv_vendor_name}, TaxID: {inv_tax_id}. "
                    f"Defaulting to invoice-level rate={rate}%"
                )

            return self.pass_check({
                "tds_applicable": True,
                "section": "195",
                "vendor_type": "FOREIGN_VENDOR",
                "vendor_name": vendor_name,
                "rate": rate,
                "flags": flags,
                "reason": "Foreign vendor → Section 195 applicable",
                "confidence": 1.0 if vendor else 0.6,
            })

        # -------------------------------
        # 5. VENDOR NOT FOUND
        # -------------------------------
        if not vendor:
            logger.warning(f"Vendor not found — GSTIN={gstin}, PAN={pan}")
            return self.fail_check({
                "tds_applicable": None,
                "reason": f"Vendor not found (GSTIN={gstin}, PAN={pan})",
                "flags": ["VENDOR_NOT_FOUND"]
            })

        logger.debug(f"Vendor found: {vendor}")

        # -------------------------------
        # 6. VENDOR STATUS VALIDATION
        # -------------------------------
        status = vendor.get("status", "").upper()

        if status in ("SUSPENDED", "CANCELLED"):
            return self.fail_check({
                "tds_applicable": None,
                "vendor": vendor.get("legal_name"),
                "reason": f"Vendor {status} blocked due to compliance status",
                "flags": ["VENDOR_BLOCKED"]
            })

        # -------------------------------
        # 7. BASE TDS SECTION
        # -------------------------------
        tds_section = vendor.get("tds_section")

        if not tds_section:
            return self.pass_check({
                "tds_applicable": False,
                "vendor": vendor.get("legal_name"),
                "reason": "No TDS section mapped in registry",
                "flags": ["NO_TDS_APPLICABLE"],
                "confidence": 0.7
            })

        # -------------------------------
        # 8. BASE DECISION OBJECT
        # -------------------------------
        result = {
            "tds_applicable": True,
            "section": tds_section,
            "vendor": vendor.get("legal_name"),
            "vendor_type": vendor.get("vendor_type"),
            "flags": [],
            "rate": None,
            "reason_trace": []
        }

        result["reason_trace"].append(f"TDS section {tds_section} from registry")

        # -------------------------------
        # 9. LOWER DEDUCTION CERT (LDC)
        # -------------------------------
        ldc = vendor.get("lower_deduction_cert")

        if ldc:
            try:
                today = datetime.today()
                valid_from = datetime.strptime(ldc["valid_from"], "%Y-%m-%d")
                valid_to = datetime.strptime(ldc["valid_to"], "%Y-%m-%d")

                if valid_from <= today <= valid_to:
                    result["rate"] = ldc.get("reduced_rate")
                    result["flags"].append("LDC_VALID")
                    result["reason_trace"].append(
                        f"LDC valid → reduced rate {ldc.get('reduced_rate')}%"
                    )
                else:
                    result["reason_trace"].append("LDC expired → normal rate applies")

            except Exception:
                result["flags"].append("LDC_PARSE_ERROR")
                result["reason_trace"].append("LDC invalid date format")

        # -------------------------------
        # 10. 206AB PENALTY RULE
        # -------------------------------
        is_206ab = vendor.get("section_206ab_applicable", False)

        if is_206ab:
            result["flags"].append("206AB_APPLICABLE")
            result["reason_trace"].append(
                "206AB applicable → higher withholding required"
            )
            result["rate_multiplier"] = 2.0

        # -------------------------------
        # 11. FINAL DEFAULT RATE HANDLING
        # -------------------------------
        if not result.get("rate"):
            result["rate"] = "AS_PER_ACT"

        result["reason"] = f"TDS applicable under Section {tds_section}"

        return self.pass_check(result)

    # ================= D2 =================
    def check_tds_section(self, invoice, master_data=None):

        desc_parts = []

        # 🔹 invoice-level description
        inv_desc = invoice.get("description","")
        if isinstance(inv_desc, str):
            desc_parts.append(inv_desc)

        # 🔹 line-item descriptions
        for item in invoice.get("line_items", invoice.get("items", [])):
            val = item.get("description")
            if isinstance(val, str):
                desc_parts.append(val)

        safe_parts = []

        for part in desc_parts:
            if isinstance(part, str):
                safe_parts.append(part)
            else:
                safe_parts.append(str(part))

        text = " ".join(safe_parts).strip().lower()

        if not text:
            return self.fail_check({
                "tds_section": None,
                "confidence": 0.0,
                "reason": "No valid description available",
                "flags": ["MISSING_DESCRIPTION"]
            })

        keyword_map = {
            "194C": {
                "contract": 0.90, "construction": 0.90, "transport": 0.95,
                "freight": 0.95, "logistics": 0.85, "carriage": 0.85, "courier": 0.80,
            },
            "194J": {
                "consulting": 0.95, "professional": 0.90, "advisory": 0.90,
                "software": 0.80, "it service": 0.85, "technical": 0.85,
                "legal": 0.90, "audit": 0.90, "accountant": 0.85,
            },
            "194H": {"commission": 0.95, "brokerage": 0.95, "referral fee": 0.90},
            "194I": {"rent": 0.95, "lease": 0.95, "building rent": 0.90, "office space": 0.85},
            "194R": {"perquisite": 0.90, "benefit": 0.80, "incentive": 0.80, "gift": 0.75},
            "194S": {
                "virtual digital asset": 0.99, "cryptocurrency": 0.99,
                "crypto": 0.90, "nft": 0.95, "vda": 0.95,
            },
        }

        scores = {}
        evidence = {}

        for section, keywords in keyword_map.items():
            score = 0
            matched = []

            for kw, weight in keywords.items():
                if re.search(rf"\b{re.escape(kw)}\b", text):
                    score += weight
                    matched.append(kw)

            if score > 0:
                scores[section] = score
                evidence[section] = matched

        if not scores:
            return self.pass_check({
                "tds_section": None,
                "confidence": 0.0,
                "reason": "No TDS signals detected",
                "flags": ["NO_TDS_SIGNAL"]
            })

        best_section = max(scores, key=scores.get)

        confidence = round(scores[best_section] / sum(scores.values()), 2)

        return self.pass_check({
            "tds_section": best_section,
            "confidence": confidence,
            "scores": scores,
            "evidence": evidence,
            "reason": f"Detected {best_section} from invoice text"
        })

    # ================= E1 =================
    def check_po_tolerance(self, invoice):
        logger.info("E1: PO Tolerance")

        po = invoice.get("po_amount", 0)
        inv = invoice.get("total_amount", 0)

        if not po:
            return self.skip_check("there is No PO amount in the invoice")

        dev = abs(inv - po) / po
        logger.debug(f"Deviation: {dev}")

        return self.pass_check("Within tolerance") if dev <= 0.05 else self.fail_check("Exceeded")

    # ================= E3 =================
    def check_vendor_approved(self, invoice, master_data):
        logger.info("E3: Vendor Approval")

        gstin = (invoice.get("vendor", {}).get("gstin") or "").strip().upper()

        registry = master_data.vendor_registry
        vendor_list = registry.get("vendors") if isinstance(registry, dict) else registry

        for v in vendor_list or []:
            if gstin == (v.get("gstin") or "").strip().upper():
                return self.pass_check("Vendor approved")

        return self.fail_check("Vendor not approved")