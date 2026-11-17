# bare-files

A Plural project with a **bare Environment**: no Apps, only a workspace, the Task's files,
and a Runtime. The Agent works with its Harness's own tools, and every tool call is a step
in the Trial (`kind: harness_tool`). The Verifier checks two things: the final answer, as
`episode.answer`, and one file the Agent wrote, read through `episode.workspace`.

```bash
plural benchmark validate bare-files
plural run -b bare-files -a files-claude   # Claude Code: Read, Write, Bash
plural run -b bare-files -a files-codex    # Codex: shell, apply_patch
plural run -b bare-files -a files-native   # the native loop: no tools, so no file
```

The native loop has no tools of its own, so it can give the right answer but can't write
`march-total.txt`: it passes `answer_correct` and fails the `file_correct` gate.
