import json
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

import jsonschema
import pytest

from plural.tracing import (
    ActionStep,
    Event,
    Outcome,
    ParsedAction,
    RewardEvent,
    Trace,
    trace_json_schema,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATHS = (
    ROOT / "src/plural/schemas/trace.v2.json",
    ROOT / "schemas/trace.v2.json",
    ROOT / "docs/schemas/trace.v2.json",
)


def test_generated_trace_schema_is_current_and_packaged() -> None:
    subprocess.run(
        [sys.executable, "scripts/generate_trace_schema.py", "--check"],
        cwd=ROOT,
        check=True,
    )

    contents = [path.read_text(encoding="utf-8") for path in SCHEMA_PATHS]
    assert contents[0] == contents[1] == contents[2]
    packaged = files("plural.schemas").joinpath("trace.v2.json")
    assert packaged.is_file()
    assert trace_json_schema() == json.loads(contents[0])


def test_trace_schema_contains_variants_and_lineage_fields() -> None:
    schema = trace_json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)

    step_schema = schema["properties"]["steps"]["items"]
    step_refs = {variant["$ref"].rsplit("/", maxsplit=1)[-1] for variant in step_schema["oneOf"]}
    assert step_refs == {"ActionStep", "Event", "LLMCall", "Turn"}
    assert set(step_schema["discriminator"]["mapping"]) == {"action", "event", "llm", "turn"}
    assert {"trace_kind", "parent_trace_id", "episode_trace_id", "stop_reason"} <= set(
        schema["properties"]
    )
    assert {"turn_id", "turn", "reasoning", "started_at", "ended_at"} <= set(
        schema["$defs"]["Turn"]["properties"]
    )
    assert schema["properties"]["schema_version"]["const"] == "2.0.0"


def test_production_and_episode_dumps_validate_against_trace_schema() -> None:
    validator = jsonschema.Draft202012Validator(trace_json_schema())

    production = Trace(
        trace_kind="production",
        parent_trace_id="request-parent",
        episode_trace_id="episode-1",
        stop_reason="complete",
    )
    production.add_llm(request=None, response=None)
    production.add_action("lookup", {"query": "plural"}, result={"found": True})
    production.steps.append(Event(name="routed", data={"provider": "test"}))

    episode = Trace(
        trace_kind="episode",
        episode_trace_id="episode-1",
        environment="test",
        initial_state={"turn": 0},
        final_state={"turn": 1},
        outcome=Outcome(reward=1.0),
        terminated=True,
    )
    episode.add_turn(
        turn=0,
        observation={"turn": 0},
        parsed_action=[ParsedAction(name="lookup", arguments={"query": "plural"})],
        actions=[ActionStep(name="lookup", result={"found": True}, observation={"found": True})],
        reward_events=[RewardEvent(name="lookup", value=1.0)],
    )

    validator.validate(production.model_dump(mode="json"))
    validator.validate(episode.model_dump(mode="json"))

    invalid = production.model_dump(mode="json")
    invalid["schema_version"] = "1.0.0"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(invalid)


def test_legacy_traces_are_rejected() -> None:
    raw = (ROOT / "tests/fixtures/legacy_trace_v0_4.json").read_text(encoding="utf-8")
    with pytest.raises(Exception):
        Trace.model_validate_json(raw)

    current_a = Trace(trace_kind="episode")
    current_b = Trace(trace_kind="episode")
    current_a.add_turn()
    current_b.add_turn()
    assert current_a.turns()[0].turn_id != current_b.turns()[0].turn_id
