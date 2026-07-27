# Tick Engine

The tick engine is the heartbeat of NationCraft. Every
`TICK_INTERVAL_SECONDS` (default 60s), every active world is walked
through an ordered sequence of phases that recomputes the entire game
state.

## 1. Architecture

```
TickRunner (scheduler) ─► TickEngine.run(ctx)
                                  │
                                  ├─► Phase: PRE_TICK     (hooks only)
                                  ├─► Phase: PRODUCTION   (built-in + hooks)
                                  ├─► Phase: POPULATION   (built-in + hooks)
                                  ├─► Phase: ECONOMY      (hooks only)
                                  ├─► Phase: RESEARCH     (built-in + hooks)
                                  ├─► Phase: CONSTRUCTION (hooks only)
                                  ├─► Phase: MILITARY     (hooks only)
                                  ├─► Phase: TRANSPORT    (hooks only)
                                  ├─► Phase: EVENTS       (built-in + hooks)
                                  ├─► Phase: MISSIONS     (built-in + hooks)
                                  ├─► Phase: RANKINGS     (hooks only)
                                  ├─► Phase: NOTIFICATIONS(hooks only)
                                  └─► Phase: POST_TICK    (hooks only)
```

## 2. Built-in handlers

Registered by `application/services/tick_registration.py`:

| Phase | Handler | What it does |
| --- | --- | --- |
| `PRODUCTION` | `production_phase` | Completes finished buildings; applies per-tick production/consumption |
| `RESEARCH` | `research_phase` | Completes research whose timer expired |
| `POPULATION` | `population_phase` | Consumes food/water; drifts approval; grows/declines population |
| `EVENTS` | `events_phase` | Rolls random events |
| `MISSIONS` | `missions_phase` | Evaluates mission progress for every country |

Each handler opens its own DB session, performs the work, commits, and
records metrics in `TickContext.metrics`.

## 3. Hook integration

After built-in handlers run for a phase, the engine invokes the
`tick.phase.<phase_name>` hook so plugins/extensions can run extra
logic:

```python
from nationcraft.core.extensions import HookPriority

async def my_phase_hook(_default, ctx):
    # ctx is a TickContext with world_id, tick, started_at, metrics
    ...

api.on_hook("tick.phase.production", my_phase_hook, priority=HookPriority.LOW)
```

## 4. TickContext

```python
@dataclass(slots=True)
class TickContext:
    world_id: int
    tick: int               # 1-indexed tick number
    started_at: float       # monotonic timestamp
    metrics: dict[str, Any] # filled by handlers
    skip_remaining: bool    # set True to abort remaining phases
```

## 5. Tick phases (enum)

Defined in `core/config/models.py`:

```python
class TickPhases(StrEnum):
    PRE_TICK = "pre_tick"
    PRODUCTION = "production"
    POPULATION = "population"
    ECONOMY = "economy"
    RESEARCH = "research"
    CONSTRUCTION = "construction"
    MILITARY = "military"
    TRANSPORT = "transport"
    EVENTS = "events"
    MISSIONS = "missions"
    RANKINGS = "rankings"
    NOTIFICATIONS = "notifications"
    POST_TICK = "post_tick"
```

## 6. Per-tick events emitted

- `tick.started` (world_id, tick)
- `tick.finished` (world_id, tick, duration_ms)
- `production.tick` (after production)
- `population.updated` (per country)
- `population.protest_started` (if unrest > 0.7)
- `event.triggered` (per random event)
- `mission.completed` (per completed mission)

## 7. Failure isolation

- A thrown handler logs an exception and is skipped; the tick continues
  with the next handler/phase.
- A thrown plugin hook is likewise isolated.
- The runner itself catches any unexpected error, logs it, and waits
  for the next interval — never crashes the worker.

## 8. Scaling

The default `TickRunner` processes worlds sequentially. For high world
counts, partition worlds by `world_id % N` across N worker processes.
Future work: per-world asyncio tasks with backpressure.

## 9. Observability

Each tick logs:
```
{"event":"tick.started","world_id":1,"tick":42,...}
{"event":"tick.phase.failed","phase":"production","handler":"default","world_id":1,...}
{"event":"tick.finished","world_id":1,"tick":42,"duration_ms":1234,...}
```

Inspect per-tick metrics via `GET /admin/metrics`.
