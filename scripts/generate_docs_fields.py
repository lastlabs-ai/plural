"""Generate the docs field catalog from current executable package models."""

import json
import sys
from pathlib import Path

from plural import Agent, Benchmark, Harness, Task
from plural.environments.definition import EnvironmentDefinition
from plural.project import public_schema
from plural.verifiers import AgentVerifier, DeterministicVerifier, HumanVerifier

root = Path(__file__).resolve().parents[1] / "docs"
models = [
    ("Environment", EnvironmentDefinition),
    ("Harness", Harness),
    ("Task", Task),
    ("DeterministicVerifier", DeterministicVerifier),
    ("AgentVerifier", AgentVerifier),
    ("HumanVerifier", HumanVerifier),
    ("Agent", Agent),
    ("Benchmark", Benchmark),
]
schemas = {}
nested = {}
DISPLAY_NAMES = {
    "EnvironmentResource": "Resource",
    "EnvironmentRuntime": "Runtime",
    "NativeAction": "Action",
    "RewarderDefinition": "Rewarder",
    "SecretReference": "Secret",
}
for name, model in models:
    schema = public_schema(model)
    schema["title"] = name
    schemas[name] = schema
    nested.update(schema.get("$defs", {}))
for name in schemas:
    nested.pop(name, None)
body = [
    "---",
    "route: /docs/reference/fields",
    'title: "Field catalog"',
    "order: 205",
    'description: "Post-resolution constructor schemas generated from the current Plural models."',
    "audience: all",
    "nav: false",
    "nav_group: Reference",
    "---",
    "# Field catalog",
    "",
    "Use this catalog after the conceptual guides. It is generated from the "
    "post-resolution Pydantic constructor models, including nested types. Required "
    "fields have no usable default. Custom cross-field validators also apply.",
    "",
    "These schemas describe resolved object values, not Python references, source "
    "materialization, runtime capability checks, or side effects. The imperative "
    "public `Job` constructor is omitted because it is not a Pydantic model; use "
    "the [Jobs guide](../running/jobs.md) and [Python SDK guide](../sdk/evaluation.md) "
    "for its source, Agent, mode, attempt, concurrency, retry, planning, and run "
    "arguments. Methods and Client request types belong in the API reference.",
    "",
    "For Python-authored Environments, `runtime` is a required Environment parameter. "
    "The resolved schema below lists it as optional because it also describes stored definitions; "
    "use the [Environments guide](../project/environments.md) when creating an Environment.",
    "",
    "[Download the complete schemas](../assets/project-schemas.json).",
    "",
    "## Find a contract",
    "",
]
for name in [*schemas, *sorted(nested)]:
    shown = DISPLAY_NAMES.get(name, name)
    body.append(f"- [{shown}](#{shown.lower()})")


def _typ(p):
    if "$ref" in p:
        name = p["$ref"].split("/")[-1]
        return DISPLAY_NAMES.get(name, name)
    if "anyOf" in p or "oneOf" in p:
        return " | ".join(_typ(x) for x in p.get("anyOf", p.get("oneOf", [])))
    if "const" in p:
        return json.dumps(p["const"])
    if "enum" in p:
        return " | ".join(json.dumps(v) for v in p["enum"])
    if p.get("type") == "array":
        return "array of " + _typ(p.get("items", {}))
    return str(p.get("type", "JSON value"))


for name, schema in [*schemas.items(), *sorted(nested.items())]:
    shown = DISPLAY_NAMES.get(name, name)
    body.extend(["", f"## {shown}", "", schema.get("description", "").split("\n\n")[0], ""])
    props = schema.get("properties", {})
    if not props:
        body.extend([f"Allowed values: `{_typ(schema)}`.", ""])
        continue
    required = set(schema.get("required", []))
    for field, p in props.items():
        state = "required" if field in required else "optional"
        default = (
            " Default: `" + json.dumps(p["default"], ensure_ascii=False) + "`."
            if "default" in p
            else ""
        )
        rules = {
            k: v
            for k, v in p.items()
            if k
            in [
                "minimum",
                "maximum",
                "exclusiveMinimum",
                "exclusiveMaximum",
                "minLength",
                "maxLength",
                "minItems",
                "maxItems",
                "pattern",
                "uniqueItems",
                "format",
            ]
        }
        constraint = (
            " Constraints: `" + json.dumps(rules, ensure_ascii=False) + "`." if rules else ""
        )
        desc = " " + p["description"].replace("\n", " ") if p.get("description") else ""
        body.append(f"- **`{field}`** — `{_typ(p)}`; {state}.{default}{constraint}{desc}")
fields_path = root / "reference/fields.md"
fields_content = "\n".join(body) + "\n"
(root / "assets").mkdir(exist_ok=True)
schemas_path = root / "assets/project-schemas.json"
schemas_content = json.dumps(schemas, indent=2) + "\n"
if "--check" in sys.argv:
    if fields_path.read_text(encoding="utf-8") != fields_content:
        raise SystemExit("Generated field documentation is stale.")
    if schemas_path.read_text(encoding="utf-8") != schemas_content:
        raise SystemExit("Generated documentation schemas are stale.")
else:
    fields_path.write_text(fields_content, encoding="utf-8")
    schemas_path.write_text(schemas_content, encoding="utf-8")
print(f"Generated {len(schemas) + len(nested)} contracts.")
