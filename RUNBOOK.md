# FraqtoOS — Operational Runbook

Companion to `ARCHITECTURE.md`. Step-by-step recipes for common operations and incidents.

## Daily health check (30 seconds)

```bash
systemctl status fraqtoos.service --no-pager | head -5
cat /home/work/fraqtoos/logs/watchdog_latest.json | python3 -m json.tool
tail -30 /home/work/fraqtoos/logs/fraqtoos.log
```

If `watchdog_latest.json` shows `status: OK` and service is `active`, you're good.

## Restart the whole system

```bash
sudo systemctl restart fraqtoos.service
tail -f /home/work/fraqtoos/logs/fraqtoos.log
```

Wait ~15s and verify `Ready - bots registered` line. No restart required after editing a bot — orchestrator reads `BOTS[]` at boot, so changes require a service restart.

## Run a single bot on demand

```bash
cd /home/work/fraqtoos
python3 orchestrator.py --run <key>
```

Where `<key>` is one of: `portfolio`, `utility_bill`, `crypto`, `digest`. Output goes to stdout *and* `logs/fraqtoos.log`.

## A bot failed — what do I do?

1. Check the digest (latest WhatsApp digest names the failing bot).
2. Tail `logs/fraqtoos.log` and `logs/<bot>.log` for the stack trace.
3. Re-run via `python3 orchestrator.py --run <key>` to reproduce.
4. Fix → `sudo systemctl restart fraqtoos.service`.

## Ollama is down

Watchdog self-heals via `sudo -n systemctl restart ollama` (sudoers entry at `/etc/sudoers.d/fraqtoos-ollama`). If it keeps dying:

```bash
systemctl status ollama
journalctl -u ollama -n 100 --no-pager
nvidia-smi                        # GPU memory fragmentation?
ollama ps                         # models pinned in RAM?
```

Common causes: GPU OOM from too many models resident → `ollama stop <model>` to free. NVIDIA IPC firmware timeout `0x0000c67d` → see `~/.claude/projects/-home-work/memory/nvidia_ipc_fix.md`.

## WhatsApp stopped sending

```bash
ls -la /tmp/fraqtoos_wa.lock              # stale lock?
pgrep -f "send_whatsapp"                  # any running senders?
ls /home/work/fraqtoos/shared/wa_profile/ # profile intact?
```

If the lock is stale, remove it: `rm /tmp/fraqtoos_wa.lock`. If the wa_profile is corrupted, re-login via headed Firefox pointed at that profile.

## Firefox profile locked

Overlapping Firefox-using bots are mutually excluded via `/tmp/firefox.lock`. If the lock gets stuck:

```bash
pgrep -f firefox | xargs -r ps -fp
rm /tmp/firefox.lock
```

## Disk near full

Watchdog alerts at ≥90%. Usual culprits: Chia plots, model cache, browser profiles, logs.

```bash
du -sh /home/work/* | sort -h | tail -20
du -sh ~/.ollama/models/*
find /home/work -name "*.log" -size +100M
```

## Graphify maintenance

After any code change:

```bash
cd <repo>
graphify update .
```

Graphify runs AST-only (no API cost). If graph is stale:

```bash
cd <repo>
graphify init . && graphify build .
```

Read `graphify-out/GRAPH_REPORT.md` before making architecture decisions.

## Pushing bot code

Every bot that's a git repo auto-commits + pushes after each successful run (see `core/runner.py`). To push manually:

```bash
cd <repo>
git add -A && git commit -m "msg"
git push origin main
```

If push fails silently, check `git remote -v` and `~/.ssh/`.

## Emergency stop (stop all automation)

```bash
sudo systemctl stop fraqtoos.service
```

The service is the only thing scheduling bots — no separate crons. Nothing will fire until you restart.

## Adding sudo NOPASSWD entries

Current entry at `/etc/sudoers.d/fraqtoos-ollama` allows `work` user to restart ollama without password. To add more:

```bash
sudo visudo -f /etc/sudoers.d/fraqtoos-<name>
# Content: work ALL=(ALL) NOPASSWD: /bin/systemctl restart <unit>
```

Test with `sudo -n systemctl restart <unit>` — if it prompts for password, the sudoers entry is wrong.

## Backup essentials

The data that matters (not derivable from code):

| Path | What | Restore strategy |
|------|------|------------------|
| `/home/work/fraqtoos/logs/state.json` | run history | regenerates |
| `/home/work/fraqtoos/logs/ai_context.json` | digest context | regenerates after 24h |
| `/home/work/fraqtoos/shared/wa_profile/` | WhatsApp session | re-login by hand |
| `/home/work/portfolio_bot/.env` | broker credentials | secrets vault |
| `/home/work/utility-bill-bot/.env` | Gmail OAuth token | re-auth flow |
| `/home/work/crypto-trading-bot/btc_1h_cache.csv` | BTC OHLC cache | regenerates from binance |

## Memory-aware context

Auto-memory lives at `/home/work/.claude/projects/-home-work/memory/`. `MEMORY.md` is the index. Read the obsidian-vault wiki first (`/home/work/obsidian-vault/wiki/`) before asking Claude about code — it's the canonical human-authored knowledge layer.
