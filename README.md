<div align="center">

# Valentown

**A town of seven LLM residents — and a world that is allowed to tell them no.**

English · [简体中文](README.zh-CN.md)

[![tests](https://github.com/aoaoguo2003/valentown/actions/workflows/tests.yml/badge.svg)](https://github.com/aoaoguo2003/valentown/actions/workflows/tests.yml)

![Valentown](docs/valentown.gif)

<sub>Day 4, 6:58 PM. Adam heads to the park to find Arthur. The world refuses —
and does not say where Arthur actually is.</sub>

</div>

---

## What this is

A **domain-specific closed-loop agent runtime** for a persistent multi-agent
simulation. Unlike a chat agent, every turn must eventually commit to an action
that advances the world clock — so the loop has a hard convergence condition,
and a wrong turn costs game time rather than a retry.

Seven residents share a town: they write letters, lend each other money, agree
to meet, and hand things over face to face. The interesting part is not that an
LLM drives them. It is that **the world is allowed to refuse**, and that every
design decision behind that world has been measured.

```
State → LLM → tool call → world → observation → LLM → … → action
                            └── may refuse, with a reason ──┘
```

An agent picks a tool. The world checks it — the shop is closed, the person is
not here, you are five short — and answers. The agent replans against the
refusal, and keeps going until it commits to something that costs time.

![The decision trace panel, showing one turn of five tool calls, two of them refused](docs/screenshot.png)

<sub>One real turn, as the UI shows it: **5 steps, 2 refused**. The world answers
the successful calls with shelf contents; the refused one keeps its arguments
(`shop='Supermarket'`) because repeating an identical call is exactly what the
agent has to avoid next.</sub>

| Decision | What it buys |
|---|---|
| 14 tools, each declaring whether it costs game time, how often it may run, who may see it | the loop counts; it knows about no specific tool |
| The lock is held twice per decision, for microseconds | 0.25s for seven residents, against 1.43s with the LLM call inside |
| Buying changes five things under one lock | 35 contested runs, zero oversells |
| Every capability is priced by an ablation | remove one, run the same task, read the drop |

### Before and after

The town used to work differently: one LLM call per turn, the model forced to
fill a fixed schema (`action`, `destination`, `duration`, `talk_to`), and a world
that always said yes. That version is still in the evaluation suite as the
`pre-rebuild` ablation, so the rebuild can be scored against the thing it
replaced rather than against a description of it.

| Task | Now | Before the rebuild |
|---|---|---|
| **errand** — read a letter, take the job, borrow money, buy, arrange a meeting, hand it over | **2/2**, 64 and 68 decisions | **0/2**, stage 1 of 6, 205–214 decisions |
| **rendezvous** — the cake only moves face to face | **2/2**, 25 and 27 decisions | **0/2**, stage 1 of 4, 217–220 decisions |
| **scarcity** — one box of medicine, two buyers, no overselling | **2/2**, 39 and 41 decisions | **0/2**, stage 1 of 3, 236–244 decisions |

The old design finishes none of them, and spends three to nine times the
decisions failing. It can only walk.

<sub>Both columns are one batch on one commit — 12 cells, 45 minutes, 4.8M
tokens, 0 unusable cells, 0 retries, 0 oversells, and no cell cut off by its
budget. Earlier batches on an earlier commit ran each baseline seven times
rather than twice, with the same outcome (7/7, 6/7, 7/7); they are quoted
separately below and never mixed with these.</sub>

---

## A world that says no

Refusals are not error handling. They are the content: an agent that is never
told no never has to plan.

| Rule | What it costs the agent |
|---|---|
| **You only see people in your own area** | Want to know where someone is? Write and ask. The world knows; no resident does. |
| **Shops keep hours, and have three seats** | Pharmacy 9–18. Turn up late and the door is shut. |
| **Rain closes outdoor spots** | Real London weather, per game hour. Outdoors is decided per anchor, not per area — a café patio shuts while its indoor tables stay open. |
| **15 to start, 15 more every third day** | A coffee costs 8. Asking someone to lend you money is not a flourish, it is the only way through. |
| **Handing something over needs both of you present** | Money can be sent from anywhere. Objects cannot. |
| **Two buyers, one box** | The shelf is decremented inside the same lock that takes the money, so "check then buy" cannot oversell. Thirty-five contested runs, **zero oversells**, and the winner is not always the same resident. |

A refusal never leaks what the agent is not allowed to know:

```
✅  "Emma Harris is not at Café_bar."
❌  "Emma Harris is at Park."          ← would hand out a global location table
```

### Three kinds of no, and only one of them is the model's fault

**It cannot know.** Where someone is right now; whether the last box was bought
during the thirty seconds it spent thinking. The first is deliberate — hand out
a global location table and writing to ask becomes pointless. The second is
atomicity: no amount of reasoning closes the gap between reading a shelf and
buying from it, only a lock does.

**It should know, and nobody had told it.** What time the pharmacy shuts. That
was never information asymmetry, it was amnesia: the world knew, and the
resident found out by walking into a locked door. Opening hours, capacity, who
keeps which shop and the full price list are now standing knowledge, the way
they would be for anyone who has lived here a while.

**It knows, and looks straight past it.** You are five short. The balance and
the price are both on screen, one line apart.

### The measured finding

| Attempt | Where it spoke | Result |
|---|---|---|
| Put prices in the context | before buying | 0/3 |
| Tell the tool description to check the wallet | before buying | 0/3 |
| Require a `cost` field so the model writes the number down | before buying | 0/3 |
| Put the opening hours in the context | before setting off | no measurable change |
| **Name the way out in the refusal itself** | **at the moment of failure** | **0/14 → 3/3** |

Four attempts to warn in advance, four failures. One attempt at the moment of
failure, and the case goes from never solved to always solved.

But "under a goal, constraints go invisible" is too loose, because the model
does respect some of them. Across 11,812 turns:

```
give_item without the item in your bag      0.02 refusals per 100 turns
buy without the money                       0.44
move_to a shop that is shut                 3.59
```

All three facts sit in the same context. What separates them is what the *next
call* needs:

> The model reads the part of the context an argument depends on, and skips the
> part that could only tell it to stop. `give_item` must name something you are
> carrying, so it reads the bag. `buy` needs the item's name and nothing else —
> the price and the balance are load-bearing for the *decision*, not for the
> *call*, and they go unread.

That predicts where a refusal will land better than any appeal to attention, and
it explains why speaking at the moment of failure works: right then the
constraint *is* load-bearing, because the next call has to be built around it.

<sub>`closed` overstates the case a little: the world has no notion of travel
time, so "set off now and arrive when it opens" is refused rather than modelled.
The resident could still wait and then walk, so the gap is real — just smaller
than 180×.</sub>

---

## Proving the parts carry weight

A baseline that scores well proves nothing; the task may simply be easy. Each
capability is removed on its own and the same task is run again.

<sub>This matrix ran on an earlier commit, before opening hours and prices
became standing knowledge — 88 cells over 6.6 hours. The capabilities it prices
are untouched by that change, but the numbers are not interchangeable with the
headline above, so they are kept apart.</sub>

|  | errand | rendezvous | scarcity |
|---|---|---|---|
| baseline | ✓ 7/7 | ✓ 6/7 | ✓ 7/7 |
| no outgoing mail | **✗ 0/2** — stuck at "afford it" | ✓ 2/2 | ✓ 2/2 |
| no cross-turn task list | **✗ 0/2** | ✓ 2/2 | **✗ 0/2** |
| no arranging meetings | ✓ 2/2 | ✗ 1/2 | ✓ 2/2 |
| one reasoning step per turn | **✗ 0/2** | ✗ 1/2 | **✗ 0/2** |
| pre-rebuild | **✗ 0/2** | **✗ 0/2** | **✗ 0/2** |

**The failures cross.** Taking away outgoing mail kills the errand and leaves the
rendezvous untouched; taking away meetings does the reverse. Nothing collapses
across the board, which is what tells you the suite is measuring capabilities
rather than fragility.

<sub>One row is not clean: removing meetings also silences the hand-over prompt,
which hangs off having a goal at all — so its rendezvous column is not
attributable to the meeting tool alone. An ablation has to remove exactly one
thing; this one removes one and a half, and is noted rather than quietly used.</sub>

The sharpest result is the multi-step loop. `single-step` gives the model all
fourteen tools but only one reasoning step per turn. It fails the errand and the
scarcity run, and passes the rendezvous once:

> The errand needs the agent to change its mind **inside one turn** — check the
> shelf, discover it is five short, and switch to writing for a loan before the
> turn ends. The rendezvous never does: walking over is one turn, handing the
> cake over is the next.

So the loop is not a general intelligence upgrade. **It buys exactly one thing:
the ability to replan without spending game time**, and it only shows up where
the task demands that.

Measured across 11,812 turns of the three seeded tasks: **1,780 refusals, and
after a refusal the agent chooses differently 100% of the time** (median across
cells). The world argues back and the agent listens.

---

## Engineering

**Slow I/O never holds the lock.** The LLM call (up to 60s) and the weather
request happen outside the critical section; the lock is taken twice per
decision, for microseconds — once to read a world snapshot, once to commit.

```
seven residents, one step each     0.25s      one call is 0.20s — near-perfect overlap
seven residents, two steps each    0.42s      two calls are 0.40s
the same work with the call inside the lock    1.43s   ← what the old design did
```

The third row is a deliberate counter-proof kept in the suite: if anyone moves a
slow call back inside the lock, the first two tests stop meaning anything and
this one goes red. (And **not** asyncio — threads already overlap perfectly on
I/O, and being able to explain why is worth more than the rewrite.)

**Committing re-runs the handler.** The world the model reasoned about is
seconds old; the last seat may be gone. The decision is validated again against
a fresh snapshot before it takes effect.

**A breaker for faults that will not heal.** 401/402/403 are account-level. On
the first one the client latches open and every later call returns immediately.
Before it existed, a drained balance produced 1,927 doomed requests and thirty
cells of garbage that read on the scorecard as *"the model is bad."* Under the
same injected fault: one request.

**A scorecard that admits what it does not know.** A cell where the model never
answered is marked `ERR` and excluded from the comparison entirely; a cell cut
off by its decision budget is marked `✗⏱`, not `✗`. Multi-stage tasks report
which stage they reached, because "bought the medicine but never delivered it"
and "did nothing all day" are not the same failure.

**Tracing, and metrics read back from it.** Every LLM call and every tool step
is appended as JSONL on the hot path; the metrics layer is a separate reader
with no project dependencies, so behaviour and cost can be recomputed offline
from any log, for free.

---

## Memory, retrieval, reflection

- **Rolling per-agent memory**, 15 lived days.
- **LLM-judged importance** — every memory scored 1–10 for poignancy, rather
  than a constant.
- **Three-factor retrieval** — `recency × importance × relevance`, relevance by
  cosine similarity over local embeddings (fastembed / bge-small; no API key,
  runs offline).
- **Nightly reflection → evolving persona → next day's prompt**, so reflection
  actually reaches behaviour.
- Retrieval is a **tool the agent calls** (`recall`), not a top-12 blob injected
  into every prompt.

---

## Honest limits

**The model assumes people are where they ought to be.** `target_absent` is the
single most common refusal — 977 across every batch, 8.3 per 100 turns. It walks
over to check instead of writing to ask. A single-step probe reproduces it 3/3.

**Giving residents their town's opening hours did not reduce refusals.** It was
the right thing to do on principle — a neighbour knows when the pharmacy shuts —
and it closed a real gap, since a resident who never accepted a task could not
previously see what anything cost. But measured against the batch before it,
`closed` fell on one task and rose on another, and the total did not move. It
is kept, and counted as the fourth failed attempt to warn in advance rather
than as an improvement.

**It does not check whether it can afford something before buying.** The four
experiments above fixed this at the moment of refusal, which rescues multi-step
runs but not the first choice of a single-step one; that probe is still 0/3.

**One change is in the codebase without having earned its place.** When a
resident is standing in front of the person they owe something to, three lines
say so. A single-step probe went 0/4 → 9/9 on the exact situation. The
end-to-end ablation did not reproduce it: 4/4 baseline against 3/4 with the
lines removed, at n=4. That scenario produces one or two hand-over moments a
day, so a binary verdict is too blunt — separating 90% from 65% would need
about thirty cells per arm. **This is a limit of the measurement, not evidence
against the change**, and it is written here rather than in the highlights.

**One evaluation bug survived into a run.** Re-proposing a meeting that already
existed deleted it for both parties — the rollback matched on pair, place and
time rather than on what the call had just created. Across every cell run before
the fix it landed exactly once — and that once was the single rendezvous
baseline failure in the earlier batch quoted above, where it read on the
scorecard exactly like the model giving up. Fixed, with tests on both halves of
the rule.

---

## Quick start

```bash
cd backend
python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1   |   macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # set LLM_API_KEY — a DeepSeek key works out of the box
python main.py              # http://localhost:5000
```

```bash
cd frontend
npm install
npm start                   # http://localhost:8080
```

The first run downloads a ~100 MB local embedding model for memory relevance.
**Without an API key the town still runs** on deterministic fallback decisions;
the LLM adds the deciding, the talking, and the reflecting.

```ini
LLM_API_KEY=your_key
LLM_BASE_URL=https://api.deepseek.com   # any OpenAI-compatible endpoint
LLM_MODEL=deepseek-v4-flash
```

---

## Layout

Dependencies run strictly one way, bottom to top.

```
world/       what the town is made of — clock, places, economy, weather,
             mailbox, goals, events, and the one place a snapshot is assembled
   ↑
tools/       what an agent may do to it — 14 tools, each a schema + handler
   ↑
runtime/     the decision loop, the scheduler, the context builder.
             Knows about no specific tool.
   ↑
api/ main.py the HTTP contract and a thin launcher

agents/  memory/  observability/  evals/  llm/     used by the layers above
```

| Package | What lives there |
|---|---|
| `world/` | Data and atomic operations. `economy.py` deliberately holds goods *and* money: buying changes five things at once, and **the atomicity boundary decides the module boundary**. |
| `tools/` | The registry. Each tool declares whether it costs game time, how many times per turn it may run, and who is eligible. The loop counts; it does not know what a letter is. |
| `runtime/` | `agent_runtime.py` (the loop), `scheduler.py` (an isolated town, shared by the offline runner and the evaluation suite), `context_builder.py` (what a resident gets to see this turn). |
| `evals/` | Scenarios, ablations, runner, scorecard. Verdicts read world state only. |
| `observability/` | `trace.py` writes on the hot path; `metrics.py` reads logs back and has no project dependencies. |

---

## Commands

```bash
node scripts/smoke_24h.js         # schedule + route smoke test, from the repo root
```

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest tests/ -q                              # 483 tests, no LLM, no network
python -m observability.metrics logs/<a-trace>.jsonl    # behaviour + cost, offline, free

python ../scripts/dry_run.py --days 2 --scenario errand # drive the whole town (costs money)
python -m evals.tool_choice --repeats 3                 # 8 single-step probes, ~2 minutes
python -m evals.runner --scenario all --ablate all --repeats 2 --note full-matrix
```

Every run gets a numbered directory (`logs/eval_v18_note/`) holding a `run.json`
with the command, the commit, and **whether the tree was dirty** — a version
number that cannot name its code is only a serial number.

---

## Scope

A research prototype: one Flask process, JSON persistence, seven residents. The
frontend is the production scheduler — the backend answers *what next*, the
browser plays it out. Built for local experimentation, not for scale.

> Inspired by *Generative Agents: Interactive Simulacra of Human Behavior*
> (Park et al., 2023); designed and written from scratch.
