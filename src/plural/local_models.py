"""What model an endpoint Agent's server is actually running.

An endpoint Agent's ``model`` is free text the server receives as is, so
nothing in the name proves what answers. A server may list every model it
could load, echo back whatever name it was asked for, or serve its one loaded
model under any name. Before a run, Plural asks the server what it has
loaded, reads the weights where they are on this machine, and reduces what it
learns to one fingerprint, the way SSH identifies a host by its key.

The facts come from the strongest source the server offers:

``server``
    The server reports the loaded model: Ollama's ``/api/show``, vLLM's
    ``root``, llama.cpp's ``/props``, or LM Studio's ``/api/v0/models``.
``weights``
    The weights are in this machine's Hugging Face cache, as for
    ``mlx_lm.server``, which loads the repository a request names. Plural
    counts their parameters from the safetensors headers.
``behavior``
    Nothing else is known, so Plural hashes the model's greedy answers to a
    few fixed prompts. This is the weakest: it tells two models apart, not
    which one either is.

None of this proves what weights a server you do not control is running. It
makes a mislabeled run visible before it starts, instead of results recorded
under the wrong name.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import struct
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx

from plural.common import FrozenModel

ServerKind = Literal["ollama", "vllm", "llama.cpp", "lm-studio", "mlx-lm", "openai-compatible"]
Method = Literal["server", "weights", "behavior"]
Trust = Literal["confirmed", "known", "allowed", "recorded"]
"""How a run came to use a model: ``confirmed`` at a prompt, ``known`` from a
fingerprint confirmed before, ``allowed`` by ``allow_local_models`` or
``--yes`` without review, and ``recorded`` when nothing asked."""

PROBES = (
    "Continue this sequence with exactly ten more words, no explanation: copper, lantern, "
    "orbit, velvet,",
    "Write one sentence about a lighthouse keeper who collects keys.",
    "List five invented city names, comma separated, nothing else.",
)
# A model whose size is in its name must count within this share of it.
SIZE_TOLERANCE = 0.3
_SIZE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*b(?![a-z])", re.IGNORECASE)
_MLX_FINGERPRINT = re.compile(r"^(\d+\.\d+\.\d+)-(\d+\.\d+\.\d+)-")


class LocalModelError(RuntimeError):
    """A local model that is unverified, unreachable, or not what its name says."""


class LocalModelIdentity(FrozenModel):
    """What an endpoint Agent's server answered with, as far as Plural could tell."""

    endpoint: str
    requested: str
    """The model name the Agent sends."""
    server: ServerKind
    server_version: str | None = None
    served: str | None = None
    """The name the server answered as, when it says."""
    weights: str | None = None
    """The weights the server runs: a Hugging Face repository and revision, an
    Ollama digest, or a file."""
    parameters: int | None = None
    quantization: str | None = None
    method: Method
    fingerprint: str
    """``SHA256:`` and the base64 digest of the facts above, like an SSH key's."""
    warnings: tuple[str, ...] = ()
    """Where the name and what answers disagree, such as a size in the name
    the weights do not have."""
    trust: Trust | None = None

    @property
    def size(self) -> str | None:
        """The parameter count as people say it, such as ``8.2B``."""
        if self.parameters is None:
            return None
        billions = self.parameters / 1e9
        return f"{billions:.1f}B" if billions >= 1 else f"{self.parameters / 1e6:.0f}M"

    def describe(self) -> list[str]:
        """Each known fact as ``label: value``, for a person to check.

        Returns:
            One line per fact, warnings last.
        """
        version = f" {self.server_version}" if self.server_version else ""
        lines = [
            f"server: {self.server}{version} at {self.endpoint}",
            f"requested: {self.requested}",
        ]
        if self.served and self.served != self.requested:
            lines.append(f"answered as: {self.served}")
        if self.weights:
            lines.append(f"weights: {self.weights}")
        if self.size:
            lines.append(f"parameters: {self.size}")
        if self.quantization:
            lines.append(f"quantization: {self.quantization}")
        lines.append(f"fingerprint: {self.fingerprint} (from the {_METHODS[self.method]})")
        lines.extend(f"warning: {item}" for item in self.warnings)
        return lines


