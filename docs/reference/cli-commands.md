# Generated CLI command reference

This file is generated from the Typer application. Do not edit it by hand.
Run `uv run python scripts/generate_cli_reference.py` after changing the CLI.

## `plural`

```text
                                                                                
 Usage: plural [OPTIONS] COMMAND [ARGS]...                                      
                                                                                
 Build, validate, inspect, and run reproducible Plural packages.                
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --api-url                   <str>  Hosted API base URL.                      │
│ --org                       <str>  Organization override.                    │
│ --project                   <str>  Project override.                         │
│ --profile                   <str>  Named CLI profile.                        │
│ --install-completion               Install completion for the current shell. │
│ --show-completion                  Show completion for the current shell, to │
│                                    copy it or customize the installation.    │
│ --help                             Show this message and exit.               │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ run        Validate, lock, and execute a local client-orchestrated job.      │
│ auth       Authenticate without entering passwords.                          │
│ org        Inspect and select organizations.                                 │
│ project    Inspect and select projects.                                      │
│ env        Manage environment packages.                                      │
│ harness    Manage immutable agent harness packages.                          │
│ benchmark  Manage ordered benchmark definitions.                             │
│ agent      Inspect agents and local agent configs.                           │
│ runtime    Inspect execution-provider integration points.                    │
│ job        Inspect and control jobs.                                         │
│ trial      Inspect immutable job trials.                                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural agent`

```text
                                                                                
 Usage: plural agent [OPTIONS] COMMAND [ARGS]...                                
                                                                                
 Inspect agents and local agent configs.                                        
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ init  Create a local agent config with exactly one harness binding.          │
│ list  List local agent configs; hosted listing follows in the backend phase. │
│ show  Show a validated local agent config.                                   │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural agent init`

```text
                                                                                
 Usage: plural agent init [OPTIONS] [path]                                      
                                                                                
 Create a local agent config with exactly one harness binding.                  
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: agent.yaml]                                    │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│    --name                    <str>   [default: agent]                        │
│ *  --model                   <str>   [required]                              │
│    --environment     -e      <path>  [default: environment.yaml]             │
│    --harness                 <str>   [default: harness.yaml]                 │
│    --harness-digest          <str>                                           │
│    --secret                  <str>                                           │
│    --force                                                                   │
│    --help                            Show this message and exit.             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural agent list`

```text
                                                                                
 Usage: plural agent list [OPTIONS] [path]                                      
                                                                                
 List local agent configs; hosted listing follows in the backend phase.         
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: .]                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural agent show`

```text
                                                                                
 Usage: plural agent show [OPTIONS] [path]                                      
                                                                                
 Show a validated local agent config.                                           
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: agent.yaml]                                    │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural auth`

```text
                                                                                
 Usage: plural auth [OPTIONS] COMMAND [ARGS]...                                 
                                                                                
 Authenticate without entering passwords.                                       
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ login   Authenticate with a browser device flow.                             │
│ logout  Revoke stored tokens and remove local credentials.                   │
│ status  Check whether the current profile is authenticated.                  │
│ whoami  Show the hosted identity for the current credential.                 │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural auth login`

```text
                                                                                
 Usage: plural auth login [OPTIONS]                                             
                                                                                
 Authenticate with a browser device flow.                                       
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --no-browser          Do not open a browser.                                 │
│ --help                Show this message and exit.                            │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural auth logout`

```text
                                                                                
 Usage: plural auth logout [OPTIONS]                                            
                                                                                
 Revoke stored tokens and remove local credentials.                             
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural auth status`

```text
                                                                                
 Usage: plural auth status [OPTIONS]                                            
                                                                                
 Check whether the current profile is authenticated.                            
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural auth whoami`

```text
                                                                                
 Usage: plural auth whoami [OPTIONS]                                            
                                                                                
 Show the hosted identity for the current credential.                           
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural benchmark`

```text
                                                                                
 Usage: plural benchmark [OPTIONS] COMMAND [ARGS]...                            
                                                                                
 Manage ordered benchmark definitions.                                          
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ init      Create an ordered benchmark tied to an exact environment revision. │
│ validate  Strictly validate a benchmark and optional environment ownership.  │
│ show      Show a validated local benchmark definition.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural benchmark init`

```text
                                                                                
 Usage: plural benchmark init [OPTIONS] [path]                                  
                                                                                
 Create an ordered benchmark tied to an exact environment revision.             
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: benchmark.yaml]                                │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --name                 <str>   [default: benchmark]                          │
│ --environment  -e      <path>  [default: environment.yaml]                   │
│ --force                                                                      │
│ --help                         Show this message and exit.                   │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural benchmark show`

