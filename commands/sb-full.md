---
description: Set Switchboard to FULL brevity mode (default) — concise fragments, no hedging
---

Run this command to set the brevity mode:

```bash
curl -sf -X POST http://localhost:9847/brevity \
  -H 'Content-Type: application/json' \
  -d '{"mode":"full"}' 2>/dev/null || echo '{"error":"daemon not running"}'
```

Confirm: "Switchboard brevity mode set to **FULL** — concise responses with no filler or hedging for the rest of this session."

Do not add any further explanation. Just confirm in one sentence.
