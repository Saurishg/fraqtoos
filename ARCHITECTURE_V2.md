# FraqtoOS Architecture V2

## System Diagram

```
systemd (fraqtoos.service)
  |
  v
orchestrator.py  <-- schedule.run_pending() every 30s
  |
  +--[every 30m]--> watchdog.run_lightweight()   pgrep critical procs
  +--[every  2h]--> job("chia_ai")               phi4 log classifier
  +--[every  4h]--> watchdog.run_full()           AI snapshot + alerts
  +--[06:00]------> job("portfolio")
  +--[07:00]------> morning_analysis()            gemma-agent (Popen)
  +--[08:00]------> job("chia_health")
  +--[10:00]------> job("utility_bill")
  +--[12:00]------> watchdog.run_full()
  +--[22:00]------> job("crypto")
  +--[23:00]------> send_daily_digest()
  |
  v
core/runner.run_bot(name, cmd, cwd, timeout, retries)
  |   subprocess.run(cmd, DISPLAY=:0)
  |
  +-> core/state.record_run()  -->  logs/state.json        (atomic)
  +-> core/ai_context.summarize_run() [phi4, 60s]
  |     write_summary()        -->  logs/ai_context.json   (atomic)
  +-> _bg(daemon thread)       -->  graphify update .  +  git push
  |
  +-- if fail and not silent:
        core/notifier.send_alert()
          |
          v
        [fcntl /tmp/fraqtoos_wa.lock]
          |
          v
        shared/send_whatsapp.py  POST http://127.0.0.1:3131/send
          |
          v
        wa-service (whatsapp-web.js, wa_profile/) --> user's phone
```

---

## Schedule Table

| Time       | Job                  | Timeout | Retries | Alert on fail |
|------------|----------------------|---------|---------|---------------|
| every 30m  | watchdog lightweight | —       | —       | critical only |
| every 2h   | chia_ai (phi4)       | 150s    | 0       | silent        |
| every 4h   | watchdog full        | —       | —       | conditional   |
| 06:00      | portfolio            | 300s    | 1       | yes           |
| 07:00      | morning_analysis     | —       | —       | no (fire+forget)|
| 08:00      | chia_health          | 60s     | 0       | silent        |
| 10:00      | utility_bill         | 300s    | 1       | yes           |
| 12:00      | watchdog full        | —       | —       | conditional   |
| 22:00      | crypto (BTC)         | 300s    | 0       | yes           |
| 23:00      | daily digest         | 300s    | —       | fallback text |

---

## Data Flow: Bot Run → AI Context → Daily Digest

```
run_bot() completes
  |
  v
ai_context.summarize_run()
  phi4 @ localhost:11434  (1 sentence, 60s timeout)
  |
  v
ai_context.write_summary(bot, summary)
  --> logs/ai_context.json  { "YYYY-MM-DD": { "BotName": "summary..." } }
                                   (atomic temp+rename, thread-locked)
  [repeats for each bot run throughout the day]
  |
  v
23:00: send_daily_digest()
  ai_context.generate_digest()
    read_today() --> all summaries for the day
    |
    +-- llama4 (300s)  --> narrative digest
    +-- phi4 fallback (120s) if llama4 fails
    +-- static bullet list if both fail
  |
  v
core/notifier.send(digest)  --> user's phone via wa-service
```

---

## WhatsApp Notification Flow

```
Caller: notifier.send(msg) or notifier.send_alert(title, body)
  |
  v
Open /tmp/fraqtoos_wa.lock
fcntl.LOCK_EX | LOCK_NB  (non-blocking acquire, retry up to 60s deadline)
  |
  v
subprocess.run(python3 shared/send_whatsapp.py <phone> <msg>, timeout=120)
  |
  v
send_whatsapp.py:
  POST http://127.0.0.1:3131/send  {"phone": "91...", "message": "..."}
  (130s timeout to allow queue drain)
  |
  v
wa-service (Node/whatsapp-web.js)
  uses wa_profile/ for session persistence
  |
  v
WhatsApp delivery to 919818187001
```