```text
                                                                                
 Usage: plural benchmark show [OPTIONS] [path]                                  
                                                                                
 Show a validated local benchmark definition.                                   
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: benchmark.yaml]                                │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural benchmark validate`

```text
                                                                                
 Usage: plural benchmark validate [OPTIONS] [path]                              
                                                                                
 Strictly validate a benchmark and optional environment ownership.              
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: benchmark.yaml]                                │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --environment  -e      <path>                                                │
│ --help                         Show this message and exit.                   │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural env`

```text
                                                                                
 Usage: plural env [OPTIONS] COMMAND [ARGS]...                                  
                                                                                
 Manage environment packages.                                                   
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ init      Create environment.yaml, environment.py, tasks.jsonl, and          │
│           Dockerfile.                                                        │
│ validate  Strictly validate a local environment and owned tasks.             │
│ build     Build a deterministic local environment manifest artifact.         │
│ push      Publish the exact local environment revision used by job sync.     │
│ task      Manage environment-owned tasks.                                    │
│ harness   Manage environment-allowed harnesses.                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural env build`

```text
                                                                                
 Usage: plural env build [OPTIONS] [path]                                       
                                                                                
 Build a deterministic local environment manifest artifact.                     
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: .]                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural env harness`

```text
                                                                                
 Usage: plural env harness [OPTIONS] COMMAND [ARGS]...                          
                                                                                
 Manage environment-allowed harnesses.                                          
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ add   Allow one exact harness revision in an environment.                    │
│ list  List exact harness revisions allowed by an environment.                │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural env harness add`

```text
                                                                                
 Usage: plural env harness add [OPTIONS] {harness}                              
                                                                                
 Allow one exact harness revision in an environment.                            
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    harness      <path>  [required]                                         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --environment  -e      <path>  [default: .]                                  │
│ --help                         Show this message and exit.                   │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural env harness list`

```text
                                                                                
 Usage: plural env harness list [OPTIONS]                                       
                                                                                
 List exact harness revisions allowed by an environment.                        
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --environment  -e      <path>  [default: .]                                  │
│ --help                         Show this message and exit.                   │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural env init`

```text
                                                                                
 Usage: plural env init [OPTIONS] [path]                                        
                                                                                
 Create environment.yaml, environment.py, tasks.jsonl, and Dockerfile.          
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   path      <path>  Package directory. [default: .]                          │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --name         <str>  Environment name. [default: environment]               │
│ --force               Replace scaffold files.                                │
│ --help                Show this message and exit.                            │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural env push`

```text
                                                                                
 Usage: plural env push [OPTIONS] [path]                                        
                                                                                
 Publish the exact local environment revision used by job sync.                 
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   path      <path>  Environment package path. [default: .]                   │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural env task`

```text
                                                                                
 Usage: plural env task [OPTIONS] COMMAND [ARGS]...                             
                                                                                
 Manage environment-owned tasks.                                                
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ add   Append a task owned by an environment.                                 │
│ list  List environment-owned tasks in deterministic order.                   │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural env task add`

```text
                                                                                
 Usage: plural env task add [OPTIONS]                                           
                                                                                
 Append a task owned by an environment.                                         
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│    --environment  -e      <path>  [default: .]                               │
│ *  --id                   <str>   [required]                                 │
│ *  --input                <str>   [required]                                 │
│    --help                         Show this message and exit.                │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural env task list`

```text
                                                                                
 Usage: plural env task list [OPTIONS]                                          
                                                                                
 List environment-owned tasks in deterministic order.                           
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --environment  -e      <path>  [default: .]                                  │
│ --help                         Show this message and exit.                   │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural env validate`

```text
                                                                                
 Usage: plural env validate [OPTIONS] [path]                                    
                                                                                
 Strictly validate a local environment and owned tasks.                         
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: .]                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural harness`

```text
                                                                                
 Usage: plural harness [OPTIONS] COMMAND [ARGS]...                              
                                                                                
 Manage immutable agent harness packages.                                       
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ init      Create a harness manifest and local entry point.                   │
│ validate  Strictly validate source trust and package metadata.               │
│ build     Build a deterministic immutable local harness archive.             │
│ test      Run a local package through protocol conformance.                  │
│ publish   Publish a deterministic archive to a local path.                   │
│ add       Add one exact harness revision to an environment allowlist.        │
│ list      List local harness manifests in a directory.                       │
│ inspect   Inspect a validated harness and its effective immutable binding.   │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural harness add`

