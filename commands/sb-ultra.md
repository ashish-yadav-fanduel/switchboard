---
description: Set Switchboard to ULTRA brevity mode — telegraphic, code first, ≤2 sentence explanations
---

Run this command to set the brevity mode:

```bash
curl -sf -X POST http://localhost:9847/brevity \
  -H 'Content-Type: application/json' \
  -d '{"mode":"ultra"}' 2>/dev/null || echo '{"error":"daemon not running"}'
```

Confirm with exactly this line: "⚡ ULTRA mode. Code first. ≤2 sentences. No prose."

Nothing else. No elaboration. Model the mode you just set.
