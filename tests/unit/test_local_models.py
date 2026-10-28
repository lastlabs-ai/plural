from __future__ import annotations

import json
import os
import struct
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest
from project_fixtures import write_project
from typer.testing import CliRunner

from plural import (
    Agent,
    DeterministicVerifier,
    Environment,
    Episode,
    Job,
    Runtime,
    Task,
    VerifierOutput,
)
from plural.cli.main import app
from plural.local_models import (
    KnownModels,
    LocalModelError,
    claimed_size,
    inspect_local_model,
    known_models,
    review_local_models,
    unverified_message,
)


def answered_paid(episode: Episode) -> VerifierOutput:
    return VerifierOutput(score=1.0 if "PAID" in json.dumps(episode.trajectory) else 0.0)


def _reply(model: str | None = None, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "choices": [{"message": {"role": "assistant", "content": "PAID"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1},
        **extra,
    }
    if model is not None:
        body["model"] = model
    return body


def _client(routes: dict[str, Any], chat: Any = None) -> httpx.Client:
    """A fake server: GET paths answer from ``routes``, chat completions from ``chat``."""

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path.endswith("/chat/completions"):
            body = json.loads(request.content)
            return httpx.Response(200, json=chat(body) if chat else _reply(body["model"]))
        if request.method == "POST" and path in routes:
            return httpx.Response(200, json=routes[path](json.loads(request.content)))
        if request.method == "GET" and path in routes:
            return httpx.Response(200, json=routes[path])
        return httpx.Response(404, json={"error": "not found"})

    return httpx.Client(transport=httpx.MockTransport(handle))


def _cache(hub: Path, repo: str, shapes: list[list[int]], bits: int | None = None) -> None:
    """A Hugging Face cache entry for ``repo`` whose safetensors header holds ``shapes``."""
    folder = hub / f"models--{repo.replace('/', '--')}"
    snapshot = folder / "snapshots" / "abc123def4567890"
    snapshot.mkdir(parents=True)
    (folder / "refs").mkdir()
    (folder / "refs" / "main").write_text("abc123def4567890")
    config: dict[str, Any] = {"quantization": {"bits": bits}} if bits else {}
    (snapshot / "config.json").write_text(json.dumps(config))
    header = {
        f"layer{index}.weight": {"dtype": "F16", "shape": shape, "data_offsets": [0, 0]}
        for index, shape in enumerate(shapes)
    }
    encoded = json.dumps(header).encode()
    (snapshot / "model.safetensors").write_bytes(struct.pack("<Q", len(encoded)) + encoded)


def _mlx(hub: Path) -> httpx.Client:
    return _client(
        {"/v1/models": {"data": [{"id": "mlx-community/Qwen3-8B-4bit"}]}},
        chat=lambda body: _reply(body["model"], system_fingerprint="0.31.3-0.32.1-macOS-15"),
    )


def test_an_mlx_server_is_identified_by_the_weights_on_this_machine(tmp_path: Path) -> None:
    _cache(tmp_path, "mlx-community/Qwen3-8B-4bit", [[8_000, 1_024_000]], bits=4)

    identity = inspect_local_model(
        "http://localhost:2080/v1",
        "mlx-community/Qwen3-8B-4bit",
        http=_mlx(tmp_path),
        hf_hub=tmp_path,
    )

    assert identity.server == "mlx-lm"
    assert identity.server_version == "0.31.3"
    assert identity.method == "weights"
    assert identity.weights == "hf:mlx-community/Qwen3-8B-4bit@abc123def456"
    assert identity.size == "8.2B"
    assert identity.quantization == "4-bit"
    assert identity.warnings == ()
    assert identity.fingerprint.startswith("SHA256:")
    assert any("weight files on this machine" in line for line in identity.describe())


def test_a_27b_model_under_an_8b_name_is_flagged(tmp_path: Path) -> None:
    _cache(tmp_path, "acme/qwen-8b", [[27_400, 1_000_000]])

    identity = inspect_local_model(
        "http://localhost:2080/v1", "acme/qwen-8b", http=_mlx(tmp_path), hf_hub=tmp_path
    )

    assert identity.warnings == ("the name says 8B, but the weights hold about 27.4B parameters",)


def test_llama_cpp_answers_any_name_with_its_one_model() -> None:
    http = _client(
        {
            "/v1/models": {
                "data": [
                    {
                        "id": "qwen3-27b-Q4_K_M.gguf",
                        "owned_by": "llamacpp",
                        "meta": {"n_params": 27_400_000_000, "size": 16_000_000_000},
                    }
                ]
            },
            "/props": {"model_path": "/models/qwen3-27b-Q4_K_M.gguf", "build_info": "b5000"},
        }
    )

    identity = inspect_local_model("http://localhost:8080/v1", "qwen:8b", http=http)

    assert identity.server == "llama.cpp"
    assert identity.weights == "qwen3-27b-Q4_K_M.gguf"
    assert identity.quantization == "Q4_K_M"
    assert identity.warnings == (
        "llama.cpp serves one model, qwen3-27b-Q4_K_M.gguf, whatever name a request gives it.",
        "the name says 8B, but the weights hold about 27.4B parameters",
    )


def _ollama(digest: str) -> httpx.Client:
    return _client(
        {
            "/api/version": {"version": "0.12.0"},
            "/api/tags": {"models": [{"name": "qwen3:8b", "digest": digest}]},
            "/api/show": lambda body: {
                "details": {"parameter_size": "8.2B", "quantization_level": "Q4_K_M"},
                "model_info": {"general.parameter_count": 8_190_735_360},
            },
        }
    )


def test_ollama_identifies_a_model_by_its_digest() -> None:
    first = inspect_local_model("http://localhost:11434/v1", "qwen3:8b", http=_ollama("a" * 64))
    again = inspect_local_model("http://localhost:11434/v1", "qwen3:8b", http=_ollama("a" * 64))
    other = inspect_local_model("http://localhost:11434/v1", "qwen3:8b", http=_ollama("b" * 64))

    assert first.server == "ollama"
    assert first.method == "server"
    assert first.weights == "ollama:qwen3:8b@aaaaaaaaaaaa"
    assert first.size == "8.2B"
    assert first.fingerprint == again.fingerprint
    assert first.fingerprint != other.fingerprint
    with pytest.raises(LocalModelError, match="ollama pull qwen3:27b"):
        inspect_local_model("http://localhost:11434/v1", "qwen3:27b", http=_ollama("a" * 64))


def test_vllm_refuses_a_name_it_does_not_serve() -> None:
    http = _client(
        {"/v1/models": {"data": [{"id": "qwen-27b", "owned_by": "vllm", "root": "Qwen/Qwen3-27B"}]}}
    )

    with pytest.raises(LocalModelError, match="It serves: qwen-27b"):
        inspect_local_model("http://gpu:8000/v1", "qwen:8b", http=http)
    identity = inspect_local_model("http://gpu:8000/v1", "qwen-27b", http=http)
    assert identity.server == "vllm"
    assert identity.weights == "Qwen/Qwen3-27B"


def test_a_server_that_reports_nothing_is_fingerprinted_by_its_answers() -> None:
    def answers(text: str) -> Any:
        return lambda body: _reply(
            body["model"], choices=[{"message": {"role": "assistant", "content": text}}]
        )

    first = inspect_local_model("http://box/v1", "mystery", http=_client({}, answers("one")))
    same = inspect_local_model("http://box/v1", "mystery", http=_client({}, answers("one")))
    other = inspect_local_model("http://box/v1", "mystery", http=_client({}, answers("two")))

    assert first.method == "behavior"
    assert first.fingerprint == same.fingerprint != other.fingerprint
    assert any("answers to fixed prompts" in line for line in first.describe())


def test_an_unreachable_server_says_so() -> None:
    with pytest.raises(
        LocalModelError, match="Cannot reach the model server at http://127.0.0.1:9"
    ):
        inspect_local_model("http://127.0.0.1:9/v1", "qwen3:8b")


@pytest.mark.parametrize(
    ("name", "size"),
    [
        ("qwen3:8b", 8.0),
        ("Qwen/Qwen3-27B", 27.0),
        ("mlx-community/Qwen3-8B-4bit", 8.0),
        ("llama-3.1-70b-instruct", 70.0),
        ("phi-2.7b", 2.7),
        ("acme/support-agent", None),
        ("gpt-4.1", None),
    ],
)
def test_claimed_size_reads_the_size_in_a_name(name: str, size: float | None) -> None:
    assert claimed_size(name) == size


def test_known_models_remembers_a_fingerprint_and_notices_a_change(tmp_path: Path) -> None:
    store = KnownModels(tmp_path / "known_models.json")
    first = inspect_local_model("http://localhost:11434/v1", "qwen3:8b", http=_ollama("a" * 64))
    swapped = inspect_local_model("http://localhost:11434/v1", "qwen3:8b", http=_ollama("b" * 64))

    assert store.lookup(first) == ("new", None)
    store.remember(first)
    assert store.lookup(first)[0] == "known"
    status, record = store.lookup(swapped)
    assert status == "changed"
    assert record is not None and record["fingerprint"] == first.fingerprint


class _Ollama(BaseHTTPRequestHandler):
    """An Ollama that swaps its weights after ``swap_after`` answers to the Harness."""

    digest = "a" * 64
    swap_after: int | None = None
    answered = 0

    def _send(self, body: dict[str, Any], status: int = 200) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        cls = type(self)
        if self.path == "/api/version":
            self._send({"version": "0.12.0"})
        elif self.path == "/api/tags":
            self._send({"models": [{"name": "qwen3:8b", "digest": cls.digest}]})
        elif self.path == "/v1/models":
            self._send({"data": [{"id": "qwen3:8b", "owned_by": "library"}]})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self) -> None:
        cls = type(self)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/show":
            self._send({"details": {"parameter_size": "8.2B", "quantization_level": "Q4_K_M"}})
            return
        if body.get("max_tokens") != 1:
            cls.answered += 1
            if cls.swap_after is not None and cls.answered >= cls.swap_after:
                cls.digest = "b" * 64
        self._send(_reply(body["model"]))

    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture
def ollama_server() -> Iterator[str]:
    _Ollama.digest, _Ollama.swap_after, _Ollama.answered = "a" * 64, None, 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Ollama)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()


