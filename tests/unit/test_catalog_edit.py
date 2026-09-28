import json
from pathlib import Path
from typing import Any

import pytest

from plural.catalog.edit import main, validate_document
from plural.catalog.models import ModelCatalog, spec_from_payload, spec_to_payload
from plural.catalog.sync import DATA_PATH, load_catalog

ENTRY: dict[str, Any] = {
    "id": "acme/widget-1",
    "name": "Acme: Widget 1",
    "description": "A small model for tests.",
    "created": "2026-09-01",
    "context_length": 128000,
    "max_output_tokens": 8192,
    "pricing": {"prompt": "0.000001", "completion": "0.000002", "cache_read": "0.0000001"},
    "architecture": {
        "modality": "text->text",
        "input_modalities": ["text"],
        "output_modalities": ["text"],
    },
    "supported_parameters": ["max_tokens", "tools"],
    "links": {"homepage": "https://acme.test/widget"},
    "endpoints": [
        {
            "provider": "fireworks",
            "region": "us",
            "upstream_id": "accounts/fireworks/models/widget-1",
            "pricing": {"prompt": "0.000001", "completion": "0.000002"},
            "quantization": "fp8",
        }
    ],
}


@pytest.fixture
def catalog(tmp_path: Path) -> Path:
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"updated_at": None, "models": []}), encoding="utf-8")
    return path


def run(path: Path, *argv: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any]]:
    code = main(["--path", str(path), *argv])
    return code, json.loads(capsys.readouterr().out)


def test_the_bundled_catalog_validates() -> None:
    issues = validate_document(load_catalog(DATA_PATH))
    assert [issue for issue in issues if issue.level == "error"] == []


def test_add_set_and_endpoint_commands_round_trip(
    catalog: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    entry_file = tmp_path / "entry.json"
    entry_file.write_text(json.dumps(ENTRY), encoding="utf-8")
    code, result = run(catalog, "add", "--file", str(entry_file), capsys=capsys)
    assert code == 0 and result["changed"] == ["acme/widget-1"]

    code, result = run(
        catalog,
        "set",
        "acme/widget-1",
        "pricing.prompt=0.5/M",
        "supported_parameters=max_tokens,tools,temperature",
        "knowledge_cutoff=2026-03",
        capsys=capsys,
    )
    assert code == 0
    written = result["entries"][0]
    assert written["pricing"]["prompt"] == "0.0000005"
    assert written["supported_parameters"] == ["max_tokens", "tools", "temperature"]

    code, result = run(
        catalog,
        "endpoint",
        "add",
        "acme/widget-1",
        "--provider",
        "baseten",
        "--upstream-id",
        "widget-1",
        "--prompt",
        "0.8/M",
        "--completion",
        "2/M",
        "--context-length",
        "64000",
        capsys=capsys,
    )
    assert code == 0
    code, result = run(
        catalog, "endpoint", "set", "acme/widget-1", "baseten", "quantization=fp4", capsys=capsys
    )
    assert code == 0

    spec = ModelCatalog(catalog).require("acme/widget-1")
    assert spec.description == "A small model for tests."
    assert spec.knowledge_cutoff == "2026-03"
    assert spec.max_output_tokens == 8192
    assert spec.links == {"homepage": "https://acme.test/widget"}
    assert spec.pricing is not None and spec.pricing.cache_read == pytest.approx(1e-7)
    baseten = next(e for e in spec.endpoints if e.provider == "baseten")
    assert baseten.context_length == 64000 and baseten.quantization == "fp4"
    assert baseten.pricing is not None and baseten.pricing.completion == pytest.approx(2e-6)

    code, _ = run(catalog, "endpoint", "remove", "acme/widget-1", "baseten@us", capsys=capsys)
    assert code == 0
    assert [e.provider for e in ModelCatalog(catalog).require("acme/widget-1").endpoints] == [
        "fireworks"
    ]


def test_an_edit_that_breaks_the_catalog_is_not_written(
    catalog: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    entry_file = tmp_path / "entry.json"
    entry_file.write_text(json.dumps(ENTRY), encoding="utf-8")
    run(catalog, "add", "--file", str(entry_file), capsys=capsys)
    before = catalog.read_text(encoding="utf-8")

    for argv in (
        ("set", "acme/widget-1", "prcing.prompt=1/M"),
        ("set", "acme/widget-1", "max_output_tokens=999999"),
        ("set", "acme/widget-1", "links.homepage=http://insecure.test"),
        ("endpoint", "add", "acme/widget-1", "--provider", "nowhere", "--upstream-id", "x"),
        ("endpoint", "add", "acme/widget-1", "--provider", "fireworks", "--upstream-id", "x"),
    ):
        code, result = run(catalog, *argv, capsys=capsys)
        assert code == 1, argv
        assert result["ok"] is False and result["errors"], argv
    assert catalog.read_text(encoding="utf-8") == before


def test_validate_reports_incomplete_cards_as_warnings(
    catalog: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bare = {key: ENTRY[key] for key in ("id", "name", "context_length", "endpoints")}
    catalog.write_text(json.dumps({"models": [bare]}), encoding="utf-8")
    code, result = run(catalog, "validate", capsys=capsys)
    assert code == 0
    assert {w["path"] for w in result["warnings"]} >= {"description", "created"}
    code, _ = run(catalog, "validate", "--strict", capsys=capsys)
    assert code == 1


def test_card_fields_survive_a_load_and_dump() -> None:
    spec = spec_from_payload(ENTRY)
    assert spec_from_payload(spec_to_payload(spec)) == spec


def test_schema_describes_every_card_field(
    catalog: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, result = run(catalog, "schema", capsys=capsys)
    assert code == 0
    properties = result["schema"]["properties"]
    assert {"description", "created", "max_output_tokens", "links", "endpoints"} <= set(properties)
