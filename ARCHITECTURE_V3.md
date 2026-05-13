# FraqtoOS Bot Architecture

```
fraqtoos/
├── orchestrator.py          ← Single scheduler (schedule lib, runs via systemd)
├── core/
│   ├── logger.py            ← Rotating log → logs/fraqtoos.log
│   ├── runner.py            ← run_bot(): subprocess + retry + timeout + state
│   ├── notifier.py          ← send() / send_alert() → WhatsApp (fcntl locked)
│   ├── state.py             ← JSON state store (atomic writes)
│   ├── ai_context.py        ← phi4 run summaries + daily digest
│   └── web_search.py        ← SearXNG wrapper
├── bots/
│   ├── chia_health.py       ← Rule-based Chia farming health check
│   ├── chia_ai_watcher.py   ← phi4 classifies Chia log errors
│   ├── ai_agent/run.py      ← Wraps gemma-agent/agent.py
│   ├── crypto/__init__.py   ← Wraps crypto-trading-bot/btc_strategy.py
│   ├── portfolio/__init__.py← Wraps portfolio_bot/portfolio_bot.py
│   └── utility_bill/__init__.py ← Wraps utility-bill-bot/bot.js
└── watchdog/
    ├── watchdog.py          ← Process health + AI diagnosis
    ├── ruflo_fixer.py       ← Auto-fix known Chia errors
    └── ruflo_report.py      ← Chia report formatter

External bot directories (each has its own git repo):
  /home/work/portfolio_bot/        portfolio_bot.py
  /home/work/utility-bill-bot/     bot.js
  /home/work/crypto-trading-bot/   btc_strategy.py
  /home/work/Desktop/crypto/       index.js  (Crypto Portfolio / Hive)
  /home/work/gemma-agent/          agent.py
```

## Schedule
| Time       | Bot                    | Status |
|------------|------------------------|--------|
| Every 30m  | Watchdog lightweight   | ✅ |
| Every 2h   | Chia AI Watcher        | ✅ |
| Every 4h   | Watchdog full          | ✅ |
| 06:00      | Portfolio Bot          | ✅ |
| 07:00      | AI Agent (morning)     | ✅ |
| 08:00      | Chia Health Monitor    | ✅ |
| 09:00      | Crypto Portfolio Bot   | ✅ |
| 10:00      | Utility Bill Bot       | ✅ |
| 12:00      | Watchdog full          | ✅ |
| 21:00      | Crypto Portfolio Bot   | ✅ |
| 22:00      | BTC Strategy Bot       | ✅ |
| 23:00      | Daily WhatsApp Digest  | ✅ |

## Data Flow
```
Bot runs → runner.py → state.json + logs/fraqtoos.log
                     → ai_context.py (phi4 summary)
                     → notifier.py (WhatsApp on failure)
                     → background git commit + graphify
```

## Run a bot manually
```bash
cd /home/work/fraqtoos
python3 orchestrator.py --run portfolio
python3 orchestrator.py --run utility_bill
python3 orchestrator.py --run crypto
python3 orchestrator.py --run chia_health
python3 orchestrator.py --run digest
python3 orchestrator.py --run watchdog
```
