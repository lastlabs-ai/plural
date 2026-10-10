"""Plan a model comparison across Tasks and Environments."""

from plural import Agent, Benchmark, Environment, Job, Runtime, Task
from plural.rewarders import DeterministicRewarder

rewarder = DeterministicRewarder(name="correct", final=("python", "reward.py"))
tasks = tuple(
    Task(
        name=name,
        instructions=prompt,
        environment=Environment(name=f"{name}-environment", runtime=Runtime.docker()),
        rewarders=(rewarder,),
    )
    for name, prompt in (
        ("refund", "Respond to a refund request."),
        ("shipping", "Respond to a shipping question."),
    )
)
benchmark = Benchmark(name="support", version="1.0.0", tasks=tasks)
agents = tuple(
    Agent(name=model.rsplit("/", 1)[-1], model=model)
    for model in ("openai/gpt-5.6-luna", "anthropic/claude-haiku-4-5")
)
job = Job(
    benchmark,
    agents=agents,
    attempts=2,
    concurrency=4,
)

plan = job.plan
assert plan.trial_count == 8
assert len({trial.environment.name for trial in plan.trials}) == 2
print(plan.model_dump_json(indent=2))
