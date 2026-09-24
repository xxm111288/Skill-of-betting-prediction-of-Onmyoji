# Skill of Betting Prediction of Onmyoji

A self-contained agent **Skill** for predicting the outcome of **Duel Betting / Showdown Bidding (对弈竞猜)** in *Onmyoji (阴阳师)* — the limited-time event where the game stages two fully-built AI teams (Red vs. Blue) and players wager on which side wins.

The Skill does not guess. It carries a full, sourced mechanics knowledge base, walks a fixed six-step decision procedure, and runs a Monte-Carlo simulation over the real damage / accuracy / action-bar / onibi formulas to produce a win-rate range plus a betting recommendation — **including an explicit "too close to call, don't bet" verdict when that is the honest answer.**

---

## What's in the box

| Bundle | Size | Contents |
|---|---|---|
| `SKILL.md` | 13 KB | The workflow, knowledge-base navigation, environment rules, sourcing policy |
| `kb/` | ~1.39 MB | **The knowledge base** — 10 Markdown documents + machine-readable data |
| `scripts/simulate_duel.py` | ~52 KB | Monte-Carlo simulator (Python 3.10+, **standard library only**) |
| `assets/lineup_template.json` | 10 KB | Schema + annotated example for the `lineup.json` input |
| `references/intake.md` | 3 KB | Checklist for requesting match data from the user |
| `references/kb_map.md` | 8 KB | KB map, 12 known pitfalls, data-fetch API reference, verification query templates |

**Total: 17 files, ~1.4 MB.** No third-party dependencies. No machine-specific paths — drop it anywhere.

### Scale of the knowledge base

| Dataset | Coverage |
|---|---|
| **Shikigami (式神)** | **All 275** in the official roster — UR 1 / SP 51 / SSR 87 / SR 68 / R 38 / N 30 (231 in-house, 27 collab, 17 "Gua Tai"); **753 skill entries** |
| **Soul sets (御魂)** | **All 70** — 57 regular (2-piece + 4-piece) and 13 boss-type sets (2-piece only) |
| **Formulas** | 10 core formulas, each with applicability boundaries and counter-examples |
| **Mechanic entries** | Buffs / debuffs / crowd control / marks / damage types, plus dispel ordering |
| **Battle mechanics** | Action bar, onibi economy, Arbiter stacks, draw-breaker rules, group-attack targeting, AI behaviour and "acting-out" list |

Each shikigami record carries: id, name, rarity, category, awakenable flag, **full 6-star awakened panel** (ATK / HP / DEF / SPD / CRIT / CRIT DMG / Effect HIT / Effect RES), pre/post-awakening deltas, **verbatim skill text with onibi cost and Lv.2–5 upgrade effects**, and auto-derived role tags.

---

## Installation

**Option A — copy the folder.** Put `yys-duel-betting-predict/` into your agent's skills directory (e.g. `~/.workbuddy/skills/`, `~/.claude/skills/`, or your host's equivalent). The folder must contain `SKILL.md` at its root.

**Option B — extract the package.** `yys-duel-betting-predict.skill` is a plain ZIP. Extract it into the skills directory so the result is `<skills-dir>/yys-duel-betting-predict/SKILL.md`.

The Skill locates its knowledge base relative to `SKILL.md` (`<skill-dir>/kb/`), so there is nothing to configure. If a user-owned working copy of the knowledge base exists in the workspace, that one wins; only if neither is found does the Skill ask for a path.

---

## Quick start

1. Give the Skill the match: both teams' 5 shikigami, each unit's 8 panel stats, equipped soul sets, and — importantly — the **lineup slot numbers** shown in-game (these decide who soaks group attacks).
2. It writes `lineup.json` and runs:

```bash
python3 scripts/simulate_duel.py lineup.json --trials 20000 --out sim_result.json --sensitivity
```

3. It reads `sim_result.json` and reports: win-rate split, expected battle length, **sensitivity table** (which single parameter flips the result), the model's stated assumptions, and any mechanics it did *not* model.

