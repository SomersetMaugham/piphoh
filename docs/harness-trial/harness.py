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
        s.setdefault("area", s["id"] if "id" in s else "")
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
        areas = [s["area"] for s in slices]
        if len(set(areas)) == 1:
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
            f"{sid}:VERIFY", sid, "VERIFY", s["verify"], [f"{sid}:BUILD", f"{sid}:PREWRITE"]
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
        busy_areas = {slices[k.split(":")[0]]["area"] for k in running if k.endswith(":BUILD")}
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
                    if slices[x.slice_id]["area"] in busy_areas:
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
                busy_areas.add(slices[pick.slice_id]["area"])
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
        for path in sorted(set(paths) | set(ref_files)):
            mine, theirs = files.get(path), ref_files.get(path)
            if mine == theirs:
                continue
            if mine is None:
                print(f"MISSING  {path} (on {ref}, not on {branch}: merge {ref})")
                stale += 1
                continue
            history = set()  # every version QA ever committed on any tests branch counts as QA-authored
            for tb in sorted(branches):
                for c in git(repo, "rev-list", tb, "--", path).split():
                    try:
                        history.add(git(repo, "rev-parse", f"{c}:{path}").strip())
                    except subprocess.CalledProcessError:
                        pass
            own = set()
            for c in git(repo, "rev-list", ref, "--", path).split():
                try:
                    own.add(git(repo, "rev-parse", f"{c}:{path}").strip())
                except subprocess.CalledProcessError:
                    pass
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
        print(f"VIOLATION: {bad} QA-owned test file(s) edited on {branch}")
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
        busy = {by_id[k]["area"] for k, v in board.items() if v == "building" and k in by_id}
        blocked_by_area = [i for i in ready if by_id[i]["area"] in busy]
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
