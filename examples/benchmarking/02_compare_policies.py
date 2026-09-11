"""Plan an Agent routing comparison on one revisioned Task."""

from plural import (
    AgentBinding,
    AgentDefinition,
    BenchmarkDefinition,
    BenchmarkJobSource,
    DeterministicVerifier,
    EnvironmentDefinition,
    JobSpec,
    RoutingSpec,
    TaskDefinition,
    WeightedVerifier,
)

environment = EnvironmentDefinition(name="routing-world")
verifier = DeterministicVerifier(name="correct", command=("python", "verify.py"))
task = TaskDefinition(
    task_id="route-request",
    instructions="Answer the request.",
    environment=environment,
    verifiers=(WeightedVerifier(verifier=verifier),),
)
benchmark = BenchmarkDefinition(name="routing-comparison", tasks=(task,))
agents = (
    AgentDefinition(
        name="primary-only",
        model="openai/gpt-4.1-mini",
    ),
    AgentDefinition(
        name="with-fallback",
        model="openai/gpt-4.1-mini",
        routing=RoutingSpec(fallback_models=("anthropic/claude-sonnet-4",)),
    ),
)
spec = JobSpec(
    source=BenchmarkJobSource(benchmark=benchmark),
    agents=tuple(AgentBinding(agent=agent) for agent in agents),
    attempts=3,
    concurrency=4,
)

plan = spec.plan()
assert plan.trial_count == 6
print(plan.model_dump_json(indent=2))
