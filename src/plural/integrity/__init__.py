"""Keeping scores honest: leak scans before a run, detectors after one.

:mod:`plural.integrity.leaks` scans what an Agent can see for the answer key,
solution files, Verifier code, and git history. :mod:`plural.integrity.detectors`
reads a recorded Trial for signs the score was gamed. Both report
:class:`~plural.jobs.IntegrityFinding` evidence; neither changes a score.
"""