Rules enforced: only `core/notifier.py` calls `send_whatsapp.py`. Bots must not
call it directly — two simultaneous Firefox sessions corrupt the WA profile.
Firefox-using bots must set `firefox_lock: True` in their BOTS entry.

---

## Error Handling / Watchdog Flow

```
run_lightweight()  [every 30m, fast]
  pgrep for each non-scheduled bot
  if critical proc missing --> send_alert() immediately

run_full()  [every 4h + 12:00]
  1. ensure_ollama_up()
       probe localhost:11434/api/tags
       if down: sudo systemctl restart ollama, wait 8s, retry
       if still down: send_alert("Ollama DOWN")
  2. sys_stats() -- disk, RAM, GPU (all with explicit timeout to survive NVIDIA IPC hang)
  3. For each bot:
       daemon   --> is_running(proc)  + tail_log()
       scheduled --> state.json last_run age + success flag
  4. probe SearXNG localhost:8888
  5. ai_diagnose(snapshot)
       model chain: phi4 --> deepseek-r1:14b --> qwen3:14b
       prompt guards: scheduled=false-running is normal; disk<90% is fine
  6. write logs/watchdog_latest.json
  7. ruflo_report.push_to_ruflo() -- best-effort, 30s timeout
  8. if CRITICAL/disk>=90%/searxng_down/force_alert:
       send_alert(bot status + analysis[:400])

runner.run_bot() error path:
  subprocess fail --> log warning, retry after 15s (up to retries count)
  timeout --> log error, return success=False immediately
  any fail + not silent --> notifier.send_alert(bot_name, last 300 chars output)
```

---

## State Files

| File                           | Owner             | Contents                                      |
|--------------------------------|-------------------|-----------------------------------------------|
| `logs/fraqtoos.log`            | core/logger.py    | Rotating 5MB x 3, all modules                 |
| `logs/state.json`              | core/state.py     | Per-bot: last_run, success, duration, output   |
| `logs/ai_context.json`         | core/ai_context.py| {date: {bot: phi4_summary}}                   |
| `logs/watchdog_latest.json`    | watchdog.py       | Last {snapshot, analysis}                     |
| `logs/chia_ai_latest.json`     | bots/chia_ai_watcher| Last AI watcher classification batch         |
| `logs/morning_plan.txt`        | gemma-agent       | 3-point morning action plan (07:00)            |
| `/tmp/fraqtoos_wa.lock`        | core/notifier.py  | fcntl.LOCK_EX mutex for WhatsApp sends        |
| `/tmp/firefox.lock`            | orchestrator.job()| fcntl.LOCK_NB for firefox_lock bots           |

---

## Known Issues and Status

| Issue | Status | Notes |
|-------|--------|-------|
| NVIDIA IPC firmware hang (`0x0000c67d`) | Fixed | All `subprocess.run` in `sys_stats()` have explicit `timeout=` args; watchdog no longer freezes |
| `daily_results` lost on restart | By design | In-memory list; `ai_context.json` persists separately so 23:00 digest still has content |
| gemma-agent zombie children | Open / low severity | `morning_analysis()` uses bare `Popen` with no reaper; one zombie/day, no orchestrator impact |
| Multi-process `state.json` write race | Mitigated | `os.replace` atomic rename per-process; in-process `Lock` does not protect across `--run` manual invocations |
| `schedule` swallows job exceptions | Mitigated | `try/finally` in `job()` ensures lock release; exceptions logged to stdout by schedule lib |
| graphify/git blocking orchestrator | Fixed | `runner._bg()` daemon thread with `proc.wait(timeout=120)` reaper; no longer blocks schedule loop |
| WhatsApp double-send / profile collision | Mitigated | `fcntl` lock + 60s deadline; bots must not call `send_whatsapp.py` directly |
| llama4 digest timeout | Handled | Falls back to phi4 (120s), then to static bullet-list formatter |
| Ollama down | Self-healing | Watchdog probes, runs `sudo systemctl restart ollama`, alerts if still down after retry |
| SearXNG down | Detected | `run_full()` probes and includes `searxng_up: false` in alert; no auto-restart |