@pytest.fixture
def ollama(ollama_server: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    monkeypatch.delenv("PLURAL_API_KEY", raising=False)
    monkeypatch.delenv("PLURAL_GATEWAY_URL", raising=False)
    monkeypatch.setenv("PLURAL_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.chdir(tmp_path)
    return ollama_server


def _task() -> Task:
    return Task(
        name="refund-01",
        instructions="Say PAID.",
        environment=Environment(name="support", runtime=Runtime.local()),
        verifiers=[DeterministicVerifier(name="paid", check=answered_paid)],
    )


def test_a_job_refuses_a_local_model_nobody_accepted(ollama: str) -> None:
    agent = Agent(model="qwen3:8b", endpoint=ollama)

    with pytest.raises(LocalModelError) as refused:
        Job(_task(), agents=[agent]).run()

    message = str(refused.value)
    assert "runs a local model nobody has accepted yet" in message
    assert "weights: ollama:qwen3:8b@aaaaaaaaaaaa" in message
    assert "allow_local_models=True" in message
    assert _Ollama.answered == 0


def test_a_job_records_the_model_it_was_allowed_to_run(ollama: str) -> None:
    agent = Agent(model="qwen3:8b", endpoint=ollama)

    trial = Job(_task(), agents=[agent], allow_local_models=True).run().trials[0]

    assert trial.score == 1.0, trial.error_message
    assert trial.model_identity is not None
    assert trial.model_identity.trust == "allowed"
    assert trial.model_identity.weights == "ollama:qwen3:8b@aaaaaaaaaaaa"


def test_a_job_runs_a_model_accepted_before(ollama: str) -> None:
    agent = Agent(model="qwen3:8b", endpoint=ollama)
    review_local_models(
        Job(_task(), agents=[agent]).spec.agents, dict(os.environ), lambda *_: "confirmed"
    )

    trial = Job(_task(), agents=[agent]).run().trials[0]

    assert trial.score == 1.0, trial.error_message
    assert trial.model_identity is not None and trial.model_identity.trust == "known"

    _Ollama.digest = "c" * 64
    with pytest.raises(LocalModelError, match="is not the one accepted on"):
        Job(_task(), agents=[agent]).run()


def test_a_model_swapped_mid_job_fails_the_trials_after_it(ollama: str) -> None:
    _Ollama.swap_after = 1
    agent = Agent(model="qwen3:8b", endpoint=ollama)

    result = Job(_task(), agents=[agent], attempts=2, allow_local_models=True).run()

    first, second = result.trials
    assert first.score == 1.0, first.error_message
    assert second.score is None
    assert second.error_message is not None
    assert "changed after the Job started" in second.error_message
    assert "ollama:qwen3:8b@bbbbbbbbbbbb" in second.error_message


@pytest.fixture
def desk(ollama_server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path) -> Path:
    project = write_project(tmp_path / "support-desk")
    monkeypatch.chdir(project.root)
    agent = project.root / "agents/local/agent.yaml"
    agent.parent.mkdir(parents=True)
    agent.write_text(f"name: local\nversion: 0.1.0\nmodel: qwen3:8b\nendpoint: {ollama_server}\n")
    return project.jobs_dir


def _run(*args: str, answer: str | None = None) -> tuple[int, str]:
    result = CliRunner().invoke(
        app, ["run", "--task", "refund", "--agent", "local", *args], input=answer
    )
    if result.exception is not None and not isinstance(result.exception, SystemExit):
        raise result.exception
    return result.exit_code, result.output


def test_plural_run_asks_once_for_a_new_local_model(
    desk: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, output = _run()
    assert code == 1
    assert "Agent local runs a local model you have not accepted yet:" in output
    assert "weights: ollama:qwen3:8b@aaaaaaaaaaaa" in output
    assert "pass --yes to run without a prompt" in output
    assert _Ollama.answered == 0

    monkeypatch.setattr("plural.cli.run_commands._interactive", lambda: True)
    code, output = _run(answer="n\n")
    assert code == 1
    assert "Nothing ran." in output
    assert _Ollama.answered == 0

    _run(answer="y\n")
    assert _Ollama.answered > 0
    assert any(desk.iterdir())

    code, output = _run()
    assert "as you accepted on" in output
    assert "Is this the model" not in output


def test_plural_run_warns_loudly_when_an_accepted_model_changes(
    desk: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("plural.cli.run_commands._interactive", lambda: True)
    _run(answer="y\n")
    _Ollama.digest = "b" * 64

    code, output = _run(answer="n\n")

    assert code == 1
    assert "WARNING: THE MODEL BEHIND AGENT LOCAL HAS CHANGED." in output
    assert "it was ollama:qwen3:8b@aaaaaaaaaaaa" in output
    assert "weights: ollama:qwen3:8b@bbbbbbbbbbbb" in output


def test_plural_run_yes_skips_the_prompt_without_remembering(desk: Path) -> None:
    _run("--yes")
    assert _Ollama.answered > 0

    code, output = _run()
    assert code == 1
    assert "you have not accepted yet" in output


class _Mlx(BaseHTTPRequestHandler):
    """An mlx_lm.server whose answers come from the model it actually runs.

    ``serves`` maps a requested name to the model that answers it; after
    ``swap_after`` answers to the Harness, ``swap_to`` answers every name.
    """

    version = "0.31.3"
    serves: dict[str, str] = {}
    swap_after: int | None = None
    swap_to = ""
    answered = 0

    def _send(self, body: dict[str, Any], status: int = 200) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == "/v1/models":
            self._send({"data": [{"id": name} for name in type(self).serves]})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self) -> None:
        cls = type(self)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        actual = cls.serves.get(body["model"], body["model"])
        prompt = body["messages"][-1]["content"]
        if "max_tokens" not in body:
            cls.answered += 1
            if cls.swap_after is not None and cls.answered >= cls.swap_after:
                cls.serves = {name: cls.swap_to for name in cls.serves}
        self._send(
            _reply(
                body["model"],
                system_fingerprint=f"{cls.version}-0.32.1-macOS-15",
                choices=[{"message": {"role": "assistant", "content": f"PAID {actual} {prompt}"}}],
            )
        )

    def log_message(self, *_args: object) -> None:
        return


SMALL, LARGE = "mlx-community/Qwen3-8B-4bit", "mlx-community/Qwen3.8-27B-4bit"


@pytest.fixture
def mlx(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[str]:
    _Mlx.version, _Mlx.swap_after, _Mlx.swap_to, _Mlx.answered = "0.31.3", None, "", 0
    _Mlx.serves = {SMALL: SMALL, LARGE: LARGE}
    hf_home = tmp_path / "hf"
    _cache(hf_home / "hub", SMALL, [[8_000, 1_024_000]], bits=4)
    _cache(hf_home / "hub", LARGE, [[27_400, 1_000_000]], bits=4)
    monkeypatch.setenv("HF_HOME", str(hf_home))
    monkeypatch.delenv("PLURAL_API_KEY", raising=False)
    monkeypatch.delenv("PLURAL_GATEWAY_URL", raising=False)
    monkeypatch.setenv("PLURAL_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.chdir(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Mlx)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()


def test_an_honest_mlx_server_is_accepted_then_known(mlx: str, tmp_path: Path) -> None:
    store = KnownModels(tmp_path / "known.json")
    first = inspect_local_model(mlx, SMALL)

    assert first.method == "weights"
    assert first.behavior is not None
    assert first.size == "8.2B"
    assert store.lookup(first) == ("new", None)
    store.remember(first)
    again = inspect_local_model(mlx, SMALL)
    assert again.fingerprint == first.fingerprint
    assert store.lookup(again)[0] == "known"


def test_a_server_answering_one_name_with_another_model_is_caught(mlx: str, tmp_path: Path) -> None:
    store = KnownModels(tmp_path / "known.json")
    store.remember(inspect_local_model(mlx, LARGE))
    honest = inspect_local_model(mlx, SMALL)

    _Mlx.serves[SMALL] = LARGE
    lying = inspect_local_model(mlx, SMALL)

    # The cache still says 8B; the answers are the 27B's.
    assert lying.weights == honest.weights
    assert lying.fingerprint != honest.fingerprint
    status, record = store.lookup(lying)
    assert status == "answers_like"
    assert record is not None and record["requested"] == LARGE
    message = unverified_message("small-local", lying, status, record)
    assert "is not what its name says" in message


def test_an_alias_of_the_same_weights_is_not_an_impostor(mlx: str, tmp_path: Path) -> None:
    store = KnownModels(tmp_path / "known.json")
    store.remember(inspect_local_model(mlx, SMALL))

    alias = inspect_local_model(mlx.replace("127.0.0.1", "localhost"), SMALL)

    assert store.lookup(alias) == ("new", None)


def test_a_new_server_version_that_answers_differently_is_serving_changed(
    mlx: str, tmp_path: Path
) -> None:
    store = KnownModels(tmp_path / "known.json")
    store.remember(inspect_local_model(mlx, SMALL))

    _Mlx.version = "0.32.0"
    _Mlx.serves[SMALL] = "a requantized 8B"
    status, record = store.lookup(inspect_local_model(mlx, SMALL))

    assert status == "serving_changed"
    assert record is not None and record["server_version"] == "0.31.3"


def test_a_remote_endpoint_is_identified_by_its_answers_alone(tmp_path: Path) -> None:
    _cache(tmp_path, SMALL, [[8_000, 1_024_000]], bits=4)

    identity = inspect_local_model(
        "http://gpu-box.lan:2080/v1", SMALL, http=_mlx(tmp_path), hf_hub=tmp_path
    )

    assert identity.method == "behavior"
    assert identity.weights is None
    assert identity.behavior is not None
    assert any("not on this machine" in line for line in identity.describe())


def test_an_mlx_model_swapped_mid_job_fails_the_next_trial(mlx: str) -> None:
    _Mlx.swap_after, _Mlx.swap_to = 1, LARGE
    agent = Agent(name="small-local", model=SMALL, endpoint=mlx)

    result = Job(_task(), agents=[agent], attempts=2, allow_local_models=True).run()

    first, second = result.trials
    assert first.score == 1.0, first.error_message
    assert second.error_message is not None
    assert "changed after the Job started" in second.error_message


def test_plural_run_refuses_a_model_that_answers_like_another(
    mlx: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = write_project(tmp_path / "support-desk")
    monkeypatch.chdir(project.root)
    agent = project.root / "agents/local/agent.yaml"
    agent.parent.mkdir(parents=True)
    agent.write_text(f"name: local\nversion: 0.1.0\nmodel: {SMALL}\nendpoint: {mlx}\n")
    known_models().remember(inspect_local_model(mlx, LARGE))
    monkeypatch.setattr("plural.cli.run_commands._interactive", lambda: True)
    _Mlx.serves[SMALL] = LARGE

    code, output = _run(answer="y\n")

    assert code == 1
    assert "WARNING: AGENT LOCAL'S MODEL IS NOT WHAT ITS NAME SAYS." in output
    assert f"it answers exactly like {LARGE}" in output
    assert "Is this the model" not in output
    assert _Mlx.answered == 0
