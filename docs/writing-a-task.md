# Writing a Task

A task defines what Evolution optimizes. You need two things: a grader script and an `evolution.yaml` config.

## Step 1: Write a Grader

The grader runs in the agent's worktree and outputs a score. The simplest grader:

```python
#!/usr/bin/env python3
"""Score = percentage of tests passing."""
import subprocess, sys

result = subprocess.run(["pytest", "tests/", "-q", "--tb=no"],
                       capture_output=True, text=True, timeout=300)

lines = result.stdout.strip().split("\n")
for line in lines:
    if "passed" in line:
        import re
        m = re.search(r"(\d+) passed", line)
        total_match = re.search(r"(\d+) passed(?:.*?(\d+) failed)?", line)
        passed = int(m.group(1)) if m else 0
        failed = int(total_match.group(2)) if total_match and total_match.group(2) else 0
        total = passed + failed
        print(passed / total if total > 0 else 0.0)
        sys.exit(0)

print(0.0)
```

**Protocol:**
- First line of stdout = numeric score (float)
- stderr = feedback text (shown to agent)
- Exit code 0 = success; nonzero = grade failed

### Tiered Grading

For expensive benchmarks, use a tiered grader that runs a fast eval most of the time and a full eval periodically:

```python
#!/usr/bin/env python3
import json
from pathlib import Path

STATE = Path(".evolution/grader_state.json")
state = json.loads(STATE.read_text()) if STATE.exists() else {"count": 0}
state["count"] += 1
STATE.write_text(json.dumps(state))

if state["count"] % 5 == 0:
    score = run_full_eval()    # All benchmarks, ~12 min
else:
    score = run_fast_eval()    # Subset, ~3 min

print(score)
```

## Step 2: Write evolution.yaml

Minimal config:

```yaml
session:
  name: my-task

task:
  name: my-task
  path: .
  seed: .
  description: Improve test coverage.
  grader:
    type: script
    script: ./grader.py
  metric:
    name: score
    direction: higher_is_better
  stop:
    max_time: 6h

roles:
  agent:
    prompt: |
      You are an autonomous agent. Make changes to improve the score.
      Submit with: evolution eval -m "what you changed"
      Share insights: evolution note add "what you found"

agents:
  agent-1:
    role: agent
    runtime: claude-code
    skills: [superpowers]
```

## Step 3: Run

```bash
evolution run --config evolution.yaml
```

## Tips

- **Start with one agent** to validate the pipeline, then scale to 2-4
- **Set milestones** if you have baseline scores. Agents get notified when milestones are reached
- **Use stagnation shake-up** (`stagnation_action: shake_up`) for long sessions
- **The grader runs in the agent's worktree**: each agent has its own copy of the code
- **Pre-compute expensive data** (embeddings, datasets) and put it in a symlinked directory so all agents share it
- **Keep grader runtime under 5 minutes**: agents iterate faster with quick feedback
