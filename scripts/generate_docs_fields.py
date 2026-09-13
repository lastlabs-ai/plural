"""Generate the docs field catalog from current executable package models."""

import json
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
    'description: "Every authoring and execution field, generated from the current Plural models."',
    "audience: all",
    "nav: false",
    "---",
    "# Field catalog",
    "",
    "Use this catalog after the conceptual guides. It is generated from the "
    "executable Pydantic models, including nested types. Required fields have no "
    "usable default. Custom cross-field validators also apply; the [definition "
    "guide](definitions.md) explains the important relationships.",
    "",
    "These are the public SDK fields used by Python and YAML. JSON Schema alone "
    "does not describe every runtime capability check or side effect.",
    "",
    "[Download the complete schemas](../assets/project-schemas.json).",
    "",
    "## Find a contract",
    "",
]
for name in [*schemas, *sorted(nested)]:
    body.append(f"- [{name}](#{name.lower()})")


def _typ(p):
    if "$ref" in p:
        return p["$ref"].split("/")[-1]
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
    body.extend(["", f"## {name}", "", schema.get("description", "").split("\n\n")[0], ""])
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
(root / "reference/fields.md").write_text("\n".join(body) + "\n")
(root / "assets").mkdir(exist_ok=True)
(root / "assets/project-schemas.json").write_text(json.dumps(schemas, indent=2) + "\n")
print(f"Generated {len(schemas) + len(nested)} contracts.")