```text
                                                                                
 Usage: plural harness add [OPTIONS] {harness}                                  
                                                                                
 Add one exact harness revision to an environment allowlist.                    
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    harness      <str>  [required]                                          │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --environment  -e      <path>  [default: .]                                  │
│ --digest               <str>                                                 │
│ --help                         Show this message and exit.                   │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural harness build`

```text
                                                                                
 Usage: plural harness build [OPTIONS] [path]                                   
                                                                                
 Build a deterministic immutable local harness archive.                         
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: .]                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural harness init`

```text
                                                                                
 Usage: plural harness init [OPTIONS] [path]                                    
                                                                                
 Create a harness manifest and local entry point.                               
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: .]                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --name         <str>  [default: harness]                                     │
│ --force                                                                      │
│ --help                Show this message and exit.                            │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural harness inspect`

```text
                                                                                
 Usage: plural harness inspect [OPTIONS] [reference]                            
                                                                                
 Inspect a validated harness and its effective immutable binding.               
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   reference      <str>  [default: .]                                         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --digest        <str>                                                        │
│ --help                 Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural harness list`

```text
                                                                                
 Usage: plural harness list [OPTIONS] [path]                                    
                                                                                
 List local harness manifests in a directory.                                   
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: .]                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural harness publish`

```text
                                                                                
 Usage: plural harness publish [OPTIONS] [path]                                 
                                                                                
 Publish a deterministic archive to a local path.                               
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: .]                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --output        <path>                                                       │
│ --help                  Show this message and exit.                          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural harness test`

```text
                                                                                
 Usage: plural harness test [OPTIONS] [reference]                               
                                                                                
 Run a local package through protocol conformance.                              
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   reference      <str>  [default: .]                                         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --digest              <str>                                                  │
│ --unsafe-local                                                               │
│ --help                       Show this message and exit.                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural harness validate`

```text
                                                                                
 Usage: plural harness validate [OPTIONS] [path]                                
                                                                                
 Strictly validate source trust and package metadata.                           
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: .]                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural job`

```text
                                                                                
 Usage: plural job [OPTIONS] COMMAND [ARGS]...                                  
                                                                                
 Inspect and control jobs.                                                      
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ init     Create a path-based job.yaml.                                       │
│ list     List durable local job records.                                     │
│ show     Show a path-based job config or durable job record.                 │
│ resume   Resume a compatible locked job, skipping successful trials.         │
│ retry    Retry failed trials without creating new Trial identities.          │
│ regrade  Rerun only the isolated verifier over immutable artifacts.          │
│ cancel   Request cancellation for a local job.                               │
│ upload   Replay a stored local job sync without launching hosted execution.  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural job cancel`

```text
                                                                                
 Usage: plural job cancel [OPTIONS] {job_id}                                    
                                                                                
 Request cancellation for a local job.                                          
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    job_id      <str>  [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --store        <path>  [default: .plural/jobs]                               │
│ --help                 Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural job init`

```text
                                                                                
 Usage: plural job init [OPTIONS] [path]                                        
                                                                                
 Create a path-based job.yaml.                                                  
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: job.yaml]                                      │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│    --environment  -e      <path>  [default: environment.yaml]                │
│    --benchmark    -b      <path>  [default: benchmark.yaml]                  │
│ *  --agent                <path>  [required]                                 │
│    --force                                                                   │
│    --help                         Show this message and exit.                │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural job list`

```text
                                                                                
 Usage: plural job list [OPTIONS] [path]                                        
                                                                                
 List durable local job records.                                                
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: .plural/jobs]                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural job regrade`

```text
                                                                                
 Usage: plural job regrade [OPTIONS] {job_id}                                   
                                                                                
 Rerun only the isolated verifier over immutable artifacts.                     
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    job_id      <str>  [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --store        <path>  [default: .plural/jobs]                               │
│ --help                 Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural job resume`

```text
                                                                                
 Usage: plural job resume [OPTIONS] {job_id}                                    
                                                                                
 Resume a compatible locked job, skipping successful trials.                    
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    job_id      <str>  [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --store        <path>  [default: .plural/jobs]                               │
│ --help                 Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural job retry`

```text
                                                                                
 Usage: plural job retry [OPTIONS] {job_id}                                     
                                                                                
 Retry failed trials without creating new Trial identities.                     
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    job_id      <str>  [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --store        <path>  [default: .plural/jobs]                               │
│ --help                 Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural job show`

```text
                                                                                
 Usage: plural job show [OPTIONS] [identifier]                                  
                                                                                
 Show a path-based job config or durable job record.                            
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   identifier      <str>  [default: job.yaml]                                 │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --store        <path>  [default: .plural/jobs]                               │
│ --help                 Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural job upload`

