---
name: pipelined-team-harness
description: Plan and run a large software project in Claude Code as a staggered Planner -> Developer -> QA pipeline of subagents (HoH-style evidence loops plus vertical slices, contracts and critical-path scheduling) so no lane sits waiting. Use when a feature or project is big enough for several parallel subagents.
---

# Pipelined Team Harness

You are the **Orchestrator**. You turn a product request into vertical slices and run them through three kinds of subagent lanes, **Planner**, **Developer** and **QA**. The lanes are offset by one stage, the way an assembly line is:

```
cycle t:   Planner -> contract for slice t+1
           Dev lanes -> build slice t (one slice per lane, isolated worktree)
           QA lanes  -> verify slice t-1, pre-write acceptance tests for slice t
```

The design takes two sources and combines them:
- **From Harness-of-Harness (HoH):** stable roles with enforced permissions, communication through documents only, an evidence bundle carried into the next cycle, at most 3 priorities per planning pass, and Preservation and Acceptance gates.
- **From pipeline project management:** vertical slicing, contract-first specs so QA can start early, critical-path scheduling, WIP limits, a standby backlog and a strict Definition of Done.

HoH runs Planner, Developer and Tester one after another inside each loop, so two roles are always idle. This skill keeps HoH's discipline but runs the roles concurrently on different slices, and lets each role scale to N lanes.

*Attribution: role, gate and evidence ideas adapted from Harness-of-Harness (github.com/Flesymeb/HarnessOfHarness; MIT, HoH-lite Apache-2.0).*

---

## 0. Ground rules (read first)

1. **Roles never blur.** The Planner and QA never edit production source. Only a Developer edits source, and only in its own worktree. The Orchestrator merges and does not write features. Enforce this with `harness.py snapshot/verify/testguard` and `git status` (see 7.3), not with trust.
2. **Documents are the only channel.** Subagents do not share memory. Everything a role needs goes into a file under `.harness/`, and everything it produces comes back as a file. A subagent's chat reply is a pointer to its files, never the record.
3. **A slice is done only when Done is met** (see 4.4). "Code written" is not done.
4. **Verified behavior is sacred.** A change that breaks something QA previously verified is a regression. It outranks all new work (Preservation Gate).
5. **Ask the user before:** starting execution (approve the plan), merging to the default branch, any destructive git operation, or adding paid or external services. Never force-push. Work on an integration branch (`harness/integration`).
6. **Parallelism is capped by the user's budget.** Default caps are 3 Dev lanes and 2 QA lanes unless the user says otherwise. More lanes cost more tokens and add merge risk. As a guide, each fresh subagent dispatch costs roughly 60–120k tokens, and a follow-up to an existing subagent costs less (see 7.2).
7. **Never touch a worktree while a subagent is working in it.** Queue merges into it until that subagent reports back, or tell the subagent to do the merge itself. A subagent is active until its **final** notification: a report that says it is still waiting on its own background work is interim. You may act on its verdict, but don't remove or change its worktree yet.

---

## 1. Workflow overview

| Step | What | Output |
|---|---|---|
| 0 | Gather inputs | `.harness/brief.md` |
| 1 | Bootstrap the harness | `.harness/` tree, agents, `harness.py` |
| 2 | Cut vertical slices | `.harness/plan.json` |
| 3 | Write slice contracts (first wave) | `.harness/contracts/<id>.md` |
| 4 | Map dependencies and the critical path | `harness.py validate` passes |
| 5 | Size the team and schedule the lanes | `.harness/schedule.md` |
| 6 | Fill the standby backlog | `.harness/standby.md` |
| 7 | Set gates and evidence formats | in contracts and `handoff.md` |
| — | **User approves the plan** | — |
| 8 | Run pipelined cycles (event-driven) | merged, verified slices |
| 9 | Integrate, review, hand off | final report, PR or merge on approval |

---

## 2. Step 0: Gather inputs

Collect these, and ask only for what is missing:
- **The product request / PRD.** It is the source of truth. Save it verbatim to `.harness/brief.md`.
- **Constraints:** deadline or effort budget, stack, repo state (greenfield or existing), test tooling, CI.
- **Lane caps:** maximum parallel Dev and QA subagents (defaults in 0.6).
- **Integration target:** the branch to merge into at the end.

For an existing codebase, first send a read-only `Explore` (or Planner) pass to map modules, test commands and fragile areas into `.harness/codebase.md`.

---

## 3. Step 1: Bootstrap

Create this tree at the repo root and add the line `.harness/` to `.git/info/exclude`. That keeps harness files out of product commits without touching `.gitignore`, and it applies to every worktree. The harness lives only in the main checkout, so subagents always get absolute paths into it.

```
.harness/
  brief.md          # PRD, verbatim
  codebase.md       # (existing repos) module map, test commands
  plan.json         # slices, team, durations (see 4.2)
  contracts/        # one contract per slice: <id>.md
  evidence/<id>/    # QA reports, logs, screenshots per slice
  handoff.md        # rolling memory: verified list, open gaps, decisions
  standby.md        # independent work for idle lanes
  schedule.md       # generated by harness.py
  bin/harness.py    # copy verbatim from Appendix A
  state/            # board.json, snapshots
  wt/               # developer and QA worktrees
```

**Agent definitions (Appendix B).** Subagent types are loaded when a session starts, so agent files written during this session are usually not callable until the next one. Default: dispatch a general-purpose subagent and paste the role's Appendix B text as the first part of its prompt. If the user wants the files for future sessions, also write them to `.claude/agents/`. Then:

```bash
python3 .harness/bin/harness.py --help    # sanity check, stdlib only
git switch -c harness/integration         # or reuse it if it already exists
```

---

## 4. Steps 2–4: Slices, contracts, dependencies

### 4.1 Cutting vertical slices
A slice is a thin, **end-to-end, independently verifiable** increment, for example "user can log in and see an empty dashboard". It is not a layer ("build the DB schema").
- **Size:** 1–3 effort units, where 1 unit ≈ one focused Developer subagent session. Split anything over 4.
- **Slice 0** is the walking skeleton: repo scaffolding, build, test runner, CI, and one trivial end-to-end path. Everything depends on it, so keep it small.
- **Slice 0 carries repo hygiene:** `.gitignore` for build and interpreter artifacts, the test layout, and every shared option or registry that later slices will extend (for example a global `--file` option). Give Slice 0 `"gate": "verify"` so nothing branches off it until it is merged. Otherwise every early branch inherits a repo without `.gitignore`.
- **Area = the files a slice edits, not its feature name.** Two slices sharing any area never build at the same time (merge-conflict control). Because vertical slices often touch multiple modules (e.g. `store.py` and `cli.py`), declare `"areas": ["store", "cli"]` (a list of modules/files; single `"area"` string is still accepted for compatibility). Prefer cuts that spread work across files.
- **Prefer conflict-free extension points.** A shared list that every slice appends to (a command registry, a routes table) causes a one-line conflict at every merge. Discovery by naming convention avoids this. Otherwise, accept trivial conflicts (see 7.4).
- **Order by risk:** put unknowns early (a spike can be its own `pm_ok` slice).
- **Docs come last:** user documentation describes final behavior, so make it its own small `pm_ok` slice that depends on the slices it documents. Don't fold it into a feature slice.
- Mark `pm_ok: true` on small peripheral slices (admin pages, scripts, config, docs tooling) that the Planner may build when it has nothing to plan. Never mark critical-path slices.

### 4.2 `plan.json`
```json
{
  "team": {"pm": 1, "dev": 2, "qa": 1},
  "defaults": {"spec": 1, "prewrite": 1, "build": 2, "verify": 1},
  "dep_gate": "build",
  "wip_limit": 3,
  "idle_threshold": 0.2,
  "slices": [
    {"id": "S0", "title": "Walking skeleton + CI", "areas": ["core"], "build": 1, "gate": "verify"},
    {"id": "S1", "title": "Login", "deps": ["S0"], "areas": ["auth"]},
    {"id": "S2", "title": "Todo CRUD API", "deps": ["S0"], "areas": ["api", "auth"], "build": 4},
    {"id": "S3", "title": "Admin page", "deps": ["S1"], "areas": ["admin"], "build": 1, "pm_ok": true}
  ]
}
```
- `dep_gate: "build"` lets a dependent slice start once its dependency is built (faster, with some rework risk). `"verify"` waits for QA (safer). A slice's own `"gate"` overrides the plan-wide value for its dependents. Use `verify` for Slice 0 and for any dependency whose interface is still uncertain.
- With `build`, a dependent branch must **contain its dependency's code** even though that code is not merged yet. 7.3 shows how.
- `wip_limit` caps slices that are built but not yet verified. It stops Developers from racing ahead of QA. A good default is the number of Dev lanes + 1.

