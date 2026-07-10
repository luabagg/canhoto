from __future__ import annotations

import json
import os
from pathlib import Path

from finance_ingest.models import AppConfig

DEFAULT_DATA_DIR = Path(
    os.environ.get("FINANCE_DATA_DIR", Path.home() / ".finance-ingest")
)


def data_dir() -> Path:
    path = Path(os.environ.get("FINANCE_DATA_DIR", DEFAULT_DATA_DIR))
    path.mkdir(parents=True, exist_ok=True)
    (path / "raw").mkdir(exist_ok=True)
    (path / "exports").mkdir(exist_ok=True)
    return path


def config_path() -> Path:
    return data_dir() / "config.json"


def db_path() -> Path:
    return data_dir() / "finance.db"


def load_config() -> AppConfig:
    path = config_path()
    if not path.exists():
        cfg = AppConfig(data_dir=str(data_dir()))
        save_config(cfg)
        return cfg
    return AppConfig.model_validate_json(path.read_text(encoding="utf-8"))


def save_config(cfg: AppConfig) -> AppConfig:
    path = config_path()
    path.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    return cfg


def update_config(**kwargs) -> AppConfig:
    cfg = load_config()
    data = cfg.model_dump()
    data.update({k: v for k, v in kwargs.items() if v is not None})
    cfg = AppConfig.model_validate(data)
    return save_config(cfg)


def dump_json(obj) -> str:
    if hasattr(obj, "model_dump"):
        return json.dumps(obj.model_dump(mode="json"), indent=2, ensure_ascii=False)
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)
