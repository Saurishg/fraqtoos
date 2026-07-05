# FraqtoOS — Architecture

## Purpose

FraqtoOS is a single-orchestrator automation server that runs ~10 sub-bots (portfolio reporting, BTC strategy, utility-bill scraping, Chia farming health, AI log watcher, daily WhatsApp digest) on cron-like schedules. One Python daemon (`orchestrator.py`, run by systemd) owns all timing; one notifier owns WhatsApp; one watchdog probes everything every 30 min and self-heals Ollama. Bots write daily AI summaries to a shared context file that llama4 stitches into a 23:00 narrative digest.

## Components

| Module | File | Role | Schedule |
|--------|------|------|----------|
| Orchestrator daemon | `orchestrator.py` | systemd entry; owns `BOTS` registry + `schedule.every(...)` jobs; loops `schedule.run_pending()` every 30s | always-on |
| Runner | `core/runner.py` | `run_bot()` — subprocess + timeout + retry; writes state + AI summary; `_bg()` daemon-thread reaper for graphify+git push | called per job |
| Notifier | `core/notifier.py` | `send()` / `send_alert()` — WhatsApp via `shared/send_whatsapp.py`; `fcntl` lock at `/tmp/fraqtoos_wa.lock`; 60s deadline | per call |
| State | `core/state.py` | `record_run()` / `get()` / `set()` over `logs/state.json`; in-process `Lock`; atomic temp+rename writes | per call |
| AI Context | `core/ai_context.py` | `summarize_run()` (phi4, 60s) + `write_summary()` per-day per-bot; `generate_digest()` (llama4 → phi4 fallback → static) | per run / 23:00 |
| Logger | `core/logger.py` | Shared formatter; `RotatingFileHandler(5MB×3)` to `logs/fraqtoos.log` + stdout | all modules |
| Web Search | `core/web_search.py` | SearXNG wrapper at `127.0.0.1:8888`; `is_up()` health probe | watchdog + agent |
| Watchdog | `watchdog/watchdog.py` | `run_lightweight()` pgrep check; `run_full()` snapshot+AI diagnose+disk/SearXNG alerts; `ensure_ollama_up()` self-heal via `sudo systemctl restart` | 30m / 4h |
| Ruflo Push | `watchdog/ruflo_report.py` | `push_to_ruflo()` — store snapshot in ruflo memory for agent context (best-effort, 30s timeout) | after `run_full` |
| Bots dir | `bots/{chia_health,chia_ai_watcher,...}` | Bot implementations imported by orchestrator | — |

### Schedule (authoritative — `orchestrator.py`)

| Time | Job | Timeout | Alert on fail |
|------|-----|---------|---------------|
| every 30m | `run_lightweight` | — | critical only |
| every 2h  | `chia_ai` (`bots.chia_ai_watcher.run`) | 150s | silent |
| every 4h  | `run_full` | — | conditional |
| 06:00 | `portfolio` | 300s | yes |
| 07:00 | `morning_analysis` (gemma-agent fire-forget) | — | no |
| 08:00 | `chia_health` | 60s | silent |
| 10:00 | `utility_bill` | 300s | yes |
| 12:00 | `run_full` | — | conditional |
| 09:00, 21:00 | `crypto_portfolio` (Hive) | 120s | yes |
| 23:00 | `send_daily_digest` (gpt-oss:20b 300s → phi4 120s → static) | — | — |

## Data flow

```
systemd (fraqtoos.service)
   │
   ▼
orchestrator.py  ── schedule.run_pending() every 30s
   │
   │   schedule.every().day.at("06:00").do(job, "portfolio")
   ▼
job(key)  ── reads BOTS[key]; optional /tmp/firefox.lock flock
   │
   ▼
core/runner.py :: run_bot(name, cmd, cwd, timeout, retries)
   │   subprocess.run(cmd, timeout=...) with DISPLAY=:0
   │
   ├──► core/state.py :: record_run()  ─► logs/state.json (atomic temp+rename)
   │
   ├──► core/ai_context.py :: summarize_run() (phi4, 60s)
   │                          write_summary()  ─► logs/ai_context.json
   │
   └──► _bg("graphify update . ; git add+commit+push")  (daemon thread, reaped)
           returns {success, output, duration} → daily_results.append(r)
                  └─ if !success and !silent: notifier.send_alert()

core/notifier.py :: send()
   │   flock /tmp/fraqtoos_wa.lock (LOCK_NB, 60s deadline)
   │   subprocess.run(send_whatsapp.py, timeout=120)
   ▼
shared/send_whatsapp.py (Firefox + wa_profile/) → user's phone

watchdog/watchdog.py :: run_full()
   │   ensure_ollama_up() → snapshot{disk,ram,gpu,bots,errors,searxng}
   │   ai_diagnose(phi4 → deepseek-r1:14b → qwen3:14b)
   ├──► logs/watchdog_latest.json
   ├──► state.set("last_watchdog", ...)
   ├──► ruflo_report.push_to_ruflo()  (best-effort)
   └──► if CRITICAL/disk≥90%/searx_down: notifier.send_alert()

23:00: send_daily_digest()
   ai_context.generate_digest() reads today's per-bot summaries → llama4 → notifier.send()
```

## External dependencies