```text
                                                                                
 Usage: plural job upload [OPTIONS] {job_id}                                    
                                                                                
 Replay a stored local job sync without launching hosted execution.             
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    job_id      <str>  [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --store        <path>  [default: .plural/jobs]                               │
│ --help                 Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural org`

```text
                                                                                
 Usage: plural org [OPTIONS] COMMAND [ARGS]...                                  
                                                                                
 Inspect and select organizations.                                              
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ use   Select an organization in the active profile.                          │
│ list  List hosted organizations.                                             │
│ show  Show the resolved organization context.                                │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural org list`

```text
                                                                                
 Usage: plural org list [OPTIONS]                                               
                                                                                
 List hosted organizations.                                                     
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural org show`

```text
                                                                                
 Usage: plural org show [OPTIONS]                                               
                                                                                
 Show the resolved organization context.                                        
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural org use`

```text
                                                                                
 Usage: plural org use [OPTIONS] {organization}                                 
                                                                                
 Select an organization in the active profile.                                  
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    organization      <str>  [required]                                     │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural project`

```text
                                                                                
 Usage: plural project [OPTIONS] COMMAND [ARGS]...                              
                                                                                
 Inspect and select projects.                                                   
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ use   Select a project in the active profile.                                │
│ list  List hosted projects.                                                  │
│ show  Show the resolved project context.                                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural project list`

```text
                                                                                
 Usage: plural project list [OPTIONS]                                           
                                                                                
 List hosted projects.                                                          
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural project show`

```text
                                                                                
 Usage: plural project show [OPTIONS]                                           
                                                                                
 Show the resolved project context.                                             
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural project use`

```text
                                                                                
 Usage: plural project use [OPTIONS] {project}                                  
                                                                                
 Select a project in the active profile.                                        
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    project      <str>  [required]                                          │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural run`

```text
                                                                                
 Usage: plural run [OPTIONS] [job]                                              
                                                                                
 Validate, lock, and execute a local client-orchestrated job.                   
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   job      <path>  Local job.yaml path. [default: job.yaml]                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --agent                        <path>              Override agent config.    │
│ --n-attempts                   <int range> [x>=1]                            │
│ --concurrency                  <int range> [x>=1]                            │
│ --runtime                      <str>                                         │
│ --retry                        <int range> [x>=0]                            │
│ --dry-run                                                                    │
│ --print-config                                                               │
│ --sync            --no-sync                        Opt in to best-effort     │
│                                                    hosted registration and   │
│                                                    result upload.            │
│                                                    [default: no-sync]        │
│ --unsafe-local                                                               │
│ --format                       <str>               json, yaml, or text.      │
│                                                    [default: json]           │
│ --help                                             Show this message and     │
│                                                    exit.                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural runtime`

```text
                                                                                
 Usage: plural runtime [OPTIONS] COMMAND [ARGS]...                              
                                                                                
 Inspect execution-provider integration points.                                 
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ list    List providers that are genuinely available.                         │
│ show    Show one runtime's dynamic availability and capabilities.            │
│ doctor  Check provider dependencies, daemon, or credentials.                 │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural runtime doctor`

```text
                                                                                
 Usage: plural runtime doctor [OPTIONS] [name]                                  
                                                                                
 Check provider dependencies, daemon, or credentials.                           
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   name      <str>  [default: local]                                          │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural runtime list`

```text
                                                                                
 Usage: plural runtime list [OPTIONS]                                           
                                                                                
 List providers that are genuinely available.                                   
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural runtime show`

```text
                                                                                
 Usage: plural runtime show [OPTIONS] {name}                                    
                                                                                
 Show one runtime's dynamic availability and capabilities.                      
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    name      <str>  [required]                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural trial`

```text
                                                                                
 Usage: plural trial [OPTIONS] COMMAND [ARGS]...                                
                                                                                
 Inspect immutable job trials.                                                  
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ list  List planned trials with local result status.                          │
│ show  Show one planned trial and its persisted result.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural trial list`

```text
                                                                                
 Usage: plural trial list [OPTIONS] {identifier}                                
                                                                                
 List planned trials with local result status.                                  
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    identifier      <str>  [required]                                       │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --store        <path>  [default: .plural/jobs]                               │
│ --help                 Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `plural trial show`

```text
                                                                                
 Usage: plural trial show [OPTIONS] {trial_id}                                  
                                                                                
 Show one planned trial and its persisted result.                               
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    trial_id      <str>  [required]                                         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --job          <str>   [default: job.yaml]                                   │
│ --store        <path>  [default: .plural/jobs]                               │
│ --help                 Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```
