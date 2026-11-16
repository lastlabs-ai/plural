# Quoting

A steel mill's quoting desk as a Plural project, built to walk through evaluating an
Agent: check that the graders can be trusted, run a baseline, and read the result.

```text
environments/quoting/         the mill: prices, stock, the schedule, and a reference policy
tasks/quote-001 ... 060/      sixty requests for quote, each with its answer key
verifiers/quote-check/        decides whether the quote or handoff was right
verifiers/tone/               a model judge of the customer note (1-5); no Task uses it yet
agents/quote-bot/             the Agent under test, with two planted weaknesses
benchmarks/quoting/           the sixty Tasks in four categories
traps.py                      plants a grader bug and integrity traps in a copy
```

Each request either gets a quote, at today's price and for a date the mill can meet,
or is handed off to a person when it can't be quoted safely. See
[the Benchmark's README](benchmarks/quoting/README.md) for the four categories and how
a Trial is scored.

## 1. See where you are

```bash
plural eval status
```

Every step of an evaluation is listed with its status, followed by the command to run
next. In a fresh copy, that is checking the graders.

## 2. Check the graders

```bash
plural eval check
```

Before any model is called, each Task runs three times through the normal engine,
each time with a fixed player in place of an Agent:

- the Environment's **reference policy** (`environments/quoting/reference.py`), which
  quotes or hands off the way a careful person would, and must pass;
- a **do-nothing** Agent, which must fail;
- an Agent that **repeats the instructions** back, which must fail.

Everything an Agent can read is then scanned for answer keys, git history, solution
files, Verifier code, and the Benchmark's canary. On this folder the check finds
nothing, and its next command is the baseline.

### Plant problems for it to find

`traps.py` copies the example and plants problems in the copy, so the clean example
stays as it is:

| Trap | What it plants |
| --- | --- |
| `unit-bug` | The answer keys of three requests in hundredweight (quote-016, quote-020, quote-053) record the cwt figure as short tons |
| `broken-check` | quote-024 is graded by a Verifier that forgot the `decision_correct` gate |
| `leaked-key` | The Environment ships a quote log holding quote-009's answer key |
| `git-history` | quote-013 runs in a Docker image whose `/repo` has older commits and a tag that held the answers |

```bash
python traps.py /tmp/quoting-traps --enable unit-bug,broken-check,leaked-key
cd /tmp/quoting-traps
plural eval check
```

```text
Graders
  ✓ reference solution passes every gate         57/60
  ✗ quote-016, quote-020, quote-053: reference fails price_correct
      quoted 15 t of 1018, but the request was for 300 t of 1018
  ✓ do-nothing agent fails                       59/60
  ✗ quote-024: noop passes: the graders gave 1.00 to an Agent that did nothing
      expected a handoff, but the Agent sent nothing
  ✓ copy-the-instructions agent fails            59/60
  ✗ quote-024: echo passes: the graders gave 1.00 to an Agent that repeated the instructions
      expected a handoff, but the Agent sent nothing
Leaks
  ✗ quote-009: The answer key "{"decision":"quote","grade":"304SS","tons":8}" appears in resources/quote-log.json.
      remove it from what the Agent sees; the answer key belongs in expected
Isolation
  ! quoting runs on the local Runtime, so Trials are unverified
      use runtime: {provider: daytona} for verified results

4 problems to fix before you baseline. Next: plural task check quote-016
```

`--all` adds `git-history`, which needs Docker and is reported under Leaks for
quote-013. A check is saved per Task in `.plural/checks/` and reused until the Task
changes, so running it again is quick.

## 3. Run the baseline

```bash
plural auth login
plural run -b quoting -a quote-bot --attempts 3
plural eval status
```

`eval status` then shows the score with its 95% interval, pass^k across the three
attempts, and how many Trials ran at each trust tier. On the `local` Runtime every
Trial is `unverified`. Set `runtime: {provider: daytona}` in
`environments/quoting/environment.yaml` for `verified` results.

## quote-bot's planted weaknesses

quote-bot is the Agent "you run today". It has two weaknesses on purpose, so later
steps have causes to find:

- **In its instructions**, it rounds the price per ton to a whole dollar before
  multiplying, so `price_correct` fails whenever the price has cents.
- **In the Environment**, the `check_schedule` action is described as "Optional: view
  mill bookings", so it skips the schedule and promises dates the mill can't meet.

Measured on the real model (`gpt-5.6-luna`, default reasoning), one attempt at each of
the 60 Tasks, on November 16, 2026:

| Weakness | Tasks it affects | Failed because of it |
| --- | --- | --- |
| Rounding | 25 quoted Tasks; every looked-up price had cents | 25 (100%) |
| Skipped schedule | 16 rush Tasks | 8 (50%): quoted the customer's date without checking the schedule, 1 to 7 days before the mill could deliver |

The other 8 rush requests were handed off instead of quoted, a wrong decision; 3 of
those followed a schedule check. quote-bot also handed off 7 of the 24 simple requests
because their wording ("1018 cold-finished bar", "304 stainless sheet") didn't match
the price book's grade names. That third failure was not planted. The mean score was
0.33: only the ambiguous and out-of-stock requests, where a handoff is right, passed.

This run reached OpenAI through a local stand-in for Plural's gateway that used the
gateway's own OpenAI adapter, rather than through pluralintel.com.

## Tests

`tests/unit/test_quoting_example.py` in the SDK repository runs the reference policy
and a scripted quote-bot on a fixed, stratified subset of 10 Tasks, at least two per
category, covering every weakness and trap. The run over all 60 Tasks is marked
`slow` and runs nightly.
