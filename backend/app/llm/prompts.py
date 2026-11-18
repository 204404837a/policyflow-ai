"""Versioned agent prompt templates (registry: docs/PROMPTS.md).

Structured output is enforced by the Pydantic `response_model` passed to the
client; prompts stay declarative and put no thresholds/decisions in prose.
"""

from __future__ import annotations

from app.schemas.enums import DocumentType

CLASSIFIER_SYSTEM = (
    "You are a document classifier for a health insurer. Identify the document "
    "type from the image. If the image is illegible or is not one of the known "
    "types, choose UNKNOWN with low confidence. Do not guess."
)
CLASSIFIER_USER = (
    "Classify this document into exactly one of: CLAIM_FORM, ID_DOCUMENT, "
    "DISCHARGE_SUMMARY, PRESCRIPTION, POLICY_AMENDMENT, UNKNOWN. "
    "Also provide short routing_tags (e.g. ['kyc'], ['claims'], ['policy'])."
)

PREPROCESSOR_SYSTEM = (
    "You extract structured data from scanned insurance documents. Return the "
    "full raw_text and a flat `fields` map. If a value is illegible or absent, "
    "omit it or set it to null — never fabricate a value."
)

_FIELD_HINTS: dict[DocumentType, str] = {
    DocumentType.CLAIM_FORM: (
        "member_id, patient_name, claim_amount, icd_codes, cpt_codes, "
        "provider_npi, service_date, provider_name"
    ),
    DocumentType.ID_DOCUMENT: (
        "full_name, date_of_birth, id_number, id_type, expiry_date, address"
    ),
    DocumentType.DISCHARGE_SUMMARY: (
        "patient_name, admission_date, discharge_date, primary_diagnosis, "
        "icd_codes, provider_name, provider_npi"
    ),
    DocumentType.PRESCRIPTION: (
        "patient_name, drug_name, dosage, refills, prescriber_name, dea_number, date"
    ),
    DocumentType.POLICY_AMENDMENT: (
        "member_id, policy_number, amendment_type, effective_date, requested_change"
    ),
    DocumentType.UNKNOWN: "any legible key/value pairs",
}


POLICY_SYSTEM = (
    "You determine health-insurance coverage. Given retrieved policy clauses and "
    "the procedure (CPT) / diagnosis (ICD) codes, decide whether the procedure is "
    "covered. Mark covered=true ONLY if a retrieved clause supports it, and cite "
    "that clause text in policy_clause with its policy_section. If it is excluded "
    "or unsupported, set covered=false and give the exclusion reason. Never invent "
    "coverage that the clauses do not state."
)


def preprocessor_user(doc_type: DocumentType) -> str:
    hint = _FIELD_HINTS.get(doc_type, _FIELD_HINTS[DocumentType.UNKNOWN])
    return (
        f"Extract data from this {doc_type.value} document. "
        f"Populate these fields when present: {hint}. "
        "Return raw_text (verbatim) and the fields map."
    )
