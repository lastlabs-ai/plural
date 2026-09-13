from plural import EvidenceContract
from plural.verifiers import DeterministicVerifier

solved = DeterministicVerifier(
    name="solved",
    check=("python", "verify.py"),
    evidence=EvidenceContract(
        observation_paths=("solved", "text"),
        state_paths=("solved", "guesses"),
    ),
)
