"""Schemas for evidence scoring and display helpers."""

from pydantic import BaseModel


class EvidenceScore(BaseModel):
    score: float
    evidence_strength: str
    rationale: str
