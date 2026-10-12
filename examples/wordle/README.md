# wordle

A Plural project. Each resource is a directory named after it:

```
environments/<name>/   environment.yaml, environment.py, README.md, resources/
tasks/<name>/          task.yaml, instruction.md, resources/
verifiers/<name>/      verifier.yaml, verify.py
harnesses/<name>/      harness.yaml
agents/<name>/         agent.yaml
benchmarks/<name>/     benchmark.yaml, README.md
```

Common commands, run from anywhere inside this directory:

```bash
plural env init <name>
plural verifier init <name>
plural task init <name> --environment <env> --verifier <verifier>
plural task validate <name>
plural run --task <name> --model <model>
plural project init wordle --push   # register this project with Plural
plural task push <name> --with-deps
```
