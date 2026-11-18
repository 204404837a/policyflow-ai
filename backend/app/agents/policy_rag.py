"""Policy-RAG agent — retrieve clauses, then judge coverage (reasoning LLM).

Guardrail G3: covered=true must cite a retrieved clause; enforced here.
"""

from __future__ import annotations

from typing import Protocol

from app.core.constants import POLICY_NO_CLAUSE_CONFIDENCE, REASONING_ALIAS
from app.llm.client import LLMClient
from app.llm.prompts import POLICY_SYSTEM
from app.schemas.agents import PolicyOutput
from app.services.rag_service import Clause


class SupportsRetrieve(Protocol):
    async def retrieve(self, cpt: list[str], icd: list[str], text: str) -> list[Clause]: ...


class PolicyAgent:
    def __init__(self, rag: SupportsRetrieve, client: LLMClient) -> None:
        self._rag = rag
        self._client = client

    async def check(
        self,
        cpt: list[str],
        icd: list[str],
        procedure_text: str,
        *,
        case_id: str | None = None,
    ) -> PolicyOutput:
        clauses = await self._rag.retrieve(cpt, icd, procedure_text)
        if not clauses:
            return PolicyOutput(
                covered=False,
                exclusions=["no matching policy clause found"],
                confidence=POLICY_NO_CLAUSE_CONFIDENCE,
            )

        context = "\n\n".join(f"[{c.section}] {c.text}" for c in clauses)
        user = (
            f"Procedure CPT: {cpt}\nDiagnosis ICD: {icd}\nProcedure: {procedure_text}\n\n"
            f"Policy clauses:\n{context}"
        )
        result = await self._client.chat(
            REASONING_ALIAS,
            system=POLICY_SYSTEM,
            user=user,
            response_model=PolicyOutput,
            case_id=case_id,
        )
        assert isinstance(result, PolicyOutput)

        # Guardrail G3: covered requires a cited clause.
        if result.covered and not (result.policy_clause and result.policy_clause.strip()):
            result = result.model_copy(
                update={
                    "policy_clause": clauses[0].text,
                    "policy_section": clauses[0].section,
                }
            )
        return result
