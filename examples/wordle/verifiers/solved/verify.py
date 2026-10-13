"""Verify a Wordle game: score it, reward each guess, and credit a quick solve afterwards."""

from plural import Episode, HindsightTrial, Step, VerifierOutput


def check(episode: Episode) -> VerifierOutput:
    """Score 1 when the secret was found and 0 otherwise. Report the guesses used."""
    guesses = len(episode.state["guesses"])
    solved = episode.state["solved"]
    return VerifierOutput(
        score=float(solved),
        scores={"guesses": float(guesses)},
        evidence=[f"solved in {guesses}" if solved else f"unsolved after {guesses}"],
    )


def reward(step: Step) -> float:
    """0.2 for each letter a guess newly puts in place, and -0.1 for a refused word."""
    if step.error:
        return -0.1
    before = step.previous_state["found"].count(".")
    after = step.current_state["found"].count(".")
    return round(0.2 * (before - after), 2)


def fewer_guesses(trial: HindsightTrial):
    """Once the game is won, credit the winning guess more the fewer guesses it took."""
    guesses = trial.steps("guess")
    if trial.score and guesses:
        yield trial.credit(guesses[-1]["event_id"], round(1.0 - 0.1 * (len(guesses) - 1), 2))
