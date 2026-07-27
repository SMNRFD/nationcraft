# Game Design Document (GDD)

> Version 1.0 — NationCraft

## 1. Vision

NationCraft is a persistent, text-based, multiplayer strategy game for
Telegram. Every player becomes the ruler of exactly one country inside a
single world. Worlds are independent parallel instances — when one fills
up, the server automatically creates another.

The game is inspired by *NationStates*, *eRepublik*, *Politics & War*,
*Tribal Wars*, *Ikariam*, *OGame*, and *Supremacy 1914*, but optimized
for Telegram's inline-keyboard UX.

## 2. Core loop

1. **Register** a player account via the bot (`/register`).
2. **Pick a world** (any open world; you may switch only by abandoning your country).
3. **Select a country** — each real-world country exists once per world.
4. **Build the economy** — farms, mines, factories, power plants.
5. **Research the tech tree** — unlock units, buildings, bonuses.
6. **Trade on the market** — buy/sell resources at prices you set.
7. **Build a military** — train infantry, tanks, planes, ships, missiles.
8. **Diplomacy** — alliances, embargoes, trade agreements, wars.
9. **Manage population** — keep food/water/approval high or face unrest.
10. **React to events** — natural disasters, economic crises, holidays.
11. **Climb the rankings** — population, GDP, military, approval, etc.

Every tick (default: 60 seconds) the server recomputes the world:
production, consumption, research progress, population growth, mission
progress, and random events.

## 3. Worlds

- **Unlimited worlds.** Auto-created when the previous one fills.
- **Capacity** is configurable (default 200 players/world).
- **Independent economies, rankings, wars, diplomacy, history.**
- **Tick number** is per-world and persisted.

## 4. Countries

Every real sovereign country is available as a selectable template
(defined in `game/data/countries.yaml`). When a new world is created,
every country is seeded with its starting population, treasury,
resources, and buildings.

Each country tracks:

| Attribute | Description |
| --- | --- |
| `population` | Living population; grows/declines per tick based on conditions |
| `treasury` | Liquid money |
| `debt` | National debt |
| `approval` | 0–100% — low values cause unrest |
| `stability` | 0–100% — low values risk revolution |
| `corruption` | 0–100% — reduces tax income and efficiency |
| `education`, `healthcare` | Civic stats; affect growth & research |
| `electricity_balance` | Power production − consumption |
| `pollution` | Damages health and approval |

## 5. Resources

Resources are fully data-driven (`game/data/resources.yaml`). Categories:

- **Material** — food, water, wood, stone, iron, copper, steel, coal, oil, gas, uranium, gold, silver, rare earth, fuel, electricity, medicine, weapons, electronics.
- **Currency** — money, influence.
- **Population** — workers, engineers, scientists, soldiers.
- **Research** — research_points.

Every resource defines: `key`, `name`, `category`, `base_price`,
`tradable`, `stackable`, `min/max`, `hidden`. Plugins may register
additional resources at load time.

## 6. Production

Buildings (`game/data/buildings.yaml`) define:

- Construction cost (resource dict) and growth factor for upgrades.
- Build time (per level).
- Production / consumption formulas (per-minute rates × level).
- Storage capacity.
- Worker requirement, power consumption/production, maintenance.
- Tech prerequisites (`requires_tech`).
- Building prerequisites (`requires_building`).

Each tick the production service:

1. Completes any building whose `completes_at` has passed.
2. For each active building: computes gross production × level ×
   (delta_seconds / 60).
3. Applies the `production.output` hook (extensions may modify it).
4. Bulk-adjusts the country's resource stocks.

## 7. Research

Tech tree (`game/data/techs.yaml`) organized by branches: industry,
military, energy, civic, space. Each tech has tier, prerequisites,
research cost (resources), research time, and effects (bonuses to
production/combat/etc.). Completed techs unlock buildings and units.

## 8. Military

Units (`game/data/units.yaml`) define attack, defense, health, speed,
range, crew, fuel usage, cost, build time, maintenance, and tech/building
prerequisites. Categories: land, air, naval, missile, cyber, space.

## 9. War & combat

- A country may declare war on any country in the same world.
- Wars track attacker/defender war_score.
- Each attack resolves a battle: aggregate attacker attack power vs.
  defender defense power, modified by random variance (±15%) and any
  registered `combat.resolve` hooks.
- Winner gains war_score proportional to the margin; loser takes
  proportionally higher unit losses.
- Wars end via ceasefire, occupation, or one side reaching 100 war_score.

## 10. Market

A continuous-matching order book:

- Players place BUY or SELL orders with quantity and unit_price.
- SELL orders deduct the offered resource upfront (refunded on cancel).
- BUY orders deduct money upfront.
- New orders match against existing opposite-side orders in price-time
  priority. Trades settle at the resting order's price.
- All trades are logged in `market_trades`.

## 11. Population simulation

Per tick:

- Each person consumes food and water.
- Approval drifts based on food/water coverage.
- Population grows or declines based on approval.
- High unrest (low approval + low stability + high pollution) emits a
  `population.protest_started` event.

## 12. Events

Random and scheduled events (`game/data/events.yaml`) — droughts,
earthquakes, pandemics, oil booms, holidays, political scandals, etc.
Each event has weight, cooldown, and effect map applied to a random
country in the world. Plugins can register new events dynamically.

## 13. Missions

Tutorial, daily, weekly, achievement, and seasonal missions
(`game/data/missions.yaml`). Each mission defines an objective
(metric/op/target) and a reward dict. Players claim completed missions
via the bot.

## 14. Alliances

Players may form alliances with shared treasury, joint wars, alliance
rankings, and member roles (leader, officer, member, recruit).

## 15. Rankings

Per-world rankings by: population, treasury, approval, stability,
education, healthcare, military_power, gdp, research_points. The bot
exposes the top-N view per metric.

## 16. Notifications

Server-emitted notifications (attack started, research completed,
factory built, mission completed, market filled, etc.) are stored per
player and surfaced via the bot's Notifications menu.

## 17. Tick engine

The game loop runs every `TICK_INTERVAL_SECONDS` (default 60s) and
walks every active world through ordered phases:

1. `pre_tick`
2. `production` — apply production/consumption, complete constructions.
3. `population` — grow/decline population, drift approval, raise unrest.
4. `economy` — apply taxes, treasury income, maintenance.
5. `research` — complete research whose timer expired.
6. `construction` — reserved for future use.
7. `military` — training completions, fuel consumption.
8. `transport` — cargo ship movement.
9. `events` — roll random events.
10. `missions` — evaluate mission progress.
11. `rankings` — recompute leaderboards.
12. `notifications` — flush queued notifications.
13. `post_tick`

Plugins may subscribe to any phase via the
`tick.phase.<phase_name>` hook.

## 18. Balance principles

- Early game: food/water is the bottleneck; population grows slowly.
- Mid game: steel & electricity gate industrial expansion.
- Late game: uranium & rare earth gate nuclear/space tech.
- Military: cheap infantry vs. expensive armor/air — combined-arms is
  rewarded by the combat formula.
- Market: price discovery is organic — no NPC buyers/sellers.

## 19. Anti-abuse

- Argon2id password hashing.
- JWT access (15 min) + refresh (30 days) with rotation on refresh.
- Rate limiting: 5 logins/min, 300 API calls/min, 120 bot actions/min/user.
- Audit log for admin actions.
- Soft deletes for countries & worlds (recoverable).
- Permission matrix enforced in services, not just routers.
