# inspector

One App, `inspector`, that holds a finished Job's evidence. Its State names the Job
and the failed Trial to explain. Its tools read the Trial's steps, the model's
context, the Apps' State, the Verifier's output and code, and the rest of the Job.
`fork` reruns the Trial from a step with one thing changed, beside unchanged
controls, and `record_finding` ends the episode with a cause and its evidence.

Every tool is read-only except `fork`, which spends from the State's budget. The
Plural key forks run with is the Agent's `INSPECTOR_API_KEY` credential, which
reaches only the App host.
