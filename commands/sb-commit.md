---
description: Generate a conventional commit message (≤50 char subject) for staged changes
---

Run this to get the staged diff:

```bash
git diff --cached --stat && echo "---" && git diff --cached
```

Then write a conventional commit message following these strict rules:
1. Subject line: `<type>(<scope>): <description>` — max 50 characters total
2. Type must be one of: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`, `ci`
3. Scope: the primary file, module, or feature area changed (short, lowercase)
4. Description: imperative mood, lowercase, no period
5. No body unless there is a breaking change — in that case add `BREAKING CHANGE:` footer only
6. Output the commit message inside a code block so it's easy to copy

If nothing is staged, say: "No staged changes. Run `git add <files>` first."
