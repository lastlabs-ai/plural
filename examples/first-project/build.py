"""Generate the example YAML from the same public objects used in Python."""

from pathlib import Path

from environment.world import SupportQueue
from verifiers.correct import correct_category

from plural import (
    Agent,
    Benchmark,
    ExecutionLimits,
    Job,
    Resource,
    Runtime,
    Task,
)
from plural.project import dump
from plural.verifiers import DeterministicVerifier

ROOT = Path(__file__).resolve().parent

environment = SupportQueue(
    resources=(Resource("policy.md", kind="data", content_type="text/markdown"),),
    runtime=Runtime.local(),
    limits=ExecutionLimits(max_turns=6, max_seconds=120),
)

verifier = DeterministicVerifier(name="correct-category", check=correct_category)

tasks = tuple(
    Task(
        name=ticket_id,
        instructions=(
            "Inspect the open ticket, categorize it, draft a concise customer response, "
            "then resolve it. Stop when the Environment reports done."
        ),
        goals=(
            "Use the support policy returned by inspect_ticket.",
            "Resolve the ticket only after categorizing it and drafting a response.",
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
