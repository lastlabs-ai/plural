"""Run two offline library policies and save their episode traces."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _shared import ensure_out_dir
from enroute import Dataset, ScriptedPolicy
from enroute.environments.export.verifiers import to_verifiers_trace
from enroute.tracing import ParsedAction, Trace
from examples.environment.library.env import make_env


def _print_episode(title: str, trace: Trace) -> None:
    print(f"\n== {title} ==")
    reward = trace.outcome.reward if trace.outcome else None
    print(f"reward={reward}  terminated={trace.terminated}")
    for i, decision in enumerate(trace.decisions()):
        action = ", ".join(a.name for a in decision.parsed_action) or "respond"
        print(f"  t={i}  {action}")
    print(f"  r_t  (outcome) {trace.decision_rewards(source='outcome')}")
    print(f"  G_t  γ=0.9    {trace.returns(gamma=0.9)}")


def main() -> None:
    out = ensure_out_dir()
    env = make_env()
    task = next(env.iter_tasks())
    scripts = {
        "researcher": [
            ParsedAction(name="search", arguments={"query": "voting"}),
            ParsedAction(name="read", arguments={"doc_id": "d1"}),
            ParsedAction(name="answer", arguments={"text": "the river path"}),
        ],
        "guesser": [
            ParsedAction(name="answer", arguments={"text": "I don't know"}),
        ],
    }

    traces: list[Trace] = []
    for name, actions in scripts.items():
        rollout = env.run_episode(task, ScriptedPolicy(actions), model=name)
        traces.append(rollout.trace)
        _print_episode(name, rollout.trace)

    good = traces[0]
    # Likes / a reviewer arrive later — attribute them to the answer decision.
    good.credit(0.4, name="reviewer", reason="readers found it useful", decision_index=-1)
    print("\n== researcher after late reviewer credit on the answer ==")
    print(f"  r_t  (events) {good.decision_rewards(source='events')}")
    print(f"  r_t  (both)   {good.decision_rewards(source='both')}")
    print(f"  G_t  γ=0.9 both {good.returns(gamma=0.9, source='both')}")
    print("  search/read now share credit for the later review — no env rewrite.")

    ds = Dataset.from_traces("library", traces, version=env.version)
    ds.save(out / "library-dataset.jsonl")
    exported = to_verifiers_trace(good)
    print(f"\ndataset={ds.content_hash[:12]}…  verifiers_returns={exported['returns']}")


if __name__ == "__main__":
    main()
