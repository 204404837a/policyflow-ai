"""Claims agent — normalize + schema-validate the claim form's extracted fields.

The alias-tolerant, self-coercing `ClaimsExtractedFields` model does the parsing
(one `model_validate`); this agent applies the business format rules (ICD-10 /
CPT / NPI / amount / date). Missing or malformed required fields →
schema_valid=False (→ REJECT downstream).
"""

from __future__ import annotations

import re

from app.core.constants import CLAIMS_CONFIDENCE_BASE
from app.schemas.agents import ClaimsExtractedFields, ClaimsOutput

_ICD = re.compile(r"^[A-Z][0-9]{2}(\.[0-9A-Z]{1,4})?$")
_CPT = re.compile(r"^\d{5}$")
_NPI = re.compile(r"^\d{10}$")
_TOTAL_CHECKS = 6  # icd, cpt, npi, amount, date, provider


class ClaimsAgent:
    async def run(self, fields: dict, *, case_id: str | None = None) -> ClaimsOutput:
        ef = ClaimsExtractedFields.model_validate(fields)

        errors: list[str] = []
        if not ef.icd_codes:
            errors.append("missing ICD-10 code")
        elif not all(_ICD.match(c) for c in ef.icd_codes):
            errors.append("invalid ICD-10 format")
        if not ef.cpt_codes:
            errors.append("missing CPT code")
        elif not all(_CPT.match(c) for c in ef.cpt_codes):
            errors.append("invalid CPT format")
        if not ef.provider_npi:
            errors.append("missing provider NPI")
        elif not _NPI.match(ef.provider_npi):
            errors.append("invalid NPI format")
        if ef.claim_amount is None or ef.claim_amount <= 0:
            errors.append("missing/invalid claim amount")
        if not ef.service_date:
            errors.append("missing service date")

        passing = (_TOTAL_CHECKS - len(errors)) / _TOTAL_CHECKS
        confidence = round(CLAIMS_CONFIDENCE_BASE + (1 - CLAIMS_CONFIDENCE_BASE) * passing, 3)
        return ClaimsOutput(
            extracted_fields=ef,
            schema_valid=not errors,
            validation_errors=errors,
            confidence=confidence,
        )
