---
description: One-line PR review per file with severity emoji — fast triage, no noise
---

Run this to get the PR diff (uses current branch vs default branch):

```bash
gh pr diff 2>/dev/null || git diff $(git merge-base HEAD main 2>/dev/null || git merge-base HEAD master 2>/dev/null || echo HEAD~1)..HEAD
```

Review each changed file and output **one line per file** using this exact format:

`<emoji> <file>: <finding in ≤12 words>`

Severity emoji key:
- 🔴 Critical (bug, security, data loss)
- 🟡 Warning (logic smell, missing validation, perf)
- 🟢 OK (style, docs, trivial)
- 💡 Suggestion (optional improvement)

Rules:
- Only include files with a finding worth noting (skip pure style/whitespace files)
- No explanatory prose before or after the list
- If the diff is empty or the PR command fails: "No diff found. Make sure you're on a PR branch or have commits ahead of main."