Minimal `lineup.json` shape (see `assets/lineup_template.json` for the full annotated schema):

```json
{
  "max_unit_turns": 600,
  "arbiter_period": 5,
  "teams": {
    "red":  { "units": [
      { "name": "…", "pos": 1, "spd": 162, "atk": 5924, "hp": 18459, "def": 723,
        "crit": 85, "cdmg": 311, "hit": 0, "res": 48,
        "souls": ["破势", "荒骷髅"],
        "passive": { "revive": 0 },
        "skills": [{ "name": "…", "cost": 3, "coef": 6.2, "hits": 1, "when": "always" }] }
    ]},
    "blue": { "units": [ … ] }
  }
}
```

The simulator warns loudly about the things a human would otherwise miss:

- `[not crit-capped]` — a damage dealer below 100% CRIT means its CRIT DMG stat is doing nothing
- `[inert in Duel Betting]` — a soul set whose 2-piece passive does not apply in this mode
- `[mechanic not modelled]` — a legitimate soul set the simulator does not yet implement
- `[possible typo]` — a soul-set name that is not in the official 70

---

## The six-step workflow

1. **Intake.** Check whether the user supplied everything needed; if not, ask for it in one go — never substitute remembered or "typical" panels.
2. **Structure.** Build the team panel-comparison table, the per-unit table, and `lineup.json`.
3. **Preliminary read** against the six-step decision checklist (onibi & tempo → accuracy & control chains → output & soul-fit → survivability → Arbiter escalation → draw-breaker).
4. **Scenario walk-through.** 3–5 concrete play-by-plays, key levers, and variance sources — not a single verdict.
5. **Monte-Carlo simulation** with the bundled script, always including `--sensitivity`.
6. **Verdict.** A win-rate range with confidence tier (high-confidence / leaning / coin-flip), the recommended side, the single biggest uncertainty, and explicitly "don't bet" when warranted.

---

## Knowledge base contents

| File | What it answers |
|---|---|
| `00_总览与自检.md` | Overview, open-verification list, **erratum log**, delivery self-check |
| `01_玩法与预测框架.md` | Event rules, version anchors, terminology map, the **six-step decision checklist** |
| `02_核心数值与公式.md` | Meaning of the 8 stats; damage / accuracy / multi-hit / crit-expectation formulas with boundaries |
| `03_式神数据.md` | Deep cards for Duel-Betting-relevant shikigami, each with an **AI-risk assessment** |
| `03A_式神全量图鉴.md` | All 275 shikigami — 6-star panels, awakening deltas, auto role tags |
| `03B_式神技能全量.md` | All 275 shikigami — verbatim skill text, onibi cost, upgrade effects |
| `04_机制词条.md` | Dispellable / remove-only / mark-type taxonomy, control tables, dispel ordering |
| `05_御魂与套装.md` | Soul rules, per-set tables, **28 recorded conflict rulings**, 13-point fast-scan checklist |
| `05A_御魂全量.md` | All 70 soul sets — 2/4-piece text, drop sources, revision history, mode-validity |
| `06_战斗流程与AI行为.md` | Action bar, onibi economy, Arbiter, draw-breaker, targeting order, AI behaviour, "acting-out" list |
| `data/shishen.json` · `data/souls.json` | Machine-readable versions of the above |

---

## Data provenance and accuracy policy

Numbers were fetched, not remembered. The primary source is **NetEase's own shikigami-roster API** (`get_heroid_list` / `get_hero_attr` / `get_hero_skill` / `get_equip_list`), cross-checked against the official site, NetEase's Dashi guides, NGA and Bilibili player testing.

Every claim is tagged with its strength: `【official】` / `【player-tested】` / `【community consensus】` / `【unverified】`.

Non-negotiable rules baked into the Skill:

