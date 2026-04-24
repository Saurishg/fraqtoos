# FraqtoOS — Solid Architecture (2026-04-24)

Single-orchestrator, single-WhatsApp-sender, AI-context-layered automation server.
All bots report to the same context layer; one writer per resource; no competing crons.

## Layout

```
/home/work/fraqtoos/
├── orchestrator.py          # systemd: fraqtoos.service
├── core/
│   ├── runner.py            # run_bot() — timeout + retry + ai_context write
│   ├── notifier.py          # send() — WhatsApp via /tmp/fraqtoos_wa.lock
│   ├── ai_context.py        # phi4 summaries → ai_context.json; llama4 digest
│   ├── state.py             # state.json — last_run, duration, runs_today
│   └── logger.py            # shared formatter
├── watchdog/
│   └── watchdog.py          # lightweight (30m) + full (4h) + ollama self-heal
├── bots/                    # per-bot wrappers (not used directly by orchestrator)
├── shared/
│   ├── send_whatsapp.py     # Firefox + wa_profile/
│   └── send_whatsapp_file.py
└── logs/
    ├── fraqtoos.log
    ├── state.json           # run history
    ├── ai_context.json      # per-day per-bot AI summaries
    ├── watchdog_latest.json
    └── audit_YYYYMMDD.md
```

## Scheduling (authoritative)

| Time  | Job            | Timeout | Lock           | Alert on fail |
|-------|----------------|---------|----------------|---------------|
| 06:00 | Portfolio      | 300s    | —              | yes           |
| 07:00 | AI morning     | fire-forget | —          | no            |
| 07:30 | Competitor Watch | 900s  | firefox_lock   | silent        |
| 08:00 | Amazon Delete  | 1800s   | firefox_lock   | silent        |
| 08:45 | Amazon Reviews | 900s    | firefox_lock   | silent        |
| 09:30 | Ads Audit      | 600s    | firefox_lock   | silent        |
| 10:00 | Utility Bill   | 300s    | —              | yes           |
| 12:00 | Watchdog full  | —       | —              | conditional   |
| 18:00 | Amazon Listing | 900s    | firefox_lock   | silent        |
| 22:00 | BTC Strategy   | 300s    | —              | yes           |
| Sun 11:00 | SEO Refresh | 900s   | firefox_lock   | silent        |
| 23:00 | Daily digest   | llama4 300s, phi4 120s fallback | — | — |
| every 30m | Watchdog light | — | — | critical only |
| every 4h  | Watchdog full  | — | — | conditional   |

## Locks (single owner per resource)

| Lock path                    | Purpose                        | Holders |
|------------------------------|--------------------------------|---------|
| `/tmp/fraqtoos_wa.lock`      | WhatsApp Firefox session       | `core/notifier.py` |
| `/tmp/amazon_firefox.lock`   | Amazon Selenium profile        | `core/runner.job()` for bots with `firefox_lock: True` |
| `ai_context._lock` (thread)  | `ai_context.json` writes       | in-process |
| `state._lock` (thread)       | `state.json` writes            | in-process |

## AI model roles

| Model           | Size  | Role |
|-----------------|-------|------|
| phi4            | 9 GB  | Run summarizer, watchdog classifier, fast tool-calling |
| gemma4          | 9.6 GB| Copy writing, NLP polish (Amazon bullets, digest style) |
| qwen3:14b       | 9 GB  | Financial reasoning (portfolio commentary, BTC strategy) |
| deepseek-r1:14b | 9 GB  | Math/logic/debugging, watchdog 2nd stage |
| llama4          | 67 GB | Daily digest narrative, multi-step synthesis |

Smart router: `/home/work/gemma-agent/agent.py` — phi4 classifies → routes by `ROUTE_MAP`.

## Watchdog responsibilities

1. **Lightweight (30 min)** — `pgrep` check for each critical bot; alert if critical bot missing.
2. **Full (4 h + 12:00)** — ollama self-heal → snapshot (disk/RAM/GPU, per-bot log tail, errors) → AI diagnosis (phi4 → deepseek-r1 → gemma4) → alert if `CRITICAL`/`WARNING`/disk≥90%/critical proc down.
3. **Ollama self-heal** — probes `/api/tags`, runs `sudo -n systemctl restart ollama` if down (sudoers entry `/etc/sudoers.d/fraqtoos-ollama`).

## Failure modes handled

| Failure                           | Handler |
|-----------------------------------|---------|
| Bot timeout                       | runner kills → state.json records → digest includes it |
| Bot non-zero exit                 | runner retries (per `retries`) → alert if non-silent |
| Ollama down                       | watchdog restarts → alerts on persistent failure |
| WhatsApp session conflict         | `flock LOCK_NB` retry; fallback to stderr log |
| Firefox profile conflict (Amazon) | `firefox_lock` — second bot skips its slot cleanly |
| AI digest timeout                 | llama4 → phi4 → static fallback |
| orchestrator restart mid-day      | `daily_results` lost but `ai_context.json` persists — digest still coherent |

## Adding a new bot

1. Write the bot script. Make sure it exits cleanly (exit code + no dangling Firefox).
2. Register in `orchestrator.py::BOTS` with `name`, `cmd`, `cwd`, `timeout`, `retries`, optional `silent`, optional `firefox_lock`.
3. Add a `schedule.every().day.at(...)` line.
4. Add entry to `watchdog/watchdog.py::BOTS` so full-watchdog sees it.
5. Run `python3 orchestrator.py --run <key>` to smoke-test.
6. `sudo systemctl restart fraqtoos.service`.

## Reference

- Wiki: `/home/work/obsidian-vault/wiki/`
- Graphify: `/home/work/fraqtoos/graphify-out/GRAPH_REPORT.md`
- Audit: `/home/work/fraqtoos/logs/audit_YYYYMMDD.md`
