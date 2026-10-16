"""Pydantic models for configs/*.yaml. Every experiment variable lives here, so an ablation is
a config file, not a code change."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a typo in a config is an error, not a default


class Price(_Strict):
    """USD per million tokens, from the provider's current price list."""

    input_per_mtok: float
    output_per_mtok: float


class ModelConfig(_Strict):
    name: str = ""  # required at run time; set here or with --model
    base_url: str | None = None  # None: the provider's default; Ollama: http://localhost:11434/v1
    api_key_env: str = "LLM_API_KEY"
    temperature: float = 0.0
    max_output_tokens: int = 2048
    price: Price | None = None  # without it, cost is reported as unknown


class Budget(_Strict):
    max_tokens: int = 30_000
    max_seconds: float = 180.0
    max_cost_usd: float | None = None


class AgentConfig(_Strict):
    name: str = "default"
    feedback: Literal["L0", "L1", "L2", "L3"] = "L3"
    max_attempts: int = 3
    reflect: bool = False
    max_policy_blocks: int = 2
    budget: Budget = Budget()
    explain_failures: bool = True  # turn off in ablations so it doesn't skew token counts
    prompt_version: str = "v1"
    model: ModelConfig = ModelConfig()


def load_config(path: Path) -> AgentConfig:
    data = yaml.safe_load(Path(path).read_text()) or {}
    return AgentConfig.model_validate({"name": Path(path).stem, **data})
