---
route: /docs/tutorials/support-queue
title: Support queue
order: 150
description: Build a support Environment, score replies with an AgentVerifier, run five tickets, and read the results.
audience: all
nav: true
nav_group: Tutorials
outcome: You can build, run, and interpret a five-ticket support evaluation from either the SDK or YAML and the CLI.
---
# Support queue

The Environment is a simulated support queue. The agent inspects a ticket, assigns billing, technical, or account, drafts a reply, and resolves it. An `AgentVerifier` judges whether the reply follows the policy.

This walkthrough builds that Environment, a model judge, five ticket Tasks, a Job, and then shows how to read the results. The actions change local evaluation state only. Choose the Python SDK or YAML and the CLI.

## Build and run

=== "Python SDK"


    Save this as `project.py`. Each Task selects a ticket through `info`. `reset` loads that ticket and keeps the expected category on State, off the Observation.

    ```python
    from plural import (
        Agent,
        AgentVerifier,
        Benchmark,
        Environment,
        Job,
        Observation,
        RubricCriterion,
        Runtime,
        State,
        Task,
        action,
    )

    TICKETS = {
        "dup-charge": ("I was charged twice for my annual plan.", "billing",
                       "Acknowledge the duplicate charge and send it to billing."),
        "app-crash": ("The desktop app crashes when I export a report.", "technical",
                      "Ask for the app version and route crashes to technical support."),
        "display-name": ("Where do I change the name my team sees?", "account",
                         "Profile settings control the display name."),
        "missing-refund": ("I was promised a refund last week and it has not arrived.", "billing",
                           "Do not promise a new refund. Route it to billing to check the first one."),
        "reset-password": ("I cannot reset my password from the login page.", "account",
                           "Send the password-reset steps. Do not ask for the current password."),
    }


    class TicketView(Observation):
        issue: str = ""
        policy: str = ""
        category: str = ""
        draft_reply: str = ""
        done: bool = False


    class Ticket(State):
        issue: str = ""
        policy: str = ""
        expected: str = ""
        category: str = ""
        draft_reply: str = ""
        done: bool = False


    class SupportQueue(Environment[TicketView, Ticket]):
        name = "support-queue"
        overview = "Categorize a ticket, draft a reply, and resolve it."

        def reset(self, *, seed=None, options=None):
            super().reset(seed=seed)
            ticket_id = (self.info or {}).get("ticket_id")
            if ticket_id not in TICKETS:
                raise ValueError("Task info.ticket_id must select a ticket")
            issue, expected, policy = TICKETS[ticket_id]
            self.state = Ticket(issue=issue, expected=expected, policy=policy, seed=self.state.seed)
            self.observation = TicketView(text=issue, issue=issue, policy=policy)
            return self.observation, {}

        @action
        def categorize(self, category: str) -> TicketView:
            if category not in {"billing", "technical", "account"}:
                raise ValueError("Choose billing, technical, or account")
            self.state.category = category
            self.observation.category = category
            return self.observation

        @action
        def draft_response(self, message: str) -> TicketView:
            if not self.state.category:
                raise ValueError("Categorize the ticket before drafting")
            self.state.draft_reply = message.strip()
            self.observation.draft_reply = self.state.draft_reply
            return self.observation

        @action
        def resolve(self) -> TicketView:
            if not self.state.draft_reply:
                raise ValueError("Draft a reply before resolving")
            self.state.done = True
            self.observation.done = True
            return self.observation

        def terminated(self) -> bool:
            return self.state.done


    environment = SupportQueue(runtime=Runtime.local())
    verifier = AgentVerifier(
        name="reply-quality",
        model="openai/gpt-5.6-luna",
        instructions=(
            "Judge draft_reply against the ticket issue and policy. "
            "Score only the stated criteria. Give zero when the reply is missing."
        ),
        criteria=[
            RubricCriterion(
                name="policy_accuracy",
                description="0 contradicts policy. 1 follows it but misses a next step. 2 follows it and states the next step.",
                min_score=0,
                max_score=2,
            ),
            RubricCriterion(
                name="clarity",
                description="0 is confusing. 1 is understandable but vague. 2 tells the customer what happens next.",
                min_score=0,
                max_score=2,
            ),
        ],
    )
    tasks = [
        Task(
            name=ticket_id,
            instructions="Categorize the ticket, draft a reply, and resolve it.",
            environment=environment,
            verifiers=[verifier],
            info={"ticket_id": ticket_id},
        )
        for ticket_id in TICKETS
    ]
    agent = Agent(
        model="openai/gpt-5.6-luna",
        instructions="Read the policy, pick the right team, and write a short reply before resolving.",
    )
    benchmark = Benchmark(name="support-triage", version="1.0.0", tasks=tasks)
    job = Job(benchmark, agents=[agent])
    ```

    The judge is a second model call with its own instructions. It is not the agent you are evaluating. `expected` stays in State so you can inspect it later; the agent never sees it.

    ```bash
    plural validate project.py:job
    plural run project.py:job --dry-run
    plural auth login
    plural run project.py:job
    ```

    Five tickets × one Agent is five Trials. The judge adds its own model cost.

