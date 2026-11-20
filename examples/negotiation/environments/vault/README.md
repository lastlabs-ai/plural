# vault

One App, `vault`, that two partners share. `seat_1` holds the first two digits of a
four-digit code and `seat_2` the last two. They take turns.

- `post(message)` writes on the board both partners read.
- `open_vault(code)` tries the full code. Three wrong tries lock the vault.

Each seat's view shows its own two digits, the tries and moves left, and the board.
