---
description: Compress a context/memory file (e.g. CLAUDE.md) through Switchboard — show before/after token counts
---

The user will specify a file path after `/sb-compress`. If no path is provided, use `CLAUDE.md`.

Steps:
1. Read the file content
2. Send it to the Switchboard daemon for compression:

```bash
curl -sf -X POST http://localhost:9847/compress \
  -H 'Content-Type: application/json' \
  -d "{\"text\": $(cat '$FILE' | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'), \"ratio\": 0.5}"
```

3. Report:
   - Original size: X tokens (~Y chars)
   - Compressed size: X tokens (~Y chars)  
   - Savings: Z% (W tokens)
   - Source: heuristic or llmlingua

4. Show the first 300 chars of compressed output as a preview.

5. Ask: "Apply compression? This will overwrite the file. (yes/no)"
   - If yes: write the compressed content back to the file and confirm.
   - If no: discard and confirm nothing was changed.

If the daemon is not running or the file doesn't exist, say so clearly without crashing.
