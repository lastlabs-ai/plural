from plural import Agent

agent = Agent(
    model="openai/gpt-5.6-luna",
    instructions="Play Wordle with the guess action. Stop as soon as the board is solved.",
)
