from __future__ import annotations

import os
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DIST_DIR = FRONTEND_DIR / "dist"
STATIC_DIR = FRONTEND_DIR / "static"
DATA_DIR = PROJECT_ROOT / "data"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
TESTS_DIR = PROJECT_ROOT / "tests"
CHROMA_DIR = PROJECT_ROOT / "chroma_db"

DUCKDB_PATH = DATA_DIR / "data.duckdb"
STATE_DB_PATH = DATA_DIR / "app_state.db"
CHECKPOINT_DB_PATH = DATA_DIR / "checkpoints.db"


def ensure_directories() -> None:
    for path in (FRONTEND_DIR, STATIC_DIR, DATA_DIR, ARTIFACTS_DIR, TESTS_DIR, CHROMA_DIR):
        path.mkdir(parents=True, exist_ok=True)


def artifact_relpath(path: str | os.PathLike[str]) -> str:
    return str(Path(path).resolve().relative_to(ARTIFACTS_DIR.resolve())).replace("\\", "/")


def artifact_path(*parts: str) -> Path:
    return ARTIFACTS_DIR.joinpath(*parts)
