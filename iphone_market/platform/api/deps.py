from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from ..ingest import CollectionPipeline
from ..search import ListingSearchIndex


def get_session(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_pipeline(request: Request) -> CollectionPipeline:
    return request.app.state.pipeline


def get_search_index(request: Request) -> ListingSearchIndex:
    return request.app.state.search_index
