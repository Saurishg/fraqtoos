# Graph Report - /home/work/fraqtoos  (2026-04-25)

## Corpus Check
- 22 files · ~15,909 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 109 nodes · 168 edges · 22 communities detected
- Extraction: 77% EXTRACTED · 23% INFERRED · 0% AMBIGUOUS · INFERRED: 38 edges (avg confidence: 0.8)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]

## God Nodes (most connected - your core abstractions)
1. `get()` - 16 edges
2. `run()` - 13 edges
3. `run_full()` - 9 edges
4. `render()` - 8 edges
5. `Agent` - 8 edges
6. `run_bot()` - 7 edges
7. `write_summary()` - 7 edges
8. `send_alert()` - 7 edges
9. `Pipeline` - 6 edges
10. `read_today()` - 6 edges

## Surprising Connections (you probably didn't know these)
- `job()` --calls--> `get()`  [INFERRED]
  /home/work/fraqtoos/orchestrator.py → /home/work/fraqtoos/core/state.py
- `job()` --calls--> `send_alert()`  [INFERRED]
  /home/work/fraqtoos/orchestrator.py → /home/work/fraqtoos/bots/amazon/run.py
- `send_daily_digest()` --calls--> `send()`  [INFERRED]
  /home/work/fraqtoos/orchestrator.py → /home/work/fraqtoos/core/notifier.py
- `render()` --calls--> `get_all_runs()`  [INFERRED]
  /home/work/fraqtoos/dashboard.py → /home/work/fraqtoos/core/state.py
- `render()` --calls--> `get()`  [INFERRED]
  /home/work/fraqtoos/dashboard.py → /home/work/fraqtoos/core/state.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.22
Nodes (10): Agent, amazon_listing_pipeline(), Pipeline, 3-model pipeline: summarize → analyze → write listing., 2-model pipeline: research → synthesize., Ask all models the same question, return the most common/best answer., Chain multiple agents — each output feeds into the next prompt., prompts: list of prompt templates, use {input} as placeholder for previous outpu (+2 more)

### Community 1 - "Community 1"
Cohesion: 0.21
Nodes (11): do_work(), main(), One-line summary feeds the 23:00 llama4 digest., Replace with the bot's actual job. Return a one-line summary., write_ai_context(), Exception, acquire_lock(), _alarm() (+3 more)

### Community 2 - "Community 2"
Cohesion: 0.24
Nodes (12): ai_diagnose(), ensure_ollama_up(), is_running(), latest_log(), Quick process check — no AI, no log reading. Returns True if all OK., Full check with log analysis and AI diagnosis., Probe ollama; if down, try systemctl restart. Alert on persistent failure., Dynamically find the newest log matching a glob pattern. (+4 more)

### Community 3 - "Community 3"
Cohesion: 0.18
Nodes (10): Use phi4 to write a 1-sentence summary of a bot run result., summarize_run(), job(), morning_analysis(), Run gemma agent with a task — fire and forget., Launch gemma-agent with smart router (phi4 classifies → best model)., run_ai_agent(), _bg() (+2 more)

### Community 4 - "Community 4"
Cohesion: 0.33
Nodes (8): clear(), disk_stats(), gpu_stats(), is_running(), ram_stats(), render(), run(), send_file()

### Community 5 - "Community 5"
Cohesion: 0.29
Nodes (10): generate_digest(), _load(), Write a bot's daily summary. Called after each bot run., Return today's summaries for all bots., Use llama4 to write a narrative daily digest from today's bot summaries.     Cal, read_today(), _save(), _today() (+2 more)

### Community 6 - "Community 6"
Cohesion: 0.44
Nodes (6): get(), get_all_runs(), _load(), record_run(), _save(), set()

### Community 7 - "Community 7"
Cohesion: 0.52
Nodes (6): check_health(), Check listing suppression and Buy Box status for both ASINs., run_all(), run_script(), send_alert(), send_success()

### Community 8 - "Community 8"
Cohesion: 0.83
Nodes (3): send(), send_alert(), send_success()

### Community 9 - "Community 9"
Cohesion: 1.0
Nodes (0): 

### Community 10 - "Community 10"
Cohesion: 1.0
Nodes (0): 

### Community 11 - "Community 11"
Cohesion: 1.0
Nodes (0): 

### Community 12 - "Community 12"
Cohesion: 1.0
Nodes (0): 

### Community 13 - "Community 13"
Cohesion: 1.0
Nodes (0): 

### Community 14 - "Community 14"
Cohesion: 1.0
Nodes (0): 

### Community 15 - "Community 15"
Cohesion: 1.0
Nodes (0): 

### Community 16 - "Community 16"
Cohesion: 1.0
Nodes (0): 

### Community 17 - "Community 17"
Cohesion: 1.0
Nodes (0): 

### Community 18 - "Community 18"
Cohesion: 1.0
Nodes (1): Run gemma agent with a task — fire and forget.

### Community 19 - "Community 19"
Cohesion: 1.0
Nodes (1): Launch gemma-agent with smart router (phi4 classifies → best model).

### Community 20 - "Community 20"
Cohesion: 1.0
Nodes (1): Quick process check — no AI, no log reading. Returns True if all OK.

### Community 21 - "Community 21"
Cohesion: 1.0
Nodes (1): Full check with log analysis and AI diagnosis.

## Knowledge Gaps
- **24 isolated node(s):** `Run gemma agent with a task — fire and forget.`, `Launch gemma-agent with smart router (phi4 classifies → best model).`, `Blocking file lock with overall timeout. Returns fd or raises Timeout.`, `Fire-and-forget background subprocess.`, `Chain multiple agents — each output feeds into the next prompt.` (+19 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 9`** (2 nodes): `logger.py`, `get_logger()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 10`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 11`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 12`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 13`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 14`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 15`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 16`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 17`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 18`** (1 nodes): `Run gemma agent with a task — fire and forget.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 19`** (1 nodes): `Launch gemma-agent with smart router (phi4 classifies → best model).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 20`** (1 nodes): `Quick process check — no AI, no log reading. Returns True if all OK.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 21`** (1 nodes): `Full check with log analysis and AI diagnosis.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get()` connect `Community 6` to `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 7`?**
  _High betweenness centrality (0.415) - this node is a cross-community bridge._
- **Why does `Agent` connect `Community 0` to `Community 6`?**
  _High betweenness centrality (0.197) - this node is a cross-community bridge._
- **Why does `run_bot()` connect `Community 3` to `Community 4`, `Community 5`, `Community 6`?**
  _High betweenness centrality (0.161) - this node is a cross-community bridge._
- **Are the 12 inferred relationships involving `get()` (e.g. with `job()` and `render()`) actually correct?**
  _`get()` has 12 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `run()` (e.g. with `gpu_stats()` and `ram_stats()`) actually correct?**
  _`run()` has 12 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `run_full()` (e.g. with `set()` and `get()`) actually correct?**
  _`run_full()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `render()` (e.g. with `get_all_runs()` and `get()`) actually correct?**
  _`render()` has 2 INFERRED edges - model-reasoned connections that need verification._