_METHODS: dict[str, str] = {
    "server": "model the server reports loaded",
    "weights": "weight files on this machine",
    "behavior": "model's answers to fixed prompts; the server reports nothing about its model",
}


def inspect_local_model(
    endpoint: str,
    model: str,
    *,
    api_key: str | None = None,
    probe: bool = True,
    http: httpx.Client | None = None,
    hf_hub: Path | None = None,
) -> LocalModelIdentity:
    """Ask ``endpoint`` what answers for ``model``, and fingerprint it.

    Args:
        endpoint: The OpenAI-compatible base URL, such as ``http://localhost:11434/v1``.
        model: The name the Agent sends.
        api_key: The endpoint's key, when it needs one.
        probe: Send a one-token request to learn the name the server answers
            as, and fall back to fingerprinting behavior. Without it, only
            what the server reports is read, which is cheap enough to repeat.
        http: HTTP client, injectable for tests.
        hf_hub: The Hugging Face cache, by default ``$HF_HOME/hub``.

    Returns:
        The identity.

    Raises:
        LocalModelError: When the endpoint cannot be reached.
    """
    if http is None:
        with httpx.Client(timeout=httpx.Timeout(10.0, read=600.0)) as owned:
            return inspect_local_model(
                endpoint, model, api_key=api_key, probe=probe, http=owned, hf_hub=hf_hub
            )
    client = http
    base = endpoint.rstrip("/")
    root = base.removesuffix("/v1")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    hub = hf_hub or Path(os.environ.get("HF_HOME", Path.home() / ".cache/huggingface")) / "hub"

    def get(url: str) -> Any:
        try:
            response = client.get(url, headers=headers)
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    try:
        reachable = client.get(f"{base}/models", headers=headers)
    except httpx.HTTPError as exc:
        raise LocalModelError(
            f"Cannot reach the model server at {endpoint}: {exc}. Start it, or fix the "
            "Agent's endpoint."
        ) from None
    try:
        listed = reachable.json() if reachable.status_code == 200 else None
    except ValueError:
        listed = None
    data = listed.get("data") if isinstance(listed, dict) else None
    entries = [item for item in data or [] if isinstance(item, dict)]
    ids = [str(item.get("id")) for item in entries]
    entry = next((item for item in entries if item.get("id") == model), None)

    facts: dict[str, Any] = {}
    server: ServerKind = "openai-compatible"
    version: str | None = None
    weights: str | None = None
    parameters: int | None = None
    quantization: str | None = None
    method: Method = "server"
    warnings: list[str] = []

    ollama = get(f"{root}/api/version")
    owners = {str(item.get("owned_by") or "") for item in entries}
    if isinstance(ollama, dict) and "version" in ollama and get(f"{root}/api/tags") is not None:
        server, version = "ollama", str(ollama["version"])
        shown = _post_json(client, f"{root}/api/show", {"model": model}, headers)
        tags = (get(f"{root}/api/tags") or {}).get("models", [])
        tag = next(
            (
                item
                for item in tags
                if model in {item.get("name"), item.get("model")}
                or f"{model}:latest" in {item.get("name"), item.get("model")}
            ),
            None,
        )
        if shown is None or tag is None:
            raise LocalModelError(
                f"Ollama at {endpoint} has no model {model!r}. Pull it with "
                f"`ollama pull {model}`, or set the Agent's model to one of: "
                f"{', '.join(str(item.get('name')) for item in tags) or 'none'}."
            )
        details = shown.get("details") or {}
        info = shown.get("model_info") or {}
        parameters = _int(info.get("general.parameter_count")) or _billions(
            details.get("parameter_size")
        )
        quantization = details.get("quantization_level") or None
        digest = str(tag.get("digest") or "")
        weights = f"ollama:{tag.get('name')}@{digest[:12]}" if digest else f"ollama:{model}"
        facts = {"digest": digest, "parameters": parameters, "quantization": quantization}
    elif "vllm" in owners:
        server = "vllm"
        version = str((get(f"{root}/version") or {}).get("version") or "") or None
        if entry is None:
            raise LocalModelError(_unlisted(endpoint, model, ids))
        weights = str(entry.get("root") or model)
        cached = _hf_weights(hub, weights)
        if cached is not None:
            weights, parameters, quantization, files = cached
            method, facts = "weights", {"weights": weights, "files": files}
        else:
            facts = {"weights": weights}
    elif "llamacpp" in owners or any("meta" in item for item in entries):
        server = "llama.cpp"
        props = get(f"{root}/props") or {}
        version = str(props.get("build_info") or "") or None
        loaded = entry or (entries[0] if entries else {})
        meta = loaded.get("meta") or {}
        parameters = _int(meta.get("n_params"))
        path = str(props.get("model_path") or loaded.get("id") or "")
        weights = Path(path).name or None
        quantization = _gguf_quantization(weights)
        facts = {"weights": weights, "parameters": parameters, "size": meta.get("size")}
        if entry is None and ids:
            warnings.append(
                f"llama.cpp serves one model, {ids[0]}, whatever name a request gives it."
            )
    elif (studio := get(f"{root}/api/v0/models")) is not None:
        server = "lm-studio"
        models = [item for item in studio.get("data", []) if isinstance(item, dict)]
        found = next((item for item in models if item.get("id") == model), None)
        if found is None:
            raise LocalModelError(_unlisted(endpoint, model, [str(m.get("id")) for m in models]))
        quantization = found.get("quantization") or None
        weights = f"lmstudio:{found.get('publisher') or ''}/{model}".replace(":/", ":")
        facts = {
            "weights": weights,
            "arch": found.get("arch"),
            "quantization": quantization,
            "context": found.get("max_context_length"),
        }

    served: str | None = None
    if probe:
        answer = _post_json(
            client,
            f"{base}/chat/completions",
            {
                "model": model,
                "max_tokens": 1,
                "temperature": 0,
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers,
            timeout=600,
        )
        if answer is None:
            raise LocalModelError(
                f"The model server at {endpoint} refused a request for {model!r}."
                + (f" It lists: {', '.join(ids)}." if ids else "")
            )
        served = str(answer.get("model") or "") or None
        mlx = _MLX_FINGERPRINT.match(str(answer.get("system_fingerprint") or ""))
        if server == "openai-compatible" and mlx:
            server, version = "mlx-lm", mlx.group(1)
        if served and not _same_name(served, model) and server != "llama.cpp":
            warnings.append(f"asked for {model}, the server answered as {served}")

    if server in {"mlx-lm", "openai-compatible"}:
        cached = _hf_weights(hub, model)
        if cached is not None:
            weights, parameters, quantization, files = cached
            method, facts = "weights", {"weights": weights, "files": files}
        elif probe:
            method = "behavior"
            facts = {"server": server, "answers": _behavior(client, base, model, headers)}
        else:
            method, facts = "behavior", {"server": server, "unknown": model}

    claimed = claimed_size(model)
    if claimed is not None and parameters:
        actual = parameters / 1e9
        if abs(actual - claimed) / claimed > SIZE_TOLERANCE:
            warnings.append(
                f"the name says {claimed:g}B, but the weights hold about {actual:.1f}B parameters"
            )
    return LocalModelIdentity(
        endpoint=base,
        requested=model,
        server=server,
        server_version=version,
        served=served,
        weights=weights,
        parameters=parameters,
        quantization=quantization,
        method=method,
        fingerprint=_fingerprint(method, facts),
        warnings=tuple(warnings),
    )


def claimed_size(name: str) -> float | None:
    """The parameter count, in billions, a model's name claims, such as 8 for ``qwen3:8b``.

    Returns:
        The first size in the name, or ``None`` when it names none.
    """
    match = _SIZE.search(name.rsplit("/", 1)[-1].replace("_", "-"))
    return float(match.group(1)) if match else None


class KnownModels:
    """Fingerprints a person accepted, by endpoint and model name, like SSH's ``known_hosts``.

    Args:
        path: The JSON file that holds them.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _key(identity: LocalModelIdentity) -> str:
        return f"{identity.endpoint} {identity.requested}"

    def lookup(
        self, identity: LocalModelIdentity
    ) -> tuple[Literal["new", "known", "changed"], dict[str, Any] | None]:
        """Whether this fingerprint was accepted for this endpoint and name before.

        Returns:
            ``known`` when it matches the accepted one, ``changed`` when another
            was accepted, ``new`` otherwise; and the accepted record, if any.
        """
        record = self._read().get(self._key(identity))
        if record is None:
            return "new", None
        if record.get("fingerprint") == identity.fingerprint:
            return "known", record
        return "changed", record

    def remember(self, identity: LocalModelIdentity) -> None:
        """Accept ``identity``'s fingerprint for its endpoint and name."""
        data = self._read()
        data[self._key(identity)] = {
            "fingerprint": identity.fingerprint,
            "server": identity.server,
            "weights": identity.weights,
            "parameters": identity.parameters,
            "quantization": identity.quantization,
            "accepted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def known_models(environ: Mapping[str, str] | None = None) -> KnownModels:
    """This user's accepted model fingerprints, in Plural's config folder.

    Returns:
        The store.
    """
    from plural.auth import config_home

    return KnownModels(config_home(environ) / "known_models.json")


Decide = Callable[
    [str, LocalModelIdentity, Literal["new", "known", "changed"], "dict[str, Any] | None"], Trust
]
"""Given an Agent's name, its model's identity, whether its fingerprint was
accepted before, and the accepted record, how the run trusts it; or raise
:class:`LocalModelError` to stop."""


def review_local_models(
    agents: Iterable[Any],
    environ: Mapping[str, str],
    decide: Decide,
    *,
    known: KnownModels | None = None,
) -> dict[str, LocalModelIdentity]:
    """Inspect every endpoint Agent's model and let ``decide`` accept or refuse it.

    A fingerprint ``decide`` confirms is remembered, so the next run of the
    same model goes ahead without asking.

    Args:
        agents: The Job's Agent bindings; those without an endpoint are skipped.
        environ: Where each endpoint's key is read from.
        decide: How the run trusts each model, or raises to stop.
        known: Accepted fingerprints, by default this user's.

    Returns:
        Each endpoint Agent's identity by Agent name, with its trust.
    """
    store = known or known_models(environ)
    identities: dict[str, LocalModelIdentity] = {}
    inspected: dict[tuple[str, str], LocalModelIdentity] = {}
    for binding in agents:
        definition = binding.agent
        if definition.endpoint is None:
            continue
        key = environ.get(definition.endpoint_key) if definition.endpoint_key else None
        if definition.endpoint_key and not key:
            # The run refuses it for its missing key, which is the clearer error.
            continue
        place = (definition.endpoint, binding.model)
        if place not in inspected:
            inspected[place] = inspect_local_model(definition.endpoint, binding.model, api_key=key)
        identity = inspected[place]
        status, record = store.lookup(identity)
        trust = decide(binding.name, identity, status, record)
        if trust == "confirmed":
            store.remember(identity)
        identities[binding.name] = identity.model_copy(update={"trust": trust})
    return identities


def unverified_message(
    name: str,
    identity: LocalModelIdentity,
    status: Literal["new", "known", "changed"],
    record: Mapping[str, Any] | None,
) -> str:
    """Why a run stopped before using a model nobody accepted.

    Returns:
        The facts to check, and how to go ahead.
    """
    if status == "changed" and record is not None:
        head = (
            f"Agent {name!r}'s model is not the one accepted on "
            f"{str(record.get('accepted_at', ''))[:10]}: its fingerprint was "
            f"{record.get('fingerprint')} ({record.get('weights') or 'unknown weights'}), and "
            "is now:"
        )
    else:
        head = f"Agent {name!r} runs a local model nobody has accepted yet:"
    return "\n".join(
        [head, *(f"  {line}" for line in identity.describe())]
        + [
            "If this is the model you mean to evaluate, accept it with `plural run`, which "
            "asks once and remembers, or pass allow_local_models=True."
        ]
    )


def _post_json(
    client: httpx.Client,
    url: str,
    body: dict[str, Any],
    headers: Mapping[str, str],
    *,
    timeout: float = 30,
) -> dict[str, Any] | None:
    try:
        response = client.post(url, json=body, headers=dict(headers), timeout=timeout)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _behavior(client: httpx.Client, base: str, model: str, headers: Mapping[str, str]) -> str:
    outputs = []
    for prompt in PROBES:
        answer = _post_json(
            client,
            f"{base}/chat/completions",
            {
                "model": model,
                "temperature": 0,
                "seed": 0,
                "max_tokens": 48,
                "messages": [{"role": "user", "content": f"/no_think {prompt}"}],
            },
            headers,
            timeout=600,
        )
        choices = (answer or {}).get("choices") or [{}]
        outputs.append(str((choices[0].get("message") or {}).get("content") or ""))
    return hashlib.sha256("\x1e".join(outputs).encode()).hexdigest()


def _hf_weights(hub: Path, repo: str) -> tuple[str, int, str | None, list[str]] | None:
    """The cached weights of Hugging Face ``repo``, or ``None`` when it is not cached.

    Returns:
        ``hf:<repo>@<revision>``, the parameter count, the quantization, and
        the weight files' SHA-256s.
    """
    if "/" not in repo or ":" in repo:
        return None
    folder = hub / f"models--{repo.replace('/', '--')}"
    ref = folder / "refs" / "main"
    try:
        revision = ref.read_text().strip()
    except OSError:
        return None
    snapshot = folder / "snapshots" / revision
    try:
        config = json.loads((snapshot / "config.json").read_text())
    except (OSError, ValueError):
        config = {}
    bits = (config.get("quantization") or {}).get("bits")
    parameters = 0
    files: list[str] = []
    for path in sorted(snapshot.glob("*.safetensors")):
        blob = path.resolve()
        # The cache names each blob by its SHA-256, so the files need no rehashing.
        files.append(blob.name if len(blob.name) == 64 else _sha256(blob))
        parameters += _safetensors_parameters(blob, bits)
    if not files:
        return None
    return f"hf:{repo}@{revision[:12]}", parameters, f"{bits}-bit" if bits else None, files


def _safetensors_parameters(path: Path, bits: int | None) -> int:
    """Parameters in one safetensors file, counting packed quantized weights unpacked.

    Returns:
        The count.
    """
    with path.open("rb") as handle:
        header = json.loads(handle.read(struct.unpack("<Q", handle.read(8))[0]))
    names = set(header)
    total = 0
    for name, tensor in header.items():
        if name == "__metadata__":
            continue
        stem = name.rsplit(".", 1)[0]
        if name.endswith((".scales", ".biases")) and f"{stem}.weight" in names:
            continue
        count = 1
        for dim in tensor["shape"]:
            count *= dim
        packed = tensor["dtype"] == "U32" and bits and f"{stem}.scales" in names
        total += count * 32 // bits if packed and bits else count
    return total


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 24), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(method: str, facts: Mapping[str, Any]) -> str:
    text = json.dumps({"method": method, **facts}, sort_keys=True, default=str)
    digest = hashlib.sha256(text.encode()).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


def _same_name(served: str, requested: str) -> bool:
    def norm(value: str) -> str:
        return value.lower().removesuffix(":latest").rsplit("/", 1)[-1]

    return norm(served) == norm(requested) or Path(served).name == requested


def _unlisted(endpoint: str, model: str, ids: list[str]) -> str:
    return (
        f"The model server at {endpoint} does not serve {model!r}. It serves: "
        f"{', '.join(ids) or 'nothing'}. Set the Agent's model to one of those."
    )


def _int(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) and value > 0 else None


def _billions(value: Any) -> int | None:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([BM])\s*", str(value or ""), re.IGNORECASE)
    if match is None:
        return None
    scale = 1e9 if match.group(2).upper() == "B" else 1e6
    return int(float(match.group(1)) * scale)


def _gguf_quantization(name: str | None) -> str | None:
    match = re.search(r"(I?Q\d+_[A-Z0-9_]+|F16|BF16|F32)", name or "", re.IGNORECASE)
    return match.group(1).upper() if match else None


__all__ = [
    "KnownModels",
    "LocalModelError",
    "LocalModelIdentity",
    "claimed_size",
    "inspect_local_model",
    "known_models",
    "review_local_models",
    "unverified_message",
]
