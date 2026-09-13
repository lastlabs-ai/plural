"""Generate the example YAML from the same public objects used in Python."""

from pathlib import Path

from environment.world import SupportQueue

from plural import (
    Agent,
    Benchmark,
    EvidenceContract,
    ExecutionLimits,
    ExecutionTarget,
    Job,
    Runtime,
    Task,
)
from plural.project import dump
from plural.sandbox import NetworkMode
from plural.verifiers import DeterministicVerifier, VerifierRuntime

ROOT = Path(__file__).resolve().parent
VERIFY = (ROOT / "verifiers" / "correct.py").read_text(encoding="utf-8")

environment = SupportQueue(
    runtime=Runtime(
        provider="local",
        network=NetworkMode.FULL,
        targets=frozenset({ExecutionTarget.LOCAL}),
        allow_unsafe_local=True,
    ),
    limits=ExecutionLimits(max_turns=6, max_seconds=120),
).package(("python", "commands.py"), source=ROOT / "environment")

verifier = DeterministicVerifier(
    name="correct-category",
    check=("python", "-c", VERIFY),
    runtime=VerifierRuntime(provider="local", network="full"),
    evidence=EvidenceContract(
        observation_paths=("category", "done"),
        state_paths=("expected",),
        include_hidden_state=True,
    ),
)

tasks = tuple(
    Task(
        name=ticket_id,
        instructions=(
            "Read the open ticket, categorize it correctly, then give a brief "
            "final confirmation. Stop after categorization."
        ),
        environment=environment,
        verifiers=[verifier],
        info={"ticket_id": ticket_id},
        metadata={"split": "evaluation"},
    )
    for ticket_id in ("ticket-1", "ticket-2", "ticket-3")
)
agents = tuple(
    Agent(
        model="openai/gpt-5.6-luna",
        name=name,
        instructions=instructions,
        secret_names=("OPENAI_API_KEY",),
    )
    for name, instructions in (
        (
            "careful",
            "Inspect the ticket before categorizing it. Use the Environment actions.",
        ),
        ("concise", "Complete the task using the available actions. Be concise."),
    )
)
benchmark = Benchmark(name="support-triage", version="1.0.0", tasks=tasks)
job = Job(tasks[0], agents=[agents[0]])

dump(environment, ROOT / "environment" / "environment.yaml")
dump(verifier, ROOT / "verifiers" / "correct.yaml")
for task in tasks:
    dump(task, ROOT / "tasks" / f"{task.name}.yaml")
for agent in agents:
    dump(agent, ROOT / "agents" / f"{agent.name}.yaml")
dump(benchmark, ROOT / "benchmark.yaml")
dump(job, ROOT / "job.yaml")

print("Built Environment, Verifier, three Tasks, two Agents, Benchmark, and Job.")
