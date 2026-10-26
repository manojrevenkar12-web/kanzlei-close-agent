"""Settings from the environment and the YAML files in config/ (thresholds never live in code)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KANZLEI_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://kanzlei_app:kanzlei_app@localhost:5432/kanzlei"
    admin_database_url: str = "postgresql://postgres:postgres@localhost:5432/kanzlei"
    app_db_password: str = "kanzlei_app"
    token_secret: str = "dev-only-secret-change-me"
    config_dir: Path = ROOT / "config"
    reports_dir: Path = ROOT / "reports"
    storage_url: str = "file://" + str(ROOT / "var" / "documents")
    public_url: str = "http://localhost:5173"
    cors_origin: str = "http://localhost:5173"
    demo_mode: bool = False
    metrics_token: str | None = None
    # Production sign-in through the load balancer's OIDC authentication (see api/alb_oidc.py).
    alb_arn: str | None = None
    aws_region: str = "eu-central-1"


def _yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@lru_cache
def settings() -> Settings:
    return Settings()


def config_dir() -> Path:
    return Path(os.environ.get("KANZLEI_CONFIG_DIR", str(settings().config_dir)))


@dataclass(frozen=True)
class Family:
    code: str
    label: str
    side: str
    receipt: bool
    tax: str
    risk: int
    recurring_ok: bool


@lru_cache
def families() -> dict[str, Family]:
    d = _yaml(config_dir() / "families.yaml")["families"]
    return {
        k: Family(k, v["label"], v["side"], bool(v["receipt"]), v["tax"], int(v["risk"]), bool(v.get("recurring_ok")))
        for k, v in d.items()
    }


@dataclass(frozen=True)
class TaxConfig:
    rates: dict[str, int]
    kleinbetrag_gross_cents: int
    small_net_cents: int
    gwg_net_cents: int
    meals_deductible_share: float
    skonto_percent: tuple[int, ...]
    eu_countries: frozenset[str]
    due_day: int
    dauerfrist_extra_months: int
    quarterly_threshold_cents: int
    kennzahlen: dict[str, dict[str, Any]]
    kennzahl_labels: dict[str, str]
    pflichtangaben_full: tuple[str, ...]
    pflichtangaben_klein: tuple[str, ...]
    reverse_charge_note: str


@lru_cache
def tax_config() -> TaxConfig:
    d = _yaml(config_dir() / "tax.yaml")
    return TaxConfig(
        rates={k: int(v) for k, v in d["rates"].items()},
        kleinbetrag_gross_cents=int(d["kleinbetrag_gross_cents"]),
        small_net_cents=int(d["equipment"]["small_net_cents"]),
        gwg_net_cents=int(d["equipment"]["gwg_net_cents"]),
        meals_deductible_share=float(d["meals_deductible_share"]),
        skonto_percent=tuple(int(x) for x in d["skonto_percent"]),
        eu_countries=frozenset(d["eu_countries"]),
        due_day=int(d["ustva"]["due_day"]),
        dauerfrist_extra_months=int(d["ustva"]["dauerfrist_extra_months"]),
        quarterly_threshold_cents=int(d["ustva"]["quarterly_threshold_cents"]),
        kennzahlen={str(k): v for k, v in d["kennzahlen"].items()},
        kennzahl_labels={str(k): str(v) for k, v in d["kennzahl_labels"].items()},
        pflichtangaben_full=tuple(d["pflichtangaben"]["full"]),
        pflichtangaben_klein=tuple(d["pflichtangaben"]["kleinbetrag"]),
        reverse_charge_note=d["pflichtangaben"]["reverse_charge_note"],
    )


@dataclass(frozen=True)
class CloseConfig:
    window_days_before: int
    window_days_after: int
    max_combination: int
    min_match_score: float
    memory_min_uses: int
    memory_dominant_share: float
    recurring_min_months: int
    recurring_amount_tolerance: float
    decision_model_file: str
    never_auto_new_counterparty: bool
    new_counterparty_min_classifier_p: float
    memory_overruled_by_classifier_p: float
    memory_overruled_if_memory_family_p_below: float
    ask_private_min_p: float
    opos_paid_within_days: int
    answer_days: int
    plaus_months: int
    plaus_min_months: int
    plaus_mad_k: float
    plaus_min_abs_cents: int
    effort: dict[str, float] = field(default_factory=dict)


@lru_cache
def close_config() -> CloseConfig:
    d = _yaml(config_dir() / "close.yaml")
    return CloseConfig(
        window_days_before=int(d["matching"]["window_days_before"]),
        window_days_after=int(d["matching"]["window_days_after"]),
        max_combination=int(d["matching"]["max_combination"]),
        min_match_score=float(d["matching"]["min_score"]),
        memory_min_uses=int(d["memory"]["min_uses"]),
        memory_dominant_share=float(d["memory"]["dominant_share"]),
        recurring_min_months=int(d["recurring"]["min_months"]),
        recurring_amount_tolerance=float(d["recurring"]["amount_tolerance"]),
        decision_model_file=str(d["decision"]["model_file"]),
        never_auto_new_counterparty=bool(d["decision"]["never_auto_new_counterparty"]),
        new_counterparty_min_classifier_p=float(d["decision"]["new_counterparty_min_classifier_p"]),
        memory_overruled_by_classifier_p=float(d["decision"]["memory_overruled_by_classifier_p"]),
        memory_overruled_if_memory_family_p_below=float(d["decision"]["memory_overruled_if_memory_family_p_below"]),
        ask_private_min_p=float(d["decision"]["ask_private_min_p"]),
        opos_paid_within_days=int(d["opos"]["paid_within_days"]),
        answer_days=int(d["queries"]["answer_days"]),
        plaus_months=int(d["plausibility"]["months"]),
        plaus_min_months=int(d["plausibility"]["min_months"]),
        plaus_mad_k=float(d["plausibility"]["mad_k"]),
        plaus_min_abs_cents=int(d["plausibility"]["min_abs_cents"]),
        effort={k: float(v) for k, v in d["effort_minutes"].items()},
    )


@lru_cache
def lexicon() -> dict[str, tuple[str, ...]]:
    d = _yaml(config_dir() / "lexicon.yaml")
    return {k: tuple(str(w).lower() for w in v) for k, v in d.items()}


@dataclass(frozen=True)
class LlmConfig:
    provider: str
    model: str
    enabled_if_env: str
    base_url_env: str
    uses: dict[str, bool]
    min_classifier_confidence: float
    redact: tuple[str, ...]
    max_tokens: int
    timeout_seconds: float

    @property
    def configured(self) -> bool:
        return bool(os.environ.get(self.enabled_if_env))


@lru_cache
def llm_config() -> LlmConfig:
    d = _yaml(config_dir() / "llm.yaml")
    return LlmConfig(
        provider=d["provider"],
        model=d["model"],
        enabled_if_env=d["enabled_if_env"],
        base_url_env=d["base_url_env"],
        uses={k: bool(v) for k, v in d["uses"].items()},
        min_classifier_confidence=float(d["min_classifier_confidence"]),
        redact=tuple(d["redact"]),
        max_tokens=int(d["max_tokens"]),
        timeout_seconds=float(d["timeout_seconds"]),
    )


def clear_caches() -> None:
    for f in (settings, families, tax_config, close_config, lexicon, llm_config):
        f.cache_clear()
    from kanzlei.domain.chart import chart

    chart.cache_clear()
