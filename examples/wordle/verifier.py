from verify import solved as check_solved

from plural import DeterministicVerifier

solved = DeterministicVerifier(name="solved", check=check_solved)
