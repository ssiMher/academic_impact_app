"""Compatibility wrapper for report-oriented impact card generation."""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.highlight_card_service import HighlightCardService


class ImpactCardService(HighlightCardService):
    """Thin wrapper over HighlightCardService for report/PPT workflows."""


def get_impact_card_service(db: Session = Depends(get_db)) -> ImpactCardService:
    return ImpactCardService(db)
