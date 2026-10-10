"""Utility condivise: percorsi, configurazione, log, I/O JSON."""
from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FUND_DIR = DATA / "fundamentals"
SITE_DATA = ROOT / "docs" / "data"

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("stockpicking")


def log_to_file(path: Path) -> None:
    """Copia il log in un file (salvato nel repository: i log di GitHub non sono sempre leggibili)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    h = logging.FileHandler(path, mode="a", encoding="utf-8")
    h.setLevel(logging.INFO)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(h)


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _clean(obj):
    """Rende serializzabile in JSON (NaN/inf -> None, numpy -> python)."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if hasattr(obj, "item") and not isinstance(obj, (str, bytes)):
        try:
            obj = obj.item()
        except Exception:
            pass
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return round(obj, 6)
    return obj


def write_json(path: Path, obj, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        if compact:
            json.dump(_clean(obj), f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(_clean(obj), f, ensure_ascii=False, indent=1)
    tmp.replace(path)


def read_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def safe_name(ticker: str) -> str:
    return ticker.replace("/", "_").replace("^", "_")
