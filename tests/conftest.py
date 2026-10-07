from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_global_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "global-config"))
