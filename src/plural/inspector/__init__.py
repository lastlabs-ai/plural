"""The Inspector: Plural's investigating agent, built on Plural.

The Inspector is an Agent with the native Harness, in an Environment whose App
exposes one Job's evidence as read-only tools. ``plural job inspect`` runs it on
a Job's failed dev Trials, and each episode records one
:class:`~plural.inspector.findings.Finding`. Import from the submodules:

- :mod:`plural.inspector.causes`: the cause dimensions, which a project extends.
- :mod:`plural.inspector.evidence`: what the evidence tools read, computed in code.
- :mod:`plural.inspector.signals`: ``@signal`` plugins that point at likely causes.
- :mod:`plural.inspector.findings`: Findings, their status, and the breakdown.
- :mod:`plural.inspector.run`: running the Inspector on a Job, or one question.
- :mod:`plural.inspector.revise`: turning a Finding into a new Agent version.
- :mod:`plural.inspector.report`: ``plural job report``.
- :mod:`plural.inspector.faults`: the fault injector that builds inspector-bench.
"""
