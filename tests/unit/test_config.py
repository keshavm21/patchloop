from pathlib import Path

import pytest
from pydantic import ValidationError

from patchloop.config import load_config

CONFIGS = Path(__file__).resolve().parents[2] / "configs"


@pytest.mark.parametrize("path", sorted(CONFIGS.glob("*.yaml")), ids=lambda p: p.stem)
def test_configs_load(path):
    cfg = load_config(path)
    assert cfg.name == path.stem
    # Ablation configs keep the failure summary off, so it doesn't skew token counts.
    assert cfg.explain_failures is False


def test_ablation_matrix():
    got = {p.stem: load_config(p) for p in CONFIGS.glob("*.yaml")}
    assert (got["single_shot"].feedback, got["single_shot"].max_attempts) == ("L0", 1)
    assert [got[n].feedback for n in ("binary", "errors", "full")] == ["L1", "L2", "L3"]
    assert got["full_reflect"].reflect and not got["full"].reflect


def test_typos_are_errors(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("feedbak: L3\n")
    with pytest.raises(ValidationError):
        load_config(path)
