from plural import ExecutionTarget, Runtime
from plural.sandbox import NetworkMode
from wordle import Wordle

environment = Wordle(
    runtime=Runtime(
        provider="local",
        network=NetworkMode.FULL,
        targets=frozenset({ExecutionTarget.LOCAL}),
        allow_unsafe_local=True,
    )
).package(("python", "commands.py"))
