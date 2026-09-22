from verify import solved as check_solved
from verify import turns as check_turns

from plural import DeterministicVerifier

solved = DeterministicVerifier(
    name="solved",
    check=check_solved,
)
turns = DeterministicVerifier(
    name="turns",
    check=check_turns,
)
