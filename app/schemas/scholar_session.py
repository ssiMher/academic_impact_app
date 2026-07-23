"""Schemas for scholar analysis session inputs."""

from typing import List

from pydantic import BaseModel, Field


class ScholarSessionCreate(BaseModel):
    author_ref: str = Field(min_length=1)


class ScholarCitationExpansionRequest(BaseModel):
    publication_ids: List[int] = Field(default_factory=list)
