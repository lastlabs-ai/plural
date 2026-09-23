# Support triage

Measures whether an Agent can triage a support ticket: read it and its policy, choose
billing, technical, or account, draft a reply, and resolve it.

Each Task is one ticket. The `correct-category` Verifier scores 1 when the ticket is
resolved with the expected category and a non-empty reply, and 0 otherwise. The
Benchmark score is the mean over Tasks.

Three tickets are enough to check an Agent's wiring, not to compare models. The score
does not judge the quality of the reply, only that one was written.
