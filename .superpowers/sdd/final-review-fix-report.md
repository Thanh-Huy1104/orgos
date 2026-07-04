# Pre-merge review fix report — agile-pivot branch

Base commit: 41b9354

## Fix 1 — config/org.yaml: wrap under `org:` key

**Problem:** `departments.py::load_org` does `data["org"]` (hard lookup), but the file was flat.
The `owner` block was also incompatible with `OwnerProfile` (dict where str expected, wrong
ApprovalRule schema), so it was dropped; the model's defaults apply.

```diff
-name: orgos
-description: A self-organizing agile engineering team...
+org:
+  name: orgos
+  description: A self-organizing agile engineering team...
 departments:
   ...
 handoffs: []
```

Verify: `python -c "from orgos.departments import load_org; print(load_org('config/org.yaml').name)"` → `orgos`

## Fix 2 — orgos/api.py: resolve ORG_YAML at call time, not module import

**Problem:** `ORG_YAML = os.environ.get(...)` at module scope meant `monkeypatch.setenv` in tests
had no effect. Also 7 call sites in route handlers referred to the bare name after it was removed.

**Fix:** Added `_org_yaml_path() -> str` helper that reads the env var fresh on each call;
replaced all `ORG_YAML` / `Path(ORG_YAML)` occurrences with `_org_yaml_path()` /
`Path(_org_yaml_path())`.

```diff
-ORG_YAML = os.environ.get("ORGOS_ORG_YAML", "./config/org.yaml")
+def _org_yaml_path() -> str:
+    return os.environ.get("ORGOS_ORG_YAML", "./config/org.yaml")
 
 def load_org():
-    data = yaml.safe_load(Path(ORG_YAML).read_text())
+    data = yaml.safe_load(Path(_org_yaml_path()).read_text())
```

## Fix 3 — orgos/agile/replay.py: remove duplicate create_sprint in live path

**Problem:** `replay_sprint` called `pm.create_sprint(...)` unconditionally after `run_sprint()`
which already created the row. Also used a different db path (`base/_orgos_memory/pm.db`)
vs `run_sprint`'s default path.

**Fix:** In the non-offline (`else`) branch: use `PMStore()` (default path), only call
`record_sprint_envelope`, return immediately. The offline (`_offline=True`) branch is unchanged
and still calls `create_sprint` because `run_sprint` is skipped there.

```diff
     else:
         replayed = run_sprint(base, mutated["picked_issue"], model=model, mock_pr=True)
-    pm = PMStore(base / "_orgos_memory" / "pm.db")
-    pm.create_sprint(replayed.id, replayed.branch, ...)
-    pm.record_sprint_envelope(...)
+        pm = PMStore()  # default path matches run_sprint
+        pm.record_sprint_envelope(...)
+        replayed.envelopes["_replay"] = None
+        return replayed
+
+    # offline branch below (unchanged) ...
```

## Fix 4 — orgos/tools/research_sources.py: correct User-Agent

```diff
-_UA = {"User-Agent": "orgos-quant-desk/1.0 (research; contact@orgos.local)"}
+_UA = {"User-Agent": "orgos-agile/1.0 (contact@orgos.local)"}
```

## Fix 5 — orgos/pm.py + orgos/agile/sprint.py: topology cadence off-by-limit

**Problem:** `list_sprints(limit=6)` caps results at 6, so `len(...) % 5 == 0` only triggers
at sprint #5 and never again.

**Fix:** Added `count_sprints()` method to `PMStore`; used it from `run_nightly_sprint`.

```diff
+    def count_sprints(self) -> int:
+        row = self.conn.execute("SELECT COUNT(*) FROM sprints").fetchone()
+        return int(row[0]) if row else 0

-    all_sprints = _pm.list_sprints(limit=6)
-    if len(all_sprints) % 5 == 0:
+    if _pm.count_sprints() % 5 == 0:
```

## Test output (last run)

```
113 passed, 2 skipped, 1 deselected in 1.71s
```

Pre-existing skips/deselects: 2 skipped (network-only), 1 deselected (-m "not network").
No new failures. `test_dora_wiring.py` (13 tests) and `test_replay.py` (2 tests) both fully green.

## Commit SHA

See git log for commit after this report was staged.
