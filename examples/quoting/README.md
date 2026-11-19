# Quoting

A steel mill's quoting desk as a Plural project, built to walk through evaluating an
Agent: check that the Tasks and graders can be trusted, run a baseline, and read the
result.

```text
environments/quoting/         the mill: prices, stock, the schedule, and a reference policy
tasks/quote-001 ... 080/      eighty requests for quote, each with its answer key
verifiers/quote-check/        decides whether the quote or handoff was right
verifiers/tone/               a model judge of the customer note (1-5); no Task uses it yet
agents/quote-bot/             the Agent under test, with two planted weaknesses
benchmarks/quoting/           the eighty Tasks in four categories, 20 of them held out
traps.py                      plants wrong answer keys, grader bugs and integrity traps in a copy
```

Each request either gets a quote, at today's price and for a date the mill can meet,
or is handed off to a person when it can't be quoted safely. See
[the Benchmark's README](benchmarks/quoting/README.md) for the four categories and how
a Trial is scored.

## 1. Check the Tasks and graders

```bash
plural benchmark validate quoting
```

After checking the files, each Task runs three times through the normal engine, each
time with a fixed player in place of an Agent, before any model is called:

- the Environment's **reference policy** (`environments/quoting/reference.py`), which
  quotes or hands off the way a careful person would, and must pass;
- a **do-nothing** Agent, which must fail;
- an Agent that **repeats the instructions** back, which must fail.

Everything an Agent can read is then scanned for answer keys, git history, solution
files, Verifier code, and the Benchmark's canary, and the Environment's default
Runtime is checked for how far its results can be trusted. On this folder the check
finds no problems. Add `--no-probes` to check the files alone.

### Plant problems for it to find

`traps.py` copies the example and plants problems in the copy, so the clean example
stays as it is:

| Trap | What it plants |
| --- | --- |
| `unit-bug` | The answer keys of three requests in hundredweight (quote-016, quote-020, quote-053) record the cwt figure as short tons |
| `broken-check` | quote-024 is graded by a Verifier that forgot the `decision_correct` gate |
| `leaked-key` | The Environment ships a quote log holding quote-009's answer key |
| `git-history` | quote-013 runs in a Docker image whose `/repo` has older commits and a tag that held the answers |
| `lenient-delivery` | quote-check's delivery check passes every date, ignoring the mill calendar |

```bash
python traps.py /tmp/quoting-traps --enable unit-bug,broken-check,leaked-key
cd /tmp/quoting-traps
plural benchmark validate quoting
```

```text
Graders
  ✓ reference solution passes every gate         77/80
  ✗ quote-016, quote-020, quote-053: reference fails price_correct
      quoted 15 t of 1018, but the request was for 300 t of 1018
  ✓ do-nothing agent fails                       79/80
  ✗ quote-024: noop passes: the graders gave 1.00 to an Agent that did nothing
      expected a handoff, but the Agent sent nothing
  ✓ copy-the-instructions agent fails            79/80
  ✗ quote-024: echo passes: the graders gave 1.00 to an Agent that repeated the instructions
      expected a handoff, but the Agent sent nothing

Leaks
  ✗ quote-009: The answer key "{"decision":"quote","grade":"304SS","tons":8}" appears in resources/quote-log.json.
      remove it from what the Agent sees; the answer key belongs in expected

Trust
  ! quoting runs on the local Runtime, so Trials are unverified
      use runtime: {provider: daytona} for verified results

4 problems to fix before you baseline. Next: plural task validate quote-016
```

`--all` adds `git-history`, which needs Docker and is reported under Leaks for
quote-013. A check is saved per Task in `.plural/checks/` and reused until the Task
changes, so running it again is quick. `lenient-delivery` is a grader bug the probes
can't see: the reference still passes, and so do Agents that promise impossible dates.

## 2. What passes

`verifiers/quote-check/verifier.yaml` marks its four binary checks as gates
(`gate: true`): `decision_correct`, `price_correct`, `delivery_feasible`, and
`above_cost`. A Trial **passes** when every gate that applies passes. A handoff has no
quote, so its price, delivery and cost checks are `None` and don't apply. `margin_usd`
has a `target` of `>= 150`, which is reported but never decides a pass.

The **pass rate** is the share of Trials that passed every gate. The **success rate** is
the share whose score reached the Benchmark's success threshold. Both are reported.

## 3. Run the baseline

```bash
plural auth login
plural run -b quoting -a quote-bot --attempts 3
```

The summary shows the score with its 95% interval, the success rate, pass^k across
the three attempts, the pass rate, and how many Trials ran at each trust tier. On the
`local` Runtime every Trial is `unverified`. Set `runtime: {provider: daytona}` in
`environments/quoting/environment.yaml` for `verified` results.

A plain run covers the 60 dev Tasks. The Benchmark holds back 20, quote-061 to
quote-080, under `heldout:`, to confirm a fix on requests nobody tuned the Agent
against. They were written after every run, inspection, and fork below, so nothing
has touched them; a Task that has run can't be held out. `plural run -b quoting -a
quote-bot --heldout` runs them alone, and each such run is a counted peek.

## quote-bot's planted weaknesses

quote-bot is the Agent "you run today". It has two weaknesses on purpose, so later
steps have causes to find:

- **In its instructions**, it rounds the price per ton to a whole dollar before
  multiplying, so `price_correct` fails whenever the price has cents.
- **In the Environment**, the `check_schedule` action is described as "Optional: view
  mill bookings", so it skips the schedule and promises dates the mill can't meet.

Measured on the real model (`openai/gpt-5.6-luna` through Plural's gateway), one
attempt at each of the first 60 Tasks, on November 16, 2026:

| Weakness | Tasks it affects | Failed because of it |
| --- | --- | --- |
| Rounding | 23 quoted Tasks; every looked-up price had cents | 23 (100%) |
| Skipped schedule | 16 rush Tasks | 5 (31%): quoted the customer's date without checking the schedule, 2 to 7 days before the mill could deliver |

The other 11 rush requests were handed off instead of quoted, a wrong decision; 5 of
those followed a schedule check. quote-bot also handed off 6 of the 24 simple requests
because their wording ("1018 cold-finished bar", "304 stainless sheet") didn't match
the price book's grade names. That third failure was not planted. The mean score was
0.33: only the ambiguous and out-of-stock requests, where a handoff is right, passed.

## 4. Find out why, and prove the fix

```bash
python traps.py --enable unit-bug        # plant the wrong answer keys too
plural run -b quoting -a quote-bot
plural job inspect JOB
plural agent revise quote-bot --from-finding F1
plural agent revise quote-bot --from-finding F23
plural run -b quoting -a quote-bot --heldout --attempts 2
plural job report NEW_JOB --compare OLD_JOB --findings
```

The unit bug is a wrong answer key, so the Inspector should put it under `task`: the
Verifier's code is right, and the request contradicts the key.

Measured on November 18, 2026, with the unit bug planted, when the Benchmark had 60
Tasks and before the rule that a wrong answer key is `task`. The Inspector explained all 30 failed dev Trials for $4.15. It put the 15 rounding failures under
`instructions` (14 confirmed by forks), the skipped schedule under `tools` (quote-036
confirmed, quote-037 not), and quote-016 and quote-020 under `grader`; it put
quote-053, the third Task the bug touches, under `instructions`. Revising quote-bot
from F1 and F23 made version 1.2.0. On the 14 Tasks then held out, two attempts each,
its pass rate rose from 36% (10 of 28) to 82% (23 of 28), a `better` verdict with a
95% interval of +21% to +71% for the change. Those Tasks had already been run and
inspected, so they weren't held out in the sense that counts: they are dev Tasks now,
and quote-061 to quote-080 replace them. What still fails is the unplanted weakness:
grade names like "304 stainless sheet". See [Find out why an Agent fails](../../docs/running/inspector.md).

Measured again on November 19, 2026, on the 20 Tasks now held out (quote-061 to
quote-080), which no dev run or inspection had used, two attempts each with
`--heldout`, which runs only those Tasks: quote-bot 1.2.0 passed 73% (29 of 40)
against 1.0.0's 28% (11 of 40), a `better` verdict, a change of +45% (95% interval
+22% to +65%). The two runs were peeks 4 and 5. Peek 3, an earlier run in which every
Trial errored before a verdict, is flagged as having revealed nothing.

`inspector-bench.json` holds the Inspector's accuracy on inspector-bench, built from
this example.

## Tests

`tests/unit/test_quoting_example.py` in the SDK repository runs the reference policy
and a scripted quote-bot on a fixed, stratified subset of 10 Tasks, at least two per
category, covering every weakness and trap. The run over all 80 Tasks is marked
`slow` and runs nightly.
