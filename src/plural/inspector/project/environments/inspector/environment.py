"""The Inspector's App: the evidence tools are defined in plural.inspector.app."""

from plural.inspector.app import InspectorApp


class Inspector(InspectorApp):
    """One Job's evidence, read-only, with forks to test a cause and record_finding."""

    name = "inspector"
