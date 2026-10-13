"""Plays its turns, and tries every way to see what another seat sees."""

import glob
import json
import os
from typing import Any

from plural import Harness, HarnessResult


def _readable(read: Any) -> bool:
    try:
        read()
    except OSError:
        return False
    return True


def _read(path: str) -> str:
    with open(path) as handle:
        return handle.read()


def _write(path: str) -> None:
    with open(path, "w") as handle:
        handle.write("x")


class Spy(Harness):
    name = "spy"
    auth = ("none",)

    def run(self, task: Any, agent: Any, environment: Any) -> HarnessResult:
        home = os.environ["HOME"]
        mine = os.path.basename(home)
        others = [f"seat_{n}" for n in (1, 2) if f"seat_{n}" != mine]
        with open(f"/tmp/drop-{mine}", "w") as note:
            note.write(mine)
        last = None
        while True:
            view = environment.wait_for_turn()
            last = view.observation
            if view.done:
                break
            environment.step("post", text=f"hello from {view.seat}")
        tokens = []
        for pid in filter(str.isdigit, os.listdir("/proc")):
            try:
                with open(f"/proc/{pid}/environ", "rb") as handle:
                    if int(pid) != os.getpid() and b"PLURAL_SEAT_TOKEN" in handle.read():
                        tokens.append(pid)
            except OSError:
                pass
        seen = {
            "seats_root": _readable(lambda: os.listdir("/workspace/seats")),
            "other_folder": any(
                _readable(lambda o=o: os.listdir(f"/workspace/seats/{o}")) for o in others
            ),
            "other_drop": any(_readable(lambda o=o: _read(f"/tmp/drop-{o}")) for o in others),
            "app_host": any(
                _readable(lambda p=p: os.listdir(p)) for p in glob.glob("/workspace/.plural-apps-*")
            ),
            "environment_writable": _readable(lambda: _write("/workspace/environment/note")),
            "other_seat_token": bool(tokens),
        }
        return HarnessResult(response=json.dumps({"seen": seen, "last": last}))
