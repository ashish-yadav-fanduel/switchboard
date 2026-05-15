---
description: Show your Switchboard token savings dashboard (session + lifetime + USD)
---

Run this bash command silently and then display the JSON result as a rich dashboard:

```bash
curl -sf http://localhost:9847/stats 2>/dev/null || echo '{"error":"daemon not running — send a prompt first to start it"}'
```

Format the output as follows:
- **This Session**: tokens processed, tokens saved, USD saved, compressions, brevity mode
- **Lifetime**: same fields + streak (consecutive active days)
- **7-day trend**: if daily_7 array has data, show a simple bar or sparkline per day
- **Top intent tiers**: list the top_tiers array (e.g. SIMPLE×12, MEDIUM×5)
- Use a clean table or panel layout. Keep it concise — one screen max.

If the daemon is not running, say: "Send any prompt first to warm Switchboard, then run /sb-stats again."
