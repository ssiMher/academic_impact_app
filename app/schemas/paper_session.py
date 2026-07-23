"""Schemas for paper analysis session workflows."""

from pydantic import BaseModel, Field


class PaperSessionCreate(BaseModel):
    query_text: str = Field(min_length=1)
    query_kind: str = "title"
