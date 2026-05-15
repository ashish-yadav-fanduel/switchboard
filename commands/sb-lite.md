---
description: Set Switchboard to LITE brevity mode — strip filler only, keep full sentences
---

Run this command to set the brevity mode:

```bash
curl -sf -X POST http://localhost:9847/brevity \
  -H 'Content-Type: application/json' \
  -d '{"mode":"lite"}' 2>/dev/null || echo '{"error":"daemon not running"}'
```

Confirm: "Switchboard brevity mode set to **LITE** — I'll remove filler words but keep full sentences for the rest of this session."

Do not add any further explanation. Just confirm the mode change in one sentence.
