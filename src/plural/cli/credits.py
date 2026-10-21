"""Tell the person running a Job when its credits run low or out.

Model calls wait while the account has no credits, so a run that runs out
looks stalled rather than failed. This watch reads the balance while the run
goes and says what is happening and where to add credits, once per change.
"""

from __future__ import annotations

import threading
from types import TracebackType
from typing import Any, Literal

import typer

from plural.harness.native_runner import DEFAULT_CREDIT_PAUSE_SECONDS
from plural.studio import Studio

State = Literal["ok", "low", "out"]


class CreditWatch:
    """Reads the account balance every ``interval`` seconds while a run goes.

    Args:
        studio: Hosted API client for the signed-in account.
        interval: Seconds between balance checks.
        err: Print to stderr, as when the run's output is JSON.
    """

    def __init__(self, studio: Studio, *, interval: float = 60.0, err: bool = True) -> None:
        self._studio = studio
        self._interval = interval
        self._err = err
        self._state: State = "ok"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> CreditWatch:
        self.check()
        self._thread = threading.Thread(target=self._loop, name="plural-credits", daemon=True)
        self._thread.start()
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            self.check()

    def check(self) -> State:
        """Read the balance and say so when its state changed.

        Returns:
            The state now: ``ok``, ``low``, or ``out``.
        """
        try:
            account = self._studio.request("GET", "/account")
        except Exception:  # noqa: BLE001
            return self._state
        wallet: dict[str, Any] = account.get("wallet") or {}
        available = float(wallet.get("available_usd", wallet.get("balance_remaining_usd", 0)))
        low = float(wallet.get("low_balance_usd", 5))
        url = str(wallet.get("add_credits_url") or "the Credits page of the web app")
        state: State = "out" if available <= 0 else "low" if available <= low else "ok"
        if state != self._state:
            message = _message(state, self._state, available, url)
            if message:
                typer.echo(message, err=self._err)
            self._state = state
        return state


def _message(state: State, before: State, available: float, url: str) -> str | None:
    if state == "out":
        minutes = round(DEFAULT_CREDIT_PAUSE_SECONDS / 60)
        return (
            "Out of credits. Model calls are paused, and running Trials wait where "
            f"they are for up to {minutes} minutes. Add credits at {url} and they "
            "resume within a minute."
        )
    if state == "low":
        return (
            f"Credits are low: ${available:.2f} left. Add credits at {url} so this "
            "run is not paused."
        )
    if before == "out":
        return "Credits added. Paused Trials are resuming."
    return None


__all__ = ["CreditWatch"]
