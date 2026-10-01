"""Action parameter schemas keep constraints and nested objects."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from plural.environments.action_registry import function_schema


def test_string_constraints_stay_on_the_parameter() -> None:
    def guess(
        word: Annotated[str, Field(min_length=5, max_length=5, pattern=r"^[a-z]{5}$")],
    ) -> None:
        """Guess."""

    schema = function_schema(guess)
    word = schema["properties"]["word"]
    assert word["type"] == "string"
    assert word["minLength"] == 5
    assert word["maxLength"] == 5
    assert word["pattern"] == r"^[a-z]{5}$"
    assert schema["required"] == ["word"]


def test_model_and_dict_parameters_keep_their_fields() -> None:
    class Move(BaseModel):
        direction: Literal["up", "down"]
        steps: int = Field(ge=1, le=10)

    class Box:
        def act(self, move: Move, flags: dict[str, bool], note: str = "ok") -> None:
            """Act."""

    schema = function_schema(Box.act)
    assert schema["properties"]["move"]["title"] == "Move"
    assert schema["properties"]["move"]["properties"]["steps"]["minimum"] == 1
    assert schema["properties"]["move"]["properties"]["steps"]["maximum"] == 10
    assert schema["properties"]["flags"]["additionalProperties"] == {"type": "boolean"}
    assert "self" not in schema["properties"]
    assert schema["required"] == ["move", "flags"]
    assert "note" not in schema["required"]


def test_nested_model_defs_are_hoisted() -> None:
    class Letter(BaseModel):
        mark: str

    class Move(BaseModel):
        letters: list[Letter]

    def place(move: Move) -> None:
        """Place."""

    schema = function_schema(place)
    assert schema["properties"]["move"]["properties"]["letters"]["items"] == {
        "$ref": "#/$defs/Letter"
    }
    assert schema["$defs"]["Letter"]["properties"]["mark"]["type"] == "string"