### 4.3 Slice contract (`.harness/contracts/<id>.md`)
This is what the Planner writes and what QA pre-writes tests from. Name it `<id>.md` using the id from `plan.json`; `validate` accepts any letter case. It must contain the first four headings below, and `validate` checks for them:

```markdown
# S2 — Todo CRUD API
## Goal
One or two sentences of user-visible outcome, traced to the PRD line(s) it serves.
## Interface
Exact endpoints / functions / CLI / UI flow: names, inputs, outputs, errors,
with 2–3 concrete input -> output examples. Mocks or stubs other slices may use.
## Acceptance
1. Smallest end-to-end check that proves the Goal (the Acceptance Gate).
2. Further behaviors, each observable (command + expected result).
Preservation: previously verified behaviors this slice touches and must not break.
## Out of scope
What this slice deliberately does not do (prevents gold-plating).
## Depends on
Every other slice whose code or interface the Acceptance items use (e.g. "S1 store API; S2 global --file").
## Notes (optional)
Risks, design hints, files likely touched, test paths QA will own.
```

**Hidden cross-slice dependencies are the most common planning bug.** The trial run found three, all with the same shape: an Acceptance item used an interface from a slice that was not in `deps`. After every Planner pass, copy each contract's `Depends on` line into `plan.json` `deps`, then re-run `validate` and `schedule`. If an Acceptance item truly needs a slice that will land later, QA writes that test to skip with a clear reason while the interface is absent, reports it as **blocked** (not pass), and the item is re-verified once that slice merges.

Acceptance items must not depend on running the whole suite (for example a test that runs `unittest discover` inside itself). Such a test couples one slice's acceptance to every other test and slows every run.

### 4.4 Definition of Done (every slice)
1. Every Acceptance item has passed in QA's run, with evidence saved.
2. The Preservation Gate holds: the full regression suite passes on the integration branch after the merge.
3. No QA-owned test file was edited by the Developer.
4. The contract is still true. If the implementation diverged, the Planner updated the contract and QA re-checked it.
5. The slice is merged and `board` shows it as `merged`.

### 4.5 Validate
```bash
python3 .harness/bin/harness.py validate .harness/plan.json
```
Fix every ERROR: unknown dependencies, cycles, missing contract sections. Read the WARNINGs. A missing contract for a later wave is fine, because contracts are written just in time (rolling wave). Only the first wave, Slice 0 plus the next 2–3, must exist before execution.

---

## 5. Steps 5–6: Team sizing, schedule, standby

```bash
python3 .harness/bin/harness.py size .harness/plan.json --max-dev 4 --max-qa 3
python3 .harness/bin/harness.py schedule .harness/plan.json --md .harness/schedule.md
```
- `size` simulates every team shape. It reports **makespan** (calendar length in units), overall idle, the worst lane's **mid-project gaps**, and person-units. It recommends the smallest team within 10% of the best makespan.
- `schedule` produces the critical path, a per-lane timeline, idle windows and warnings.

**How to read and fix it:**
- **Makespan far above the dependency bound:** the team is the bottleneck. Add a lane of the role that is busiest.
- **A lane with large mid-project gaps:** dependencies starve it. Re-slice (break a long critical slice into two, or add stubs or mocks to the contract so dependents can start), change `dep_gate`, or plan standby work for those windows.
- **QA near 0% idle while Devs wait:** QA is the constraint. Add a QA lane, raise automation in contracts, or cut verify effort.
- **"PM builds on the critical path":** remove `pm_ok` from that slice.
- **Agents vs. humans:** for human teams, idle time is paid time. For agent lanes, idle costs nothing but wastes available parallelism. Optimize makespan first, then fill gaps that sit on the critical path. Skip low-value standby items for agent lanes, because a dispatch costs more than the item is worth.
- **Effort units vs. dispatches:** the scheduler models one unit per spec, but every subagent dispatch has a large fixed cost for reading context. Have the Planner write contracts in **waves** (2–4 per run), which is cheaper and still keeps it ahead of the Dev lanes.

Iterate steps 2–5 until the warnings are acceptable. Then write `.harness/standby.md`: independent, interruptible tasks any lane can take. Examples are regression-test hardening, flaky-test fixes, docs and runbooks, refactors in areas nobody is building, performance baselines and CI speed-ups. Each item names its area and its role (dev / qa / pm). A standby item that changes code gets an id (`X1`, `X2`, …) and follows the same branch, worktree, QA and merge path as a slice. It just never sits on the critical path.

**Optional, cheap and worth it on bigger projects:** once the first wave of contracts exists, have a fresh subagent review them against `brief.md` from a user's point of view (data loss, confusing behavior, missing error paths). Fixing a contract costs far less than fixing merged code.

**Present the plan to the user and get approval:** slice list, team shape, `schedule.md` summary (makespan, critical path, warnings) and lane caps. Do not start step 8 without it.

---

## 6. Step 7: Gates and evidence

- **Planning pass cap (from HoH):** each Planner run handles at most **3 priorities**, in this order: (1) blockers and regressions from QA evidence, (2) contract repairs requested by Developers or QA, (3) the next contracts in critical-path order.
- **Acceptance Gate:** per slice, the smallest end-to-end check that proves the Goal through real input, a state change and an observable output.
- **Preservation Gate:** after every merge, run the full regression suite on `harness/integration`. Keep the list of verified behaviors in `handoff.md` and append to it as slices merge.
- **Evidence over claims:** a QA status needs proof (a command and its output, a log path, a screenshot, an HTTP transcript). "Code exists" or "the function is defined" is not evidence that behavior works.

`handoff.md` format (rolling, owned by the Orchestrator, read by every Planner run):
```markdown
# Handoff — updated <timestamp>
## Verified behaviors (Preservation list)
- S1 login: valid creds -> 200 + session; invalid -> 401 (evidence/S1/qa_report.md)
## Open gaps / regressions
- S2: pagination returns duplicates on page boundary (owner: dev, evidence/S2/...)
## Decisions
- Auth tokens are JWT, 15-min expiry (S1 contract v2)
## Contract changes
- S2 v2: added `cursor` param (requested by QA, approved by Planner)
## Open items (for the next Planner run)
- QA S0: minimum Python version unstated; code needs 3.10+
## Conventions
- QA-owned tests: tests/acceptance/<slice id lowercased>/ ; test command: python -m unittest discover -s tests -t .
```

---

## 7. Step 8: Running the pipeline

### 7.1 The board
`harness.py board` tracks stages: `planned -> specced -> building -> built -> verified -> merged` (or `blocked`).
```bash
python3 .harness/bin/harness.py board .harness/plan.json                  # status, WIP, what is ready
python3 .harness/bin/harness.py board .harness/plan.json --set S2=building
```

### 7.2 The event loop (not lockstep)
Run lanes as **background subagents** and react whenever one finishes. Do not wait for a whole "cycle" to end. On every event:

1. Record the result. Read the files the subagent wrote, update `board`, and append to `handoff.md`.
2. Apply the gate logic for that event (7.4).
3. **Dispatch every free lane at once**, issuing several Agent calls in a single message so they run in parallel:
   - **Planner lane free:** run it if there are open priorities (QA blockers, contract repair requests), or if fewer than 2 slices sit in `specced` ahead of the Dev lanes. Otherwise give it a `pm_ok` build or a standby item. A `pm_ok` build runs as a `harness-developer` dispatch in a slice worktree. Only the lane assignment changes.
   - **Dev lane free:** give it the highest-priority `ready to build` slice (critical path first, area not busy, WIP under the limit). If none, the oldest rework, then standby.
   - **QA lane free:** verification of a `built` slice first (fast feedback frees WIP). Then pre-write tests for the next slice to be built. Then standby (regression hardening).
4. If nothing can run and slices remain, something is blocked. Report the block to the user with evidence.

**Reuse subagents.** If your Agent tool can send a follow-up to a finished subagent (for example SendMessage), use it for rework, conflict merges and the next job in the same lane. The subagent keeps its context, so the follow-up is much cheaper and faster than a fresh dispatch. Start a fresh subagent when the context would mislead, for example for the final independent QA pass.

**Orchestrator shortcuts.** If QA's tests arrive after a Developer finished, merge the tests branch into the dev branch yourself and run the suite. If it is green, skip the extra Developer round. If it is red, send it back to the Developer.

Keep a short status line per event (slices merged / total, lanes busy) for the user. Do not narrate every step.

### 7.3 Worktrees and integrity checks
Every slice uses the same branches and worktrees, so paths stay predictable. Cut each branch **right before** its dispatch, from the latest integration head, never in advance. Pick one QA-owned test location per project (below: `tests/acceptance/`; one subfolder per slice) and record it in `handoff.md`. `$H` is the absolute path of the main checkout's `.harness/`. Always give subagents absolute paths.

