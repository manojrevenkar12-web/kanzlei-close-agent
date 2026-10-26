"""The engine never sees the answer key, and the model reader never sees what it must not."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from kanzlei.config import llm_config
from kanzlei.engine.llm import ModelReader

SRC = Path(__file__).resolve().parents[1] / "src" / "kanzlei"


def test_engine_never_imports_the_simulation() -> None:
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                assert not n.startswith("kanzlei_sim"), f"{path.name} imports {n}"
                assert n not in ("sklearn", "scipy"), f"{path.name} imports {n}: training stays out of the engine"


def test_model_reader_redacts_and_is_checked() -> None:
    sent: list[dict[str, Any]] = []

    def fake(body: dict[str, Any]) -> dict[str, Any]:
        sent.append(body)
        return {"content": [{"type": "text", "text": "telecom"}]}

    reader = ModelReader(llm_config(), transport=fake)
    assert reader.suggest_family("Lastschrift DE89370400440532013000 Funknetz AG, info@funk.example") == "telecom"
    assert "DE89370400440532013000" not in sent[0]["messages"][0]["content"]
    assert "info@funk.example" not in sent[0]["messages"][0]["content"]

    def nonsense(_: dict[str, Any]) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": "revenue_and_more"}]}

    assert ModelReader(llm_config(), transport=nonsense).suggest_family("x") is None


def test_model_invoice_must_add_up() -> None:
    def answer(text: str) -> Any:
        return lambda _: {"content": [{"type": "text", "text": text}]}

    good = '{"seller": "Funk AG", "invoice_no": "7", "issue_date": "2026-09-01", "gross": "119,00", "taxes": [{"rate": 19, "base": "100,00", "tax": "19,00"}], "lines": ["Tarif"]}'
    bad = '{"seller": "Funk AG", "gross": "120,00", "taxes": [{"rate": 19, "base": "100,00", "tax": "19,00"}]}'
    assert ModelReader(llm_config(), transport=answer(good)).read_invoice("...", expected_gross=11900) is not None
    assert ModelReader(llm_config(), transport=answer(good)).read_invoice("...", expected_gross=12000) is None
    assert ModelReader(llm_config(), transport=answer(bad)).read_invoice("...") is None
