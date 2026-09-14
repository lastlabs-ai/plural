from plural import Runtime
from wordle import Wordle

environment = Wordle(runtime=Runtime.local()).package(("python", "commands.py"))
