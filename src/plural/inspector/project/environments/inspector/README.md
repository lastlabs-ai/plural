# inspector

One App, `inspector`, that holds a finished Job's evidence. Its State names the Job
and the failed Trial to explain. Its tools read the Trial's steps, the model's
context, the Apps' State, the Verifier's output and code, and the rest of the Job.
`fork` reruns the Trial from a step with one thing changed, beside unchanged
controls, and `record_finding` ends the episode with a cause and its evidence.

Every tool is read-only except `fork`, which spends from the State's budget. Forks
call models with the Agent's `INSPECTOR_FORK_KEY` credential: a gateway-only key
minted for this one inspection of one Job and revoked when it ends. It reaches only
the App host, and is never your own key. Without it, forks are off.
