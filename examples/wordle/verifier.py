from pathlib import Path

from plural import EvidenceContract
from plural.verifiers import DeterministicVerifier

check = Path(__file__).with_name("verify.py").read_text(encoding="utf-8")

solved = DeterministicVerifier(
    name="solved",
    check=("python", "-c", check),
    evidence=EvidenceContract(
        observation_paths=("solved", "text"),
        state_paths=("solved", "guesses"),
    ),
)
