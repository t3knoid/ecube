import logging

from fastapi import HTTPException, status
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

logger = logging.getLogger(__name__)

engine = None
SessionLocal = sessionmaker(autocommit=False, autoflush=False)
Base = declarative_base()


def _initialize_engine_from_settings() -> None:
    """Initialise SQLAlchemy engine only when DATABASE_URL is configured."""
    global engine

    database_url = (settings.database_url or "").strip()
    if not database_url:
        engine = None
        SessionLocal.configure(bind=None)
        return

    try:
        engine = create_engine(
            database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_pool_max_overflow,
            pool_recycle=settings.db_pool_recycle_seconds,
        )
        SessionLocal.configure(bind=engine)
    except Exception:
        engine = None
        SessionLocal.configure(bind=None)
        logger.exception("Failed to initialize database engine from DATABASE_URL")


def is_database_configured() -> bool:
    """Return True when DATABASE_URL has been configured and engine is active."""
    bind = getattr(SessionLocal, "kw", {}).get("bind")
    return bind is not None


_initialize_engine_from_settings()


def get_db():
    if not is_database_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not configured yet. Complete setup first.",
        )

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