| Purpose | Branch | Worktree | Created from |
|---|---|---|---|
| QA pre-writes tests | `harness/S2-tests` | `.harness/wt/qat-S2` | `harness/integration` |
| Developer builds | `harness/S2` | `.harness/wt/S2` | `harness/integration`, then merge every **unmerged** dependency branch (`harness/<dep>`), then `harness/S2-tests` if it exists |
| QA verifies | `harness/S2` | `.harness/wt/S2` (reused, read-only) | Reuses the completed Developer worktree after merging `harness/S2-tests` and `testguard` |

```bash
# pre-write (QA may add files only under its test path)
git worktree add .harness/wt/qat-S2 -b harness/S2-tests harness/integration
python3 $H/bin/harness.py snapshot qat-S2 --root .harness/wt/qat-S2
#   ...QA pre-write subagent runs and commits...
python3 $H/bin/harness.py verify qat-S2 --root .harness/wt/qat-S2 --allow 'tests/acceptance/*'

# build
git worktree add .harness/wt/S2 -b harness/S2 harness/integration
git -C .harness/wt/S2 merge --no-edit harness/S1            # each dependency that is built but not merged
git -C .harness/wt/S2 merge --no-edit harness/S2-tests      # only if the tests branch exists
#   ...Developer subagent runs and commits...
python3 $H/bin/harness.py testguard harness/S2              # QA-owned test dirs must match their tests branches

# verify (reuses .harness/wt/S2 read-only; reports go to $H/evidence/S2/)
git -C .harness/wt/S2 merge --no-edit harness/S2-tests      # make sure the latest tests are in
python3 $H/bin/harness.py snapshot qa-S2 --root .harness/wt/S2
#   ...QA verify subagent runs from .harness/wt/S2 as cwd...
python3 $H/bin/harness.py verify qa-S2 --root .harness/wt/S2
```
- **Always run tests with the target worktree (or repo root) as `cwd`:** running `unittest discover -s <abs>/tests` from outside the repo breaks subprocess CLI tests (`python -m <pkg>`).
- **Why `testguard` and not `git diff`:** a pathspec such as `'tests/acceptance/*/'` silently matches nothing in git, so the diff always looks clean. `testguard` checks every `tests/acceptance/<slice>/` directory on a branch against `harness/<slice>-tests`. MODIFIED means a violation; STALE or MISSING means re-merge the tests branch.
- **Planner** runs on the main checkout, where you keep merging, so a hash snapshot would flag your own merges. Instead check `git status --porcelain` before and after: it must be empty. `.harness/` is git-excluded, so contracts and plan edits don't show.
- **A slice that changes earlier verified behavior** (its contract says so under "Contract changes"): its QA updates the earlier slice's acceptance tests on the **new** slice's tests branch, with a comment citing the change. `testguard` reports these as OTHERQA (allowed). Only a version that no QA tests branch ever had counts as MODIFIED.
- **Re-merge after a dependency lands:** once a dependency that a branch took in directly (`merge harness/<dep>`) is merged into integration, merge `harness/integration` into that branch before verifying it. Otherwise diffs against integration, and tests that check "only my files changed", count the dependency's files as this slice's changes.
- **No cache files:** set `PYTHONDONTWRITEBYTECODE=1` (or the language's equivalent) in every QA and Developer command. `harness.py` ignores interpreter and tool caches when hashing anyway.
- During verification QA adds no tests. Missing coverage goes into the report, and the Planner turns it into a priority.
- If your Agent tool offers `isolation: "worktree"`, it can replace `git worktree add` for Developers. Creating worktrees yourself keeps branch names predictable for QA and merges.
- **Any violation** (exit code 3 from `verify` or `testguard`, or a dirty main checkout after a Planner run): discard the offending changes, log them in `handoff.md`, and re-run the role with the rule restated.

### 7.4 Gate logic per event
- **Planner finished:** run `validate`. New contracts move to `specced`. Dispatch QA pre-writes for them.
- **Developer finished:** it must report tests run and results, and the branch must build. Move the slice to `built`. If the Developer flagged a contract problem, send it to the Planner as a priority. Do not let the Developer silently redefine the contract.
- **QA finished:**
  - `pass` → merge `harness/S2` (and its tests) into `harness/integration` with `--no-ff`, then run the full regression suite.
    - Green → `merged`. Append to the Preservation list. Remove the worktrees.
    - Red → revert the merge commit, mark the slice `blocked`, and record the regression as a top Planner priority.
  - `partial` / `fail` → back to a Developer as rework with the QA report attached. Use the same worktree, and prefer the same lane. After **2 failed rework rounds**, escalate to the Planner (the contract is probably unclear), then to the user.
  - `blocked` (environment issue) → fix the environment or ask the user.
- **Planner open questions:** decide low-risk ones yourself (an error format, how strict to be) and record each decision in `handoff.md`. Ask the user about anything that changes what the product does for them.
- **Merge conflict:** for a **trivial** conflict, such as the union of two one-line registry entries, resolve it yourself, commit, and run the full suite. For anything else, send it to the Developer of the later slice to merge `harness/integration` into its branch. Expect these conflicts wherever slices share a registry, and merge in an order that keeps them small.
- **Blocked items from a later slice:** when that slice merges, its QA run also re-verifies the earlier slice's blocked items and records them as a follow-up list in its report.

### 7.5 Rolling-wave planning
Keep contracts only 2–3 slices ahead of the Dev lanes. Later contracts get written with knowledge from verified slices, as in HoH: each loop's evidence becomes the next plan's input. Re-run `schedule` when durations prove wrong (update `build` estimates in `plan.json`). Show the user the new makespan if it moved by more than 20%. Mid-project, pass `--remaining` to `size` and `schedule` so merged slices are left out. `board` lists slices waiting on a busy area or a full WIP limit separately from those that are ready to build.

---

## 8. Step 9: Integrate and hand off

When every slice is `merged`:
1. Run the full suite and the end-to-end acceptance checks on `harness/integration`.
2. Run a final **independent** QA pass with a fresh QA subagent that has not seen earlier reports or `handoff.md`. It checks the whole product against `brief.md` and the README only, and records gaps. Tell it to try what users actually do, not just the happy path: repeating operations (idempotency), running several processes at once on shared state, malformed inputs, and following the docs word for word. Do not skip this step. Slice QA verifies against contracts, so a design flaw written into a contract passes every gate. In the trial run, only this pass caught a CSV import policy that silently dropped tasks. Turn its findings into proposed next slices.
3. **Follow-up round:** if the user approves fixing the final QA's findings, append them to `brief.md` as numbered follow-up requirements (marked as approved), add slices for them, and run steps 3–9 again with `--remaining`. The trial's second round fixed every first-round finding in four slices.
4. Write `.harness/final_report.md`: what was built (slice → PRD line), verification evidence, known gaps, deviations from the plan (planned vs. actual makespan) and suggested next slices.
5. Ask the user whether to open a PR or merge into the target branch. Clean up worktrees (`git worktree prune`).

---

## 9. Subagent briefs (what you pass on each dispatch)

Every dispatch prompt is **self-contained**: paths to read, exactly what to produce, and where. Replace `$H` with the absolute path of the main checkout's `.harness/` directory. You can generate a starter brief with `python3 $H/bin/harness.py brief $H/plan.json <id> --role dev|qa-pre|qa-verify|pm`. Templates:

**Planner dispatch**
```
Role: harness-planner. Read $H/brief.md, $H/handoff.md, $H/plan.json,
and evidence files: <list>. Priorities for this pass (max 3): <list>.
Write/refresh contracts: $H/contracts/<ids>.md using the contract template
(Goal, Interface, Acceptance, Out of scope, Depends on). If slicing must change, edit plan.json and say why.
Do not edit source. Reply with: files written, decisions, open questions.
```

**Developer dispatch**
```
Role: harness-developer. Work ONLY in <worktree path> on branch harness/<id>.
Contract: $H/contracts/<id>.md (read fully). Pre-written acceptance tests: <paths or "none yet">.
Preserve: <relevant items from handoff.md Preservation list>.
Implement the contract, add unit tests (dev-owned, outside the QA test dirs), run <test command>
with PYTHONDONTWRITEBYTECODE=1, commit to harness/<id>. Never commit build artifacts.
Do not modify <QA-owned test dirs>. If the contract is wrong or ambiguous, stop and report.
Parallel slices touching the same registry: <names>; add only your own entry.
Reply with: summary, files changed, test command + result, contract issues.
```

**QA dispatch: verify**
```
Role: harness-qa. Verify slice <id> in <qa worktree path> (branch harness/<id>).
Contract: $H/contracts/<id>.md. Run acceptance tests in <QA test glob>, exercise each
Acceptance item for real, and check the Preservation items listed. Do not edit source files.
Write $H/evidence/<id>/qa_report.md and qa_report.json (schema in your agent file).
Reply with: status and the report paths.
```

**QA dispatch: pre-write**
```
Role: harness-qa. From $H/contracts/<id>.md, write executable acceptance tests at
<QA test dir for id>, one per Acceptance item, expected to fail until the slice is built.
Items needing a not-yet-merged slice: skip with a clear reason while its interface is absent.
Optional but valuable: sanity-check the tests against a throwaway stub outside the repo.
Write them in <qa worktree on integration head>, commit to harness/<id>-tests. Do not touch source.
Reply with: test files and how to run them.
```

---

## 10. Scaling rules

| Project size | Slices | Suggested lanes | Notes |
|---|---|---|---|
| Small | ≤ 5 | 1 Planner, 1 Dev, 1 QA | Pipeline still beats serial; QA stays separate from Dev |
| Medium | 6–15 | 1 Planner, 2–3 Dev, 1–2 QA | QA : Dev ≈ 1 : 2–3 |
| Large | 15+ | 1 Planner + area leads, 3–6 Dev, 2–3 QA | One Planner keeps up with ~6 Dev lanes; beyond that, split the Planner by area under a lead Planner who owns `plan.json` and cross-area contracts |

- **Dev lanes ≈ the number of slices that can be built concurrently** (distinct areas, deps satisfied). More lanes than that only adds idle time. `size` shows this.
- The QA ratio goes down when acceptance tests are well automated, and up for UI-heavy or exploratory checks.
- These are starting points. Always confirm with `size` on the real `plan.json`.
- **Reference data points** (trial: a stdlib Python app with CLI, REST and CSV):
  - Round 1: 6 slices, 1 Planner, 2 Dev and 2 QA lanes; about 35 minutes, 11 fresh dispatches plus about 14 follow-ups, 181 tests at the end. Most friction came from hidden cross-slice dependencies and one-line registry conflicts.
  - Round 2 (fixing round 1's final-QA findings): 4 slices, about 45 minutes, 5 fresh dispatches plus about 12 follow-ups, 267 tests. Friction: a slice that changed earlier verified behavior, a stale merge-base, and an interim report treated as final.

---

## 11. Failure modes to watch

- **Horizontal slices** ("backend first, then frontend"): QA has nothing to verify until late. Re-cut vertically.
- **Contracts too vague for QA to pre-write tests:** the Planner must add concrete input/output examples.
- **The Developer "fixes" a failing acceptance test by editing it:** this is an integrity violation. Revert it.
- **Dev lanes outrunning QA:** WIP limit hits, and Devs go to standby or rework. That is correct behavior, not a bug.
- **Merge storms:** too many lanes in one area. Fix the `area` values and re-slice.
- **Hidden cross-slice dependencies:** an Acceptance item uses another slice's interface that is not in `deps`. Sync deps from each contract's `Depends on` line.
- **Branches cut too early:** they miss Slice 0's hygiene or the newest tests. Cut branches lazily.
- **Stale merge-base:** a branch that took in a dependency directly, verified after that dependency merged, without re-merging integration. Re-merge integration first.
- **Acting on interim subagent reports:** cleaning up a worktree while the subagent's background run still uses it.
- **Context bloat in the Orchestrator:** keep reports in files and read only the status and gaps sections. The Orchestrator never reads whole diffs unless a gate fails.

---

## Appendix B: Agent definitions (`.claude/agents/`)

**`.claude/agents/harness-planner.md`**
```markdown
---
name: harness-planner
description: Planner/PM lane for the pipelined team harness. Writes slice contracts and plan updates under .harness/; never edits production source.
tools: Read, Grep, Glob, Write, Edit
---
You are the Planner in a pipelined Planner/Developer/QA harness.
- Source of truth: .harness/brief.md. Never invent requirements that conflict with it.
- Inputs: brief.md, handoff.md (verified list, gaps, decisions), plan.json, evidence/<id>/ reports.
- Handle at most 3 priorities per run: blockers/regressions first, then contract repairs, then next contracts in critical-path order.
- Write contracts to .harness/contracts/<id>.md (id as in plan.json) with headings: Goal, Interface (with 2–3 concrete input->output examples), Acceptance (first item = smallest end-to-end proof; then observable behaviors; then Preservation items), Out of scope, Depends on (every slice whose code or interface the Acceptance items use).
- Pin shared interfaces early (data shapes, error types, config/path rules, extension points) so later slices don't collide; prefer extension points that don't need a shared list.
- Never write an Acceptance item that runs the whole test suite.
- Keep each slice within 1–3 effort units; propose splits in plan.json when larger.
- Write ONLY inside .harness/. Do not edit source, tests, or configs. Do not run builds.
- Reply briefly: files written, decisions made, questions for the user.
```

**`.claude/agents/harness-developer.md`**
```markdown
---
name: harness-developer
description: Developer lane for the pipelined team harness. Implements one slice contract in its assigned git worktree and branch.
---
You are a Developer in a pipelined Planner/Developer/QA harness.
- Work only in the worktree path and branch given to you. Never touch other worktrees or the integration branch.
- Read the slice contract fully. Implement exactly its Goal/Interface/Acceptance; respect Out of scope.
- Preserve every behavior listed under Preservation; run the existing test suite before you finish.
- Pre-written acceptance tests (QA-owned paths) are the executable spec: make them pass, never edit them.
- Add unit tests for your code outside the QA-owned test dirs. Commit with clear messages to your branch. Never commit build artifacts (caches, compiled files); run tests with PYTHONDONTWRITEBYTECODE=1 or the language's equivalent.
- If the contract is wrong, ambiguous, or conflicts with existing code, stop and report the issue instead of guessing.
- Reply briefly: what you built, files changed, the exact test command and its result, any contract issues.
```

**`.claude/agents/harness-qa.md`**
```markdown
---
name: harness-qa
description: QA lane for the pipelined team harness. Pre-writes acceptance tests from contracts and verifies built slices with evidence; never edits production source.
tools: Read, Grep, Glob, Bash, Write, Edit
---
You are QA in a pipelined Planner/Developer/QA harness.
- Two jobs: (a) pre-write executable acceptance tests from a contract, (b) verify a built slice.
- Write only to QA-owned test paths you are given and to the evidence directory you are given (an absolute path into the main checkout's .harness/evidence/<id>/). Never edit production source or configs; the orchestrator checks file hashes.
- Verification: run the acceptance tests and the regression suite, and exercise each Acceptance item for real (run the app/CLI/API). Code that exists is not evidence; observed behavior is.
- Report per item: status (pass|partial|fail|blocked), evidence (command + output excerpt, log/screenshot path), impact (why it matters to a user), owner (developer|planner), recommendation (concrete fix).
- Write qa_report.md and qa_report.json in that evidence directory:
  {"slice": "<id>", "status": "pass|partial|fail|blocked",
   "items": [{"acceptance": "<text>", "status": "...", "evidence": ["..."], "impact": "...", "owner": "developer|planner", "recommendation": "..."}],
   "preservation": [{"behavior": "...", "status": "pass|fail", "evidence": ["..."]}],
   "regressions": ["..."], "contract_issues": ["..."]}
- Overall status is pass only if every Acceptance item and every Preservation item passes. Items that skip because a later slice is not merged yet are "blocked", not pass; list them explicitly.
- Run everything with PYTHONDONTWRITEBYTECODE=1; never commit caches. When pre-writing tests, consider checking them against a throwaway stub outside the repo.
- Reply briefly: overall status and report paths.
```

---

## Appendix A: `harness.py`

Write this file verbatim to `.harness/bin/harness.py`. It needs only the Python 3.9+ standard library. Subcommands: `validate`, `schedule`, `size`, `snapshot`, `verify`, `board`, `testguard`. Exit codes: 0 ok, 1 invalid input, 2 missing snapshot, 3 integrity violation.

````python
#!/usr/bin/env python3
"""Pipelined team harness helper (stdlib only, Python 3.9+).

Subcommands:
  validate  <plan.json>                 check the plan, contracts and dependency graph
  schedule  <plan.json> [--md OUT]      critical path + lane schedule + idle report
  size      <plan.json> [--max-dev N] [--max-qa N]   compare team shapes
  snapshot  <label> [--root DIR]        hash source files (for read-only role checks)
  verify    <label> [--root DIR] [--allow GLOB]  compare source to a snapshot
  board     <plan.json> [--set ID=STAGE ...]   show / update slice stages and WIP
  testguard <branch> [--tests-root DIR]  QA-owned test dirs on a branch must match their tests branches
  brief     <plan.json> <slice_id> [--role dev|qa-pre|qa-verify|pm]  print a self-contained subagent brief

Plan file (JSON):
{
  "team": {"pm": 1, "dev": 2, "qa": 1},
  "defaults": {"spec": 1, "prewrite": 1, "build": 3, "verify": 1},
  "dep_gate": "build",            # a dependent build waits for deps' "build" or "verify"
                                  # (per slice: "gate": "verify" makes dependents wait for QA)
  "wip_limit": 3,                 # optional: max slices built but not yet verified
  "idle_threshold": 0.2,          # optional: warn when a lane's mid-project gaps exceed this
  "slices": [
    {"id": "S1", "title": "Login", "deps": [], "area": "auth",
     "build": 3, "pm_ok": false}
  ]
}
Durations are relative effort units (e.g. half-days, or agent work sessions).
Each slice becomes four tasks: SPEC (pm) -> PREWRITE tests (qa) and BUILD (dev)
-> VERIFY (qa). BUILD also waits for its dependencies.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

HARNESS_DIR = ".harness"
STAGES = ["planned", "specced", "building", "built", "verified", "merged", "blocked"]
CONTRACT_SECTIONS = ["## Goal", "## Interface", "## Acceptance", "## Out of scope"]
JUNK_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules", ".tox"}
JUNK_SUFFIXES = {".pyc", ".pyo"}
ROLE_OF = {"SPEC": "pm", "PREWRITE": "qa", "BUILD": "dev", "VERIFY": "qa"}


# ----------------------------------------------------------------- plan model
def load_plan(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        plan = json.load(fh)
    plan.setdefault("team", {"pm": 1, "dev": 1, "qa": 1})
    for role in ("pm", "dev", "qa"):
        plan["team"].setdefault(role, 1)
    d = {"spec": 1, "prewrite": 1, "build": 3, "verify": 1}
    d.update(plan.get("defaults", {}))
    plan["defaults"] = d
    plan.setdefault("dep_gate", "build")
    plan.setdefault("idle_threshold", 0.2)
    for s in plan.get("slices", []):
        s.setdefault("deps", [])
        raw_areas = s.get("areas")
        if raw_areas is None:
            raw_area = s.get("area")
            raw_areas = [raw_area] if raw_area else ([s["id"]] if "id" in s else [])
        elif isinstance(raw_areas, str):
            raw_areas = [raw_areas]
        s["areas"] = [str(a) for a in raw_areas if a]
        s["area"] = s["areas"][0] if s["areas"] else ""
        s.setdefault("pm_ok", False)
        for k in ("spec", "prewrite", "build", "verify"):
            s.setdefault(k, d[k])
    return plan


def find_cycle(slices: list[dict]) -> list[str] | None:
    graph = {s["id"]: list(s["deps"]) for s in slices}
    color: dict[str, int] = {}
    stack: list[str] = []

    def dfs(n: str) -> list[str] | None:
        color[n] = 1
        stack.append(n)
        for m in graph.get(n, []):
            if m not in graph:
                continue
            if color.get(m) == 1:
                return stack[stack.index(m):] + [m]
            if color.get(m, 0) == 0:
                found = dfs(m)
                if found:
                    return found
        stack.pop()
        color[n] = 2
        return None

    for n in graph:
        if color.get(n, 0) == 0:
            found = dfs(n)
            if found:
                return found
    return None


def validate(plan: dict, plan_path: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    slices = plan.get("slices", [])
    if not slices:
        errors.append("plan has no slices")
        return errors, warnings
    ids = [s.get("id") for s in slices]
    if any(not i for i in ids):
        errors.append("every slice needs an id")
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        errors.append(f"duplicate slice ids: {', '.join(dupes)}")
    known = set(ids)
    for s in slices:
        for dep in s["deps"]:
            if dep not in known:
                errors.append(f"{s['id']}: unknown dependency {dep}")
            if dep == s["id"]:
                errors.append(f"{s['id']}: depends on itself")
        for k in ("spec", "prewrite", "build", "verify"):
            v = s[k]
            if not isinstance(v, (int, float)) or v < 0:
                errors.append(f"{s['id']}: {k} must be a non-negative number")
        if s.get("gate", "build") not in ("build", "verify"):
            errors.append(f"{s['id']}: gate must be \"build\" or \"verify\"")
        if s["build"] <= 0:
            errors.append(f"{s['id']}: build must be > 0")
        if s["build"] > 8 * max(plan["defaults"]["build"], 1):
            warnings.append(f"{s['id']}: build {s['build']} is very large; split the slice")
    cyc = find_cycle(slices)
    if cyc:
        errors.append("dependency cycle: " + " -> ".join(cyc))
    team = plan["team"]
    if team["pm"] < 1:
        errors.append("team.pm must be >= 1")
    if team["dev"] < 1 and not any(s["pm_ok"] for s in slices):
        errors.append("team.dev is 0 and no slice is pm_ok: nobody can build")
    if team["qa"] < 1:
        warnings.append("team.qa is 0: the PM or orchestrator must verify; never let a builder approve its own slice")
    if team["dev"] > 1:
        all_areas = {a for s in slices for a in s["areas"]}
        if len(all_areas) <= 1:
            warnings.append("all slices share one area: parallel dev lanes will conflict; split areas")
    # contracts
    root = Path(plan_path).resolve().parent
    cdir = root / "contracts"
    if cdir.is_dir():
        for s in slices:
            cp = cdir / f"{s['id']}.md"
            if not cp.exists():  # accept any letter case, e.g. s1.md for S1
                alt = [c for c in cdir.glob("*.md") if c.stem.lower() == s["id"].lower()]
                cp = alt[0] if alt else cp
            if not cp.exists():
                warnings.append(f"{s['id']}: missing contract {cp.relative_to(root)}")
                continue
            text = cp.read_text(encoding="utf-8")
            missing = [h for h in CONTRACT_SECTIONS if h not in text]
            if missing:
                errors.append(f"{s['id']}: contract lacks sections {', '.join(missing)}")
            if "## Depends on" not in text:
                warnings.append(f"{s['id']}: contract has no '## Depends on' section")
            else:
                body = text.split("## Depends on", 1)[1].split("\n## ", 1)[0]
                named = {i for i in known if i and i != s["id"]
                         and re.search(rf"(?<![A-Za-z0-9]){re.escape(i)}(?![A-Za-z0-9])", body, re.I)}
                undeclared = sorted(named - set(s["deps"]))
                if undeclared:
                    warnings.append(f"{s['id']}: contract depends on {', '.join(undeclared)} "
                                    "but plan.json deps do not list them")
    else:
        warnings.append("no contracts/ directory next to the plan yet")
    return errors, warnings


# ----------------------------------------------------------------- scheduling
@dataclass
class Task:
    key: str
    slice_id: str
    kind: str
    dur: float
    preds: list[str] = field(default_factory=list)
    es: float = 0.0
    ef: float = 0.0
    ls: float = 0.0
    lf: float = 0.0
    tail: float = 0.0  # longest path from task start to project end

    @property
    def slack(self) -> float:
        return round(self.ls - self.es, 6)


def build_tasks(plan: dict) -> dict[str, Task]:
    by_id = {s["id"]: s for s in plan["slices"]}

    def gate_of(dep: str) -> str:  # a slice may override the plan-wide gate for its dependents
        g = by_id.get(dep, {}).get("gate", plan["dep_gate"])
        return "VERIFY" if g == "verify" else "BUILD"

    tasks: dict[str, Task] = {}
    for s in plan["slices"]:
        sid = s["id"]
        tasks[f"{sid}:SPEC"] = Task(f"{sid}:SPEC", sid, "SPEC", s["spec"])
        tasks[f"{sid}:PREWRITE"] = Task(f"{sid}:PREWRITE", sid, "PREWRITE", s["prewrite"], [f"{sid}:SPEC"])
        tasks[f"{sid}:BUILD"] = Task(
            f"{sid}:BUILD", sid, "BUILD", s["build"],
            [f"{sid}:SPEC"] + [f"{d}:{gate_of(d)}" for d in s["deps"]],
        )
        tasks[f"{sid}:VERIFY"] = Task(
            f"{sid}:VERIFY", sid, "VERIFY", s["verify"],
            [f"{sid}:BUILD", f"{sid}:PREWRITE"] + [f"{d}:VERIFY" for d in s["deps"]],
        )
    return tasks


def topo(tasks: dict[str, Task]) -> list[str]:
    indeg = {k: 0 for k in tasks}
    succ: dict[str, list[str]] = {k: [] for k in tasks}
    for t in tasks.values():
        for p in t.preds:
            indeg[t.key] += 1
            succ[p].append(t.key)
    order, queue = [], sorted(k for k, v in indeg.items() if v == 0)
    while queue:
        k = queue.pop(0)
        order.append(k)
        for n in succ[k]:
            indeg[n] -= 1
            if indeg[n] == 0:
                queue.append(n)
    return order


def cpm(tasks: dict[str, Task]) -> tuple[float, list[str]]:
    order = topo(tasks)
    succ: dict[str, list[str]] = {k: [] for k in tasks}
    for t in tasks.values():
        for p in t.preds:
            succ[p].append(t.key)
    for k in order:
        t = tasks[k]
        t.es = max((tasks[p].ef for p in t.preds), default=0.0)
        t.ef = t.es + t.dur
    end = max(t.ef for t in tasks.values())
    for k in reversed(order):
        t = tasks[k]
        t.lf = min((tasks[n].ls for n in succ[k]), default=end)
        t.ls = t.lf - t.dur
        t.tail = t.dur + max((tasks[n].tail for n in succ[k]), default=0.0)
    # one critical chain, walked from a zero-slack start
    path: list[str] = []
    cur = min((t for t in tasks.values() if not t.preds and t.slack == 0),
              key=lambda t: t.key, default=None)
    while cur is not None:
        path.append(cur.key)
        nxt = [tasks[n] for n in succ[cur.key] if tasks[n].slack == 0 and abs(tasks[n].es - cur.ef) < 1e-9]
        cur = sorted(nxt, key=lambda t: (-t.tail, t.key))[0] if nxt else None
    return end, path


@dataclass
class Worker:
    name: str
    role: str
    busy_until: float = 0.0
    log: list[tuple[float, float, str]] = field(default_factory=list)


def simulate(plan: dict, team: dict | None = None) -> dict:
    team = dict(team or plan["team"])
    tasks = build_tasks(plan)
    span_cpm, crit = cpm(tasks)
    slices = {s["id"]: s for s in plan["slices"]}
    workers = [Worker(f"pm{i+1}", "pm") for i in range(team["pm"])]
    workers += [Worker(f"dev{i+1}", "dev") for i in range(team["dev"])]
    workers += [Worker(f"qa{i+1}", "qa") for i in range(team["qa"])]
    if team["qa"] == 0:  # PM verifies when there is no QA lane
        for w in workers:
            if w.role == "pm":
                w.role = "pm+qa"
    wip_limit = plan.get("wip_limit")

    done: dict[str, float] = {}
    started: dict[str, tuple[float, str]] = {}
    running: dict[str, float] = {}  # task -> finish time
    t = 0.0
    guard = 0
    while len(done) < len(tasks):
        guard += 1
        if guard > 100000:
            raise RuntimeError("scheduler did not converge")
        for k, fin in list(running.items()):
            if fin <= t + 1e-9:
                done[k] = fin
                del running[k]
        ready = [x for x in tasks.values()
                 if x.key not in done and x.key not in running
                 and all(p in done for p in x.preds)]
        # verification first (fast feedback frees WIP), then longest remaining path
        ready.sort(key=lambda x: (x.kind != "VERIFY", -x.tail, x.key))
        busy_areas = {a for k in running if k.endswith(":BUILD") for a in slices[k.split(":")[0]]["areas"]}
        in_flight = {k.split(":")[0] for k in list(running) + list(done)
                     if k.endswith(":BUILD")} - {k.split(":")[0] for k in done if k.endswith(":VERIFY")}
        for w in sorted(workers, key=lambda w: (w.role != "dev", w.name)):
            if w.busy_until > t + 1e-9:
                continue
            pick = None
            for x in ready:
                role = ROLE_OF[x.kind]
                ok = role == w.role or (w.role == "pm+qa" and role in ("pm", "qa"))
                if not ok and x.kind == "BUILD" and w.role.startswith("pm"):
                    s = slices[x.slice_id]
                    ok = bool(s["pm_ok"]) and x.slack > 0
                if not ok and x.kind == "BUILD" and team["dev"] == 0 and w.role.startswith("pm"):
                    ok = bool(slices[x.slice_id]["pm_ok"])
                if not ok:
                    continue
                if x.kind == "BUILD":
                    if any(a in busy_areas for a in slices[x.slice_id]["areas"]):
                        continue
                    if wip_limit and x.slice_id not in in_flight and len(in_flight) >= wip_limit:
                        continue
                pick = x
                break
            if pick is None:
                continue
            ready.remove(pick)
            fin = t + pick.dur
            running[pick.key] = fin
            started[pick.key] = (t, w.name)
            w.busy_until = fin
            w.log.append((t, fin, pick.key))
            if pick.kind == "BUILD":
                busy_areas.update(slices[pick.slice_id]["areas"])
                in_flight.add(pick.slice_id)
        future = [f for f in running.values() if f > t + 1e-9]
        if not future and len(done) < len(tasks) and not running:
            stuck = [x.key for x in tasks.values() if x.key not in done]
            raise RuntimeError("no worker can run: " + ", ".join(stuck[:6]))
        if future:
            t = min(future)
    makespan = max(done.values())
    report_workers = []
    total_busy = total_cap = 0.0
    for w in workers:
        busy = sum(e - s for s, e, _ in w.log)
        idle_windows, cursor = [], 0.0
        for s, e, _ in sorted(w.log):
            if s - cursor > 1e-9:
                idle_windows.append((cursor, s))
            cursor = max(cursor, e)
        if makespan - cursor > 1e-9:
            idle_windows.append((cursor, makespan))
        total_busy += busy
        total_cap += makespan
        # mid-project gaps only: ignore waiting before the first task and after the last
        inner = [(a, b) for a, b in idle_windows
                 if w.log and a > min(s for s, _, _ in w.log) - 1e-9 and b < max(e for _, e, _ in w.log) + 1e-9]
        inner_idle = sum(b - a for a, b in inner)
        report_workers.append({
            "name": w.name, "role": w.role, "busy": busy,
            "idle_rate": round(1 - busy / makespan, 3) if makespan else 0.0,
            "gap_rate": round(inner_idle / makespan, 3) if makespan else 0.0,
            "log": sorted(w.log), "idle": idle_windows,
        })
    pm_on_crit = [k for k in crit if k.endswith(":BUILD") and started[k][1].startswith("pm")]
    return {
        "team": team, "makespan": makespan, "cpm_lower_bound": span_cpm,
        "critical_path": crit, "workers": report_workers,
        "idle_rate": round(1 - total_busy / total_cap, 3) if total_cap else 0.0,
        "pm_builds_on_critical_path": pm_on_crit, "tasks": tasks, "started": started,
    }


def fmt(x: float) -> str:
    return str(int(x)) if abs(x - round(x)) < 1e-9 else f"{x:.1f}"


def schedule_markdown(plan: dict, r: dict) -> str:
    out = ["# Pipeline schedule", ""]
    team = r["team"]
    out.append(f"Team: {team['pm']} PM, {team['dev']} dev lane(s), {team['qa']} QA lane(s). "
               f"Makespan **{fmt(r['makespan'])}** units "
               f"(dependency lower bound {fmt(r['cpm_lower_bound'])}). "
               f"Overall idle rate **{r['idle_rate']:.0%}**.")
    out += ["", "## Critical path", "", " -> ".join(r["critical_path"]), ""]
    out += ["## Lanes", "", "Idle = all unused time; Gaps = idle between a lane's first and last task "
            "(ramp-up and ramp-down excluded).", "",
            "| Lane | Busy | Idle | Gaps | Work (start-end task) |", "|---|---|---|---|---|"]
    for w in r["workers"]:
        work = "; ".join(f"{fmt(s)}-{fmt(e)} {k}" for s, e, k in w["log"])
        out.append(f"| {w['name']} | {fmt(w['busy'])} | {w['idle_rate']:.0%} | {w['gap_rate']:.0%} | {work} |")
    out += ["", "## Idle windows (fill from the standby backlog)", ""]
    any_idle = False
    for w in r["workers"]:
        if w["idle"]:
            any_idle = True
            spans = ", ".join(f"{fmt(a)}-{fmt(b)}" for a, b in w["idle"])
            out.append(f"- {w['name']}: {spans}")
    if not any_idle:
        out.append("- none")
    out += ["", "## Timeline by unit", ""]
    horizon = int(-(-r["makespan"] // 1))
    header = "| Lane | " + " | ".join(str(i) for i in range(horizon)) + " |"
    out += [header, "|---|" + "---|" * horizon]
    for w in r["workers"]:
        cells = []
        for i in range(horizon):
            label = "."
            for s, e, k in w["log"]:
                if s <= i + 1e-9 and i + 1e-9 < e:
                    sid, kind = k.split(":")
                    label = f"{sid}{kind[0]}"
            cells.append(label)
        out.append(f"| {w['name']} | " + " | ".join(cells) + " |")
    out += ["", "Legend: S=spec, P=prewrite tests, B=build, V=verify, .=idle", ""]
    warns = warnings_for(plan, r)
    out += ["## Warnings", ""] + ([f"- {x}" for x in warns] or ["- none"])
    return "\n".join(out) + "\n"


def warnings_for(plan: dict, r: dict) -> list[str]:
    warns = []
    th = plan["idle_threshold"]
    for w in r["workers"]:
        if w["gap_rate"] > th:
            warns.append(f"{w['name']} has mid-project gaps of {w['gap_rate']:.0%} (> {th:.0%}): "
                         "split slices finer, reorder, or fill them from the standby backlog")
        elif w["idle_rate"] > 0.5:
            warns.append(f"{w['name']} idles {w['idle_rate']:.0%} overall (mostly ramp-up/down): "
                         "consider dropping the lane or giving it standby work")
    if r["pm_builds_on_critical_path"]:
        warns.append("PM builds on the critical path: " + ", ".join(r["pm_builds_on_critical_path"]))
    if r["makespan"] > 1.5 * r["cpm_lower_bound"]:
        warns.append("makespan is >1.5x the dependency bound: the team is the bottleneck; "
                     "run `size` to compare shapes")
    return warns


# ----------------------------------------------------------------- integrity
def source_files(root: Path) -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, check=True,
        ).stdout.decode("utf-8", "replace")
        files = [root / p for p in out.split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
        files = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip]
            files += [Path(dirpath) / f for f in filenames]
    keep = []
    for f in files:
        rel = f.relative_to(root)
        if rel.parts and rel.parts[0] == HARNESS_DIR:
            continue
        if any(part in JUNK_DIRS for part in rel.parts) or f.suffix in JUNK_SUFFIXES:
            continue  # interpreter/tool caches are not source
        if f.is_file() and not f.is_symlink():
            keep.append(f)
    return sorted(keep)


def hash_tree(root: Path) -> dict[str, str]:
    result = {}
    for f in source_files(root):
        h = hashlib.sha256()
        with f.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        result[f.relative_to(root).as_posix()] = h.hexdigest()
    return result


def snapshot_path(root: Path, label: str) -> Path:
    return root / HARNESS_DIR / "state" / f"snapshot-{label}.json"


# ----------------------------------------------------------------- test guard
def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def tree_files(repo: Path, ref: str, root: str) -> dict[str, str]:
    """path -> blob id for files under root at ref (cache files skipped)."""
    out = {}
    try:
        listing = git(repo, "ls-tree", "-r", ref, "--", root)
    except subprocess.CalledProcessError:
        return out
    for line in listing.splitlines():
        meta, path = line.split("\t", 1)
        parts = Path(path).parts
        if any(p in JUNK_DIRS for p in parts) or Path(path).suffix in JUNK_SUFFIXES:
            continue
        out[path] = meta.split()[2]
    return out


def _is_merged(repo: Path, ancestor: str, branch: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", ancestor, branch],
        capture_output=True,
    ).returncode == 0


def _blob_history(repo: Path, branches: set[str], path: str) -> dict[str, set[str]]:
    """Return {branch: set_of_blob_ids} for `path` across `branches`."""
    res: dict[str, set[str]] = {}
    for tb in sorted(branches):
        blobs: set[str] = set()
        try:
            out = git(repo, "log", "--format=", "--raw", "--no-renames", tb, "--", path)
        except subprocess.CalledProcessError:
            res[tb] = blobs
            continue
        for line in out.splitlines():
            if not line.startswith(":"):
                continue
            parts = line.split()
            if len(parts) >= 4:
                blobs.add(parts[3])
        res[tb] = blobs
    return res


def testguard(repo: Path, branch: str, tests_root: str, prefix: str = "harness/") -> int:
    """Every QA-owned slice test dir on `branch` must match that slice's tests branch."""
    root = tests_root.rstrip("/")
    files = tree_files(repo, branch, root)
    branches = set(git(repo, "branch", "--list", "--format=%(refname:short)", f"{prefix}*-tests").split())
    by_slice: dict[str, list[str]] = {}
    for path in files:
        rel = Path(path).relative_to(root).parts
        if len(rel) >= 2:
            by_slice.setdefault(rel[0], []).append(path)
    bad = stale = other = 0
    for sdir, paths in sorted(by_slice.items()):
        ref = next((b for b in branches if b.lower() == f"{prefix}{sdir}-tests".lower()), None)
        if ref is None:
            print(f"UNOWNED  {root}/{sdir}/ has no {prefix}{sdir}-tests branch (cannot verify)")
            continue
        ref_files = tree_files(repo, ref, f"{root}/{sdir}")
        ref_merged = _is_merged(repo, ref, branch)
        for path in sorted(set(paths) | set(ref_files)):
            mine, theirs = files.get(path), ref_files.get(path)
            if mine == theirs:
                continue
            if mine is None:
                if ref_merged:
                    print(f"DELETED  {path} (present on merged {ref}, removed on {branch})")
                    bad += 1
                else:
                    print(f"MISSING  {path} (on {ref}, not on {branch}: merge {ref})")
                    stale += 1
                continue
            hist_map = _blob_history(repo, branches, path)
            history = {b for bs in hist_map.values() for b in bs}
            own = hist_map.get(ref, set())
            if mine in own:
                print(f"STALE    {path} (older version of {ref}: merge it again)")
                stale += 1
            elif mine in history:
                print(f"OTHERQA  {path} (QA-authored on another tests branch, e.g. a later slice's contract change)")
                other += 1
            else:
                print(f"MODIFIED {path} (differs from every version on any tests branch)")
                bad += 1
    if bad:
        print(f"VIOLATION: {bad} QA-owned test file(s) edited or deleted on {branch}")
        return 3
    notes = []
    if stale:
        notes.append(f"{stale} stale/missing: re-merge tests branches")
    if other:
        notes.append(f"{other} updated by another slice's QA")
    print("OK" + (f" ({'; '.join(notes)})" if notes else ""))
    return 0


# ----------------------------------------------------------------- board
def board_path(plan_path: str) -> Path:
    return Path(plan_path).resolve().parent / "state" / "board.json"


def load_board(plan: dict, plan_path: str) -> dict:
    p = board_path(plan_path)
    board = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    for s in plan["slices"]:
        board.setdefault(s["id"], "planned")
    return board


# ----------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("validate"); p.add_argument("plan")
    p = sub.add_parser("schedule"); p.add_argument("plan"); p.add_argument("--md"); p.add_argument("--json", action="store_true")
    p.add_argument("--remaining", action="store_true", help="drop slices the board shows as merged (re-plan mid-project)")
    p = sub.add_parser("size"); p.add_argument("plan")
    p.add_argument("--remaining", action="store_true", help="drop slices the board shows as merged")
    p.add_argument("--max-dev", type=int, default=4); p.add_argument("--max-qa", type=int, default=3)
    p = sub.add_parser("snapshot"); p.add_argument("label"); p.add_argument("--root", default=".")
    p = sub.add_parser("verify"); p.add_argument("label"); p.add_argument("--root", default=".")
    p.add_argument("--allow", action="append", default=[], help="glob of paths this role may change, e.g. tests/acceptance/*")
    p = sub.add_parser("board"); p.add_argument("plan"); p.add_argument("--set", nargs="*", default=[])
    p = sub.add_parser("testguard"); p.add_argument("branch"); p.add_argument("--tests-root", default="tests/acceptance")
    p.add_argument("--repo", default=".")
    p = sub.add_parser("brief"); p.add_argument("plan"); p.add_argument("slice_id")
    p.add_argument("--role", choices=("dev", "qa-pre", "qa-verify", "pm"), default="dev")
    a = ap.parse_args(argv)

    def remaining(plan: dict) -> dict:
        if not getattr(a, "remaining", False):
            return plan
        board = load_board(plan, a.plan)
        merged = {k for k, v in board.items() if v == "merged"}
        plan["slices"] = [s for s in plan["slices"] if s["id"] not in merged]
        for s in plan["slices"]:
            s["deps"] = [d for d in s["deps"] if d not in merged]
        return plan

    if a.cmd == "validate":
        plan = load_plan(a.plan)
        errors, warnings = validate(plan, a.plan)
        for e in errors:
            print(f"ERROR   {e}")
        for w in warnings:
            print(f"WARNING {w}")
        print("OK" if not errors else f"{len(errors)} error(s)")
        return 1 if errors else 0

    if a.cmd == "schedule":
        plan = load_plan(a.plan)
        errors, _ = validate(plan, a.plan)
        if errors:
            print("plan is invalid; run validate", file=sys.stderr)
            return 1
        r = simulate(remaining(plan))
        if a.json:
            slim = {k: v for k, v in r.items() if k not in ("tasks", "started")}
            slim["warnings"] = warnings_for(plan, r)
            print(json.dumps(slim, indent=2))
        else:
            md = schedule_markdown(plan, r)
            if a.md:
                Path(a.md).parent.mkdir(parents=True, exist_ok=True)
                Path(a.md).write_text(md, encoding="utf-8")
            print(md)
            if a.md:
                print(f"wrote {a.md}")
        return 0

    if a.cmd == "size":
        plan = load_plan(a.plan)
        errors, _ = validate(plan, a.plan)
        if errors:
            print("plan is invalid; run validate", file=sys.stderr)
            return 1
        plan = remaining(plan)
        rows = []
        for dev in range(1, a.max_dev + 1):
            for qa in range(1, a.max_qa + 1):
                team = {"pm": plan["team"]["pm"], "dev": dev, "qa": qa}
                r = simulate(plan, team)
                people = team["pm"] + dev + qa
                gaps = max((w["gap_rate"] for w in r["workers"]), default=0.0)
                rows.append((r["makespan"], people, dev, qa, r["idle_rate"], r["makespan"] * people, gaps))
        best = min(r[0] for r in rows)
        print("| dev | qa | people | makespan | idle | worst lane gaps | person-units |")
        print("|---|---|---|---|---|---|---|")
        for ms, people, dev, qa, idle, cost, gaps in sorted(rows, key=lambda x: (x[0], x[1])):
            print(f"| {dev} | {qa} | {people} | {fmt(ms)} | {idle:.0%} | {gaps:.0%} | {fmt(cost)} |")
        th = plan["idle_threshold"]
        fast = [r for r in rows if r[0] <= best * 1.1]
        cands = [r for r in fast if r[6] <= th]
        pick = min(cands or fast, key=lambda r: (r[1], r[6], r[0]))
        print(f"\nRecommended: {pick[2]} dev + {pick[3]} qa (+{plan['team']['pm']} pm): makespan "
              f"{fmt(pick[0])} vs best {fmt(best)}, idle {pick[4]:.0%}, worst lane gaps {pick[6]:.0%}"
              + ("" if cands else f"  [every fast shape has a lane with gaps > {th:.0%}: re-slice or plan standby work]"))
        return 0

    if a.cmd == "snapshot":
        root = Path(a.root).resolve()
        snap = hash_tree(root)
        out = snapshot_path(root, a.label)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(snap, indent=1, sort_keys=True), encoding="utf-8")
        print(f"snapshot {a.label}: {len(snap)} files -> {out.relative_to(root)}")
        return 0

    if a.cmd == "verify":
        root = Path(a.root).resolve()
        path = snapshot_path(root, a.label)
        if not path.exists():
            print(f"no snapshot named {a.label}", file=sys.stderr)
            return 2
        before = json.loads(path.read_text(encoding="utf-8"))
        now = hash_tree(root)
        added = sorted(set(now) - set(before))
        removed = sorted(set(before) - set(now))
        changed = sorted(k for k in set(now) & set(before) if now[k] != before[k])
        allowed = [i for i in added + removed + changed if any(fnmatch.fnmatch(i, g) for g in a.allow)]
        added, removed, changed = ([i for i in x if i not in allowed] for x in (added, removed, changed))
        for i in allowed:
            print(f"ALLOWED  {i}")
        if not (added or removed or changed):
            print(f"UNCHANGED since {a.label}")
            return 0
        for tag, items in (("ADDED", added), ("REMOVED", removed), ("CHANGED", changed)):
            for i in items:
                print(f"{tag:8} {i}")
        print(f"VIOLATION: source changed since {a.label}")
        return 3

    if a.cmd == "testguard":
        return testguard(Path(a.repo).resolve(), a.branch, a.tests_root)

    if a.cmd == "board":
        plan = load_plan(a.plan)
        board = load_board(plan, a.plan)
        for item in a.set:
            sid, _, stage = item.partition("=")
            if sid not in board:
                print(f"unknown slice {sid}", file=sys.stderr)
                return 1
            if stage not in STAGES:
                print(f"unknown stage {stage}; use one of {', '.join(STAGES)}", file=sys.stderr)
                return 1
            board[sid] = stage
        if a.set:
            p = board_path(a.plan)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(board, indent=1), encoding="utf-8")
        titles = {s["id"]: s.get("title", "") for s in plan["slices"]}
        for stage in STAGES:
            ids = [k for k, v in board.items() if v == stage]
            if ids:
                print(f"{stage:9} " + ", ".join(f"{i} {titles.get(i, '')}".strip() for i in ids))
        wip = sum(1 for v in board.values() if v in ("building", "built"))
        lim = plan.get("wip_limit")
        print(f"WIP (building+built): {wip}" + (f" / limit {lim}" + ("  OVER LIMIT" if wip > lim else "") if lim else ""))
        # what is unblocked for building
        ok_stages = {"build": ("built", "verified", "merged"), "verify": ("verified", "merged")}
        by_id = {s["id"]: s for s in plan["slices"]}
        ready = [s["id"] for s in plan["slices"]
                 if board[s["id"]] == "specced"
                 and all(board.get(d) in ok_stages[by_id.get(d, {}).get("gate", plan["dep_gate"])] for d in s["deps"])]
        busy = {a for k, v in board.items() if v == "building" and k in by_id for a in by_id[k]["areas"]}
        blocked_by_area = [i for i in ready if any(a in busy for a in by_id[i]["areas"])]
        ready = [i for i in ready if i not in blocked_by_area]
        if lim and wip >= lim:
            blocked_by_area += [f"(WIP limit) {i}" for i in ready]
            ready = []
        need_spec = [s["id"] for s in plan["slices"] if board[s["id"]] == "planned"]
        need_verify = [k for k, v in board.items() if v == "built"]
        print("ready to build: " + (", ".join(ready) or "-"))
        if blocked_by_area:
            print("waiting:        " + ", ".join(blocked_by_area) + "  (area busy or WIP full)")
        print("needs spec:     " + (", ".join(need_spec) or "-"))
        print("needs verify:   " + (", ".join(need_verify) or "-"))
        return 0

    if a.cmd == "brief":
        plan = load_plan(a.plan)
        by_id = {s["id"]: s for s in plan["slices"]}
        if a.slice_id not in by_id:
            print(f"unknown slice {a.slice_id}", file=sys.stderr)
            return 1
        hdir = Path(a.plan).resolve().parent
        sid = a.slice_id
        sdir = sid.lower()
        wt = hdir / "wt" / sid
        if a.role == "dev":
            print(f"Role: harness-developer. Work ONLY in {wt} on branch harness/{sid}.\n"
                  f"Contract: {hdir / 'contracts' / f'{sid}.md'} (read fully).\n"
                  f"Handoff: {hdir / 'handoff.md'} (preserve verified behaviors; check decisions).\n"
                  f"Pre-written acceptance tests: tests/acceptance/{sdir}/ (if present; never edit).\n"
                  f"Run tests from {wt} with PYTHONDONTWRITEBYTECODE=1 and commit to harness/{sid}.\n"
                  f"Reply with: summary, files changed, test command + result, contract issues.")
        elif a.role == "qa-pre":
            print(f"Role: harness-qa. Pre-write executable acceptance tests for {sid} from {hdir / 'contracts' / f'{sid}.md'}.\n"
                  f"Work ONLY in {hdir / 'wt' / f'qat-{sid}'} on branch harness/{sid}-tests.\n"
                  f"Write tests under tests/acceptance/{sdir}/, run with PYTHONDONTWRITEBYTECODE=1, commit to harness/{sid}-tests.\n"
                  f"Reply with: test files written and how to run them.")
        elif a.role == "qa-verify":
            print(f"Role: harness-qa. Verify slice {sid} in {wt} (branch harness/{sid}, read-only).\n"
                  f"Contract: {hdir / 'contracts' / f'{sid}.md'}. Handoff: {hdir / 'handoff.md'}.\n"
                  f"Run acceptance tests in tests/acceptance/{sdir}/ and full suite from {wt} with PYTHONDONTWRITEBYTECODE=1.\n"
                  f"Write qa_report.md and qa_report.json in {hdir / 'evidence' / sid}.\n"
                  f"Reply with: status and report paths.")
        else:
            print(f"Role: harness-planner. Read {hdir / 'brief.md'}, {hdir / 'handoff.md'}, {hdir / 'plan.json'}.\n"
                  f"Write/refresh contracts in {hdir / 'contracts'} (focus: {sid}). Do not edit source.\n"
                  f"Reply with: files written, decisions, open questions.")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
````
