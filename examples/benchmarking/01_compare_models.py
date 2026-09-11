"""Plan a model comparison across Task revisions and Environments."""

from plural import (
    AgentBinding,
    AgentDefinition,
    BenchmarkDefinition,
    BenchmarkJobSource,
    DeterministicVerifier,
    EnvironmentDefinition,
    JobSpec,
    TaskDefinition,
    WeightedVerifier,
)

verifier = DeterministicVerifier(name="correct", command=("python", "verify.py"))
tasks = tuple(
    TaskDefinition(
        task_id=name,
        instructions=prompt,
        environment=EnvironmentDefinition(name=f"{name}-environment"),
        verifiers=(WeightedVerifier(verifier=verifier),),
    )
    for name, prompt in (
        ("refund", "Respond to a refund request."),
        ("shipping", "Respond to a shipping question."),
    )
)
benchmark = BenchmarkDefinition(name="support", tasks=tasks)
agents = tuple(
    AgentBinding(agent=AgentDefinition(name=model.rsplit("/", 1)[-1], model=model))
    for model in ("openai/gpt-4.1-mini", "anthropic/claude-sonnet-4")
)
spec = JobSpec(
    source=BenchmarkJobSource(benchmark=benchmark),
    agents=agents,
    attempts=2,
    concurrency=4,
)

plan = spec.plan()
assert plan.trial_count == 8
assert len({trial.environment.digest for trial in plan.trials}) == 2
print(plan.model_dump_json(indent=2))
