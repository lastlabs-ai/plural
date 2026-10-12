"""Plan an Agent routing comparison on one Task."""

from plural import Agent, Benchmark, Environment, Job, Runtime, Task
from plural.verifiers import DeterministicVerifier

environment = Environment(name="routing-world", runtime=Runtime.docker())
verifier = DeterministicVerifier(name="correct", check=("python", "verify.py"))
task = Task(
    name="route-request",
    instructions="Answer the request.",
    environment=environment,
    verifiers=(verifier,),
)
benchmark = Benchmark(name="routing-comparison", version="1.0.0", tasks=(task,))
agents = (
    Agent(
        name="primary-only",
        model="openai/gpt-5.6-luna",
    ),
    Agent(
        name="with-fallback",
        model="openai/gpt-5.6-luna",
        fallback_models=("anthropic/claude-haiku-4-5",),
    ),
)
job = Job(
    benchmark,
    agents=agents,
    attempts=3,
    concurrency=4,
)

plan = job.plan
assert plan.trial_count == 6
print(plan.model_dump_json(indent=2))
