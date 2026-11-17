# bare-files

A Plural project with a **bare Environment**: no Apps, only a workspace, the Task's files,
and a Runtime. The Agent works with its Harness's own tools, and every tool call is a step
in the Trial (`kind: harness_tool`). The Verifier checks two things: the final answer, as
`episode.answer`, and one file the Agent wrote, read through `episode.workspace`.

```bash
plural benchmark validate bare-files
plural run -b bare-files -a files-claude   # Claude Code: Read, Write, Bash
plural run -b bare-files -a files-codex    # Codex: shell, apply_patch
plural run -b bare-files -a files-native   # the native loop: read_file, write_file, list_files, run
```

The native loop brings tools of its own only in an Environment with no Apps, like this one.
In an Environment with Apps, it uses the Apps' actions instead.
