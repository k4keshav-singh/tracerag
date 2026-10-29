"""Entry point: ``python -m app.main`` or ``uvicorn app.main:app``."""

from __future__ import annotations

import logging

import uvicorn

from .api import create_app
from .config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)

app = create_app()


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
    _ = settings


if __name__ == "__main__":
    main()