- **Never fabricate.** If no reliable source exists, the document says "no reliable source found, pending verification" — it does not fill the gap with older values or guesswork.
- **Two independent sources for any numeric claim, at least one official**, with link and fetch date.
- **Test-server ≠ live server.** Anything about *which modes an effect works in* must be checked against the most recent official patch note.
- **Conflicts get adjudicated, not averaged** — both readings are recorded with the reasoning behind the ruling.

Three findings worth calling out, because most community write-ups get them wrong:

1. **Duel Betting starts at 4 onibi** — not 3 (the value for soul/exploration dungeons).
2. **Duel Betting panels are not gear-derived.** They are generated by the Hundred Ghosts point-allocator, which is why you routinely see stat lines no legal soul loadout could produce.
3. **13 boss-type soul sets have no 2-piece effect in Duel Betting.** That includes the six sets widely described online as "Star Scar" sets with "PvP-active" 2-piece bonuses — the official 2026-04-15 patch note removed that category, reclassified all six as boss sets, and stated they no longer apply in Duel, Realm Raids or Dojo.

---

## Requirements

- **Python 3.10+** — the simulator uses the standard library only.
- Any agent host that supports Skills and can read files and run scripts.
- Optional: network access, if you want the Skill to verify time-sensitive facts (patch notes, event dates) rather than relying on the bundled cutoff.

---

## Keeping it current

The knowledge base is anchored to a date, and *Onmyoji* patches frequently. To bring it up to date:

1. **Patch notes first.** Look up the most recent official maintenance announcement (`阴阳师 <date> 维护更新公告`). Mode-validity changes — what works in Duel Betting, Realm Raids, Dojo — are announced there and nowhere else.
2. **New shikigami.** The official roster API is enumerable by id; fetch name, panel, and full skill text rather than transcribing screenshots.
3. **Rebalance passes.** Record changes in the affected document, and add a row to its changelog section. Append; do not rewrite the file.
4. **Log conflicts, don't average them.** If two sources disagree, record both readings and the reason for the ruling.

The bundled simulator carries its own soul-effect table and an explicit "modelled / not modelled / inert in this mode" split, so a new soul set fails loudly rather than silently computing the wrong thing.

---

## Repository layout

```
Skill-of-betting-prediction-of-Onmyoji/
├── README.md
├── yys-duel-betting-predict/          # the skill folder — copy this into your skills dir
│   ├── SKILL.md
│   ├── kb/                            # knowledge base (10 docs + data/)
│   ├── scripts/simulate_duel.py
│   ├── assets/lineup_template.json
│   └── references/
└── yys-duel-betting-predict.skill     # same thing, zipped for one-step install
```

---

## Scope, limitations, disclaimer

**In scope:** anything that changes *who dies first in an automated battle* — stats and formulas, shikigami skills, crowd control and marks, soul sets, onibi economy, action order, Arbiter escalation, AI release logic.

**Out of scope by design:** gacha odds, awakening/fragment/material drop rates, soul-farming teams, exploration/secret-dungeon/realm-raid/dojo/guild content, skins and cosmetics, PvP ranking and matchmaking, and the events themselves — except where their *combat mechanics* apply.

**Known limitations.** The simulator is a *heuristic comparative model*, not a re-implementation of the game engine. It does not model summons, multi-form transformations, assist attacks, damage chaining, or the precise timing of out-of-turn triggers; those are listed as "not modelled" in every run's output for the human to reason about. Absolute win rates should be treated as indicative; the ranking and the sensitivity analysis are where the value is.

**Version anchor.** Knowledge-base content reflects the **10th-anniversary version "永恒之章·拾光永恒"** (live 2026-09-09), with an information cutoff of **2026-09-24**. Boss-set reclassification, shikigami rebalances and new releases after that date require incremental updates.

**Disclaimer.** Content is AI-assisted and restricted to in-game data for reference only. This is a probabilistic reasoning aid, not an oracle — no responsibility is taken for any wager placed on the basis of its output. Wager responsibly.
