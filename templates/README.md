# Bot template

`bot_template.py` is the minimum skeleton every FraqtoOS bot should follow.

## Why this shape

- **Load `.env` up front** — secrets out of source, standard across repos.
- **File + stdout logging** — orchestrator captures stdout for `logs/fraqtoos.log`, the file log gives the bot its own history.
- **`write_ai_context(summary)`** — every bot MUST call this on both success and failure. The 23:00 llama4 digest reads from `ai_context.json` and cannot see a bot that doesn't write here.
- **Exit codes** — `sys.exit(1)` on failure so the orchestrator marks the run failed and retries per policy.
- **Stem as bot name** — `Path(__file__).stem` keeps the ai_context key consistent with the filename.

## Register in orchestrator

Add to `/home/work/fraqtoos/orchestrator.py` in the `BOTS` dict:

```python
"mybot": {
    "name":         "My Bot",
    "cmd":          ["python3", "/home/work/mybot/mybot.py"],
    "cwd":          "/home/work/mybot",
    "timeout":      300,
    "retries":      1,
    "silent":       False,      # True = don't alert on failure
    "firefox_lock": False,      # True for Amazon bots
},
```

Then add one `schedule.every().day.at("HH:MM").do(lambda: job("mybot"))` line, add a matching entry in `watchdog/watchdog.py::BOTS`, and `sudo systemctl restart fraqtoos.service`.

## Do NOT

- Launch your own cron — the orchestrator is the only scheduler.
- Call `send_whatsapp.py` directly from inside a bot — use `ai_context` and let the digest speak. Only alerting paths (portfolio report, utility bill) send WhatsApp directly, and those use `/home/work/fraqtoos/shared/send_whatsapp.py` which takes the lock.
- Open Firefox without setting `firefox_lock: True` if another Amazon bot could overlap.
- Swallow exceptions silently — let them bubble and exit non-zero; the digest needs to see failures.