| Service | Endpoint | Used by | Failure mode |
|---------|----------|---------|--------------|
| Ollama | `localhost:11434` | `ai_context.py`, `watchdog.ai_diagnose` | watchdog auto-restarts via `sudo -n systemctl restart ollama` |
| SearXNG | `127.0.0.1:8888` | `core/web_search.py` | watchdog flags as `searxng_up: false`, alert sent |
| WhatsApp service | `shared/send_whatsapp.py` (Firefox + `wa_profile/`) | `notifier.py` | `fcntl` lock prevents concurrent sessions; falls back to stderr |
| gemma-agent | `/home/work/gemma-agent/agent.py` | `morning_analysis`, `run_ai_agent` | fire-and-forget Popen (zombies possible — see gotchas) |
| ruflo CLI | `~/.local/share/fnm/.../ruflo` | `watchdog/ruflo_report.py` | `capture_output, timeout=30`, errors logged as `log.warning` |
| graphify | shell `graphify update .` | `runner._bg` per bot run | daemon thread, 120s wait, errors swallowed |

## State files

| File | Owner | Contents |
|------|-------|----------|
| `logs/fraqtoos.log` | `core/logger.py` | Rotating 5MB × 3, all modules |
| `logs/state.json` | `core/state.py` | `runs[bot] = {last_run, success, duration, runs_today, last_output}`, `last_watchdog` |
| `logs/ai_context.json` | `core/ai_context.py` | `{YYYY-MM-DD: {bot: phi4_summary}}` — read at 23:00 by `generate_digest()` |
| `logs/watchdog_latest.json` | `watchdog/watchdog.py` | last `{snapshot, analysis}` — also consumed by `morning_analysis` |
| `logs/chia_ai_latest.json` | `bots/chia_ai_watcher.py` | last AI watcher classification batch |
| `logs/chia_watcher_state.json` | `bots/chia_ai_watcher.py` | last-seen log offsets |
| `logs/morning_plan.txt` | gemma-agent (07:00) | 3-point morning action plan |
| `agentdb.rvf`, `ruvector.db` | claude-flow / ruflo | swarm + vector memory (not orchestrator state) |
| `/tmp/fraqtoos_wa.lock` | `core/notifier.py` | `fcntl.LOCK_EX` for WhatsApp |
| `/tmp/firefox.lock` | `orchestrator.py::job` | `fcntl.LOCK_NB` for `firefox_lock: True` bots |

(There is no `state/` or `.fraqtoos/` directory — all state lives in `logs/`.)

## Operational

```bash
# Start / stop
sudo systemctl start fraqtoos.service
sudo systemctl stop fraqtoos.service
sudo systemctl restart fraqtoos.service
sudo systemctl status fraqtoos.service

# Manual run (bypass schedule)
python3 /home/work/fraqtoos/orchestrator.py --run portfolio
python3 /home/work/fraqtoos/orchestrator.py --run digest
python3 /home/work/fraqtoos/orchestrator.py --run watchdog

# Dashboard
python3 /home/work/fraqtoos/orchestrator.py --dashboard

# Logs
tail -f /home/work/fraqtoos/logs/fraqtoos.log
journalctl -u fraqtoos.service -f
```

### Adding a new bot

1. Write the bot script; ensure clean exit codes and no dangling Firefox windows.
2. Register in `orchestrator.py::BOTS` with `name`, `cmd`, `cwd`, `timeout`, `retries`, optional `silent`, optional `firefox_lock`.
3. Add `schedule.every().day.at("HH:MM").do(job, "<key>")`.
4. Add a corresponding entry to `watchdog/watchdog.py::BOTS` (set `scheduled: True` for one-shot bots so the pgrep check is skipped).
5. Smoke-test: `python3 orchestrator.py --run <key>`.
6. `sudo systemctl restart fraqtoos.service`.

## Known gotchas

- **graphify + git in background** — `runner._bg()` runs `graphify update .` and `git add/commit/push` on a *daemon thread* with a `proc.wait(timeout=120)` reaper. Earlier versions used inline `subprocess.run` and blocked the orchestrator until the git push completed, sometimes piling up scheduled jobs.
- **Ollama IPC firmware hang** — `nvidia-smi` can stall indefinitely during NVIDIA IPC firmware timeouts (fix logged in `~/.claude/projects/-home-work/memory/nvidia_ipc_fix.md`). All `subprocess.run` calls in `watchdog.sys_stats()` now have explicit `timeout=` to prevent the watchdog from freezing.
- **WhatsApp double-send** — only `core/notifier.py` may call `send_whatsapp.py`; bots must never call it directly or two Firefox profiles will collide. The `fcntl` lock + 60s deadline catches this if it slips through.
- **Firefox profile sharing** — `wa_profile/` is shared by `send_whatsapp.py`; any bot that opens Firefox needs `firefox_lock: True` so `job()` `flock`s `/tmp/firefox.lock` (non-blocking — second job logs "skipped" and exits cleanly).
- **State file corruption** — `state.py._save` and `ai_context.py._save` write via temp file + `os.replace` (atomic). Without this, a SIGTERM mid-write corrupts the JSON, `_load` swallows the exception and returns `{}`, and the next `_save` silently wipes all run history.
- **Process re-entry on `--run`** — manual `--run` invocations and the systemd daemon both write `state.json`. The in-process `Lock` does not protect across processes; multi-process writes rely entirely on the atomic `os.replace`.
- **Schedule library swallows job exceptions** — if `job()` raises, `schedule` logs to stdout but keeps running. Always `try/finally` lock cleanup inside `job()`.
- **`daily_results` is in-memory** — restarts mid-day lose the per-run list, but `ai_context.json` persists, so the 23:00 digest still has content.
- **gemma-agent fire-and-forget** — `morning_analysis()` and `run_ai_agent()` use bare `Popen` with no reaper thread; they can leave zombie children on the orchestrator. Low impact (one Popen per day) but worth knowing.
- **`bots.chia_ai_watcher.run()` is invoked via inline `python3 -c "..."`** — keeps cwd consistent and avoids module-path drift; logs go through orchestrator runner so they appear in `fraqtoos.log`.