=== "YAML and CLI"


    Keep the Environment class in `world.py` (the `SupportQueue` class from the SDK tab). YAML selects the ticket, the judge, and the Job.

    `environment.yaml`:

    ```yaml
    kind: environment
    python: world.py:SupportQueue
    name: support-queue
    runtime:
      provider: local
      allow_unsafe_local: true
    ```

    `verifier.yaml`:

    ```yaml
    kind: agent
    name: reply-quality
    model: openai/gpt-5.6-luna
    instructions: Judge draft_reply against the ticket issue and policy. Score only the stated criteria. Give zero when the reply is missing.
    criteria:
      - name: policy_accuracy
        description: 0 contradicts policy. 1 follows it but misses a next step. 2 follows it and states the next step.
        min_score: 0
        max_score: 2
      - name: clarity
        description: 0 is confusing. 1 is understandable but vague. 2 tells the customer what happens next.
        min_score: 0
        max_score: 2
    ```

    `tasks/dup-charge.yaml` — copy this for `app-crash`, `display-name`, `missing-refund`, and `reset-password`, changing `name` and `ticket_id`:

    ```yaml
    kind: task
    name: dup-charge
    instructions: Categorize the ticket, draft a reply, and resolve it.
    info:
      ticket_id: dup-charge
    environment: ../environment.yaml
    verifiers:
      - ../verifier.yaml
    ```

    `agent.yaml`:

    ```yaml
    kind: agent
    name: careful
    model: openai/gpt-5.6-luna
    instructions: Read the policy, pick the right team, and write a short reply before resolving.
    ```

    `benchmark.yaml`:

    ```yaml
    kind: benchmark
    name: support-triage
    version: 1.0.0
    tasks:
      - tasks/dup-charge.yaml
      - tasks/app-crash.yaml
      - tasks/display-name.yaml
      - tasks/missing-refund.yaml
      - tasks/reset-password.yaml
    ```

    `job.yaml`:

    ```yaml
    kind: job
    source: benchmark.yaml
    agents:
      - agent.yaml
    ```

    ```bash
    plural validate job.yaml
    plural run job.yaml --dry-run
    plural auth login
    plural run job.yaml
    ```

## Interpret the results

```bash
plural job list
plural job show JOB_ID
plural trial list JOB_ID
plural trial watch TRIAL_ID --job JOB_ID
```

`job show` prints mean reward, cost, and latency. The AgentVerifier reward is the weighted rubric score, not a simple 0/1. `trial list` shows each ticket. A low score on one ticket and a high score on another is the useful signal.

Open `.plural/jobs/JOB_ID/trials/TRIAL_ID/` when a score is surprising:

- **Trajectory:** categorize, draft, resolve, and any errors the agent hit.
- **Observation:** the issue, policy, category, and draft the judge saw.
- **State:** includes the expected team, which the agent did not see.
- **Verifier results:** each criterion score and the evidence the judge cited.

A finished Trial can still score poorly. That means the reply failed the rubric, not that the run crashed. If billing tickets are cheap and clear but account tickets are expensive and vague, change instructions or the policy before you change the model.
