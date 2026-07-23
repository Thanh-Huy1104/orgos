# minivalid — runtime schema validation library (TypeScript)

Version: 1.0.0
Author: orgos
Status: ready-to-build

## Overview

A small, zero-runtime-dependency schema validation library for
TypeScript — the shape of zod/valibot, scoped down. Users declare
schemas (`v.object({ name: v.string() })`), call `schema.parse(input)`,
and get either a typed value or a structured list of issues with paths.

Stack: **TypeScript 5 (strict mode), Node 22, ESM**. The ONLY
dependency is `typescript` as a devDependency. Tests use Node's
built-in test runner (`node:test` + `node:assert/strict`) — no jest,
no vitest. Everything is deterministic pure logic; tests pin exact
expected outputs.

## Toolchain contract (read carefully — this is not Python)

- `npm install` installs the toolchain (just `typescript`).
- `npm test` must run `tsc -p .` then `node --test dist/tests/`.
- `tsconfig.json`: `"module": "nodenext"`, `"moduleResolution": "nodenext"`,
  `"strict": true`, `"outDir": "dist"`, include `src/` and `tests/`.
- **ESM gotcha**: with nodenext, relative imports in .ts source MUST be
  written with a `.js` extension (`import { ok } from "../src/core.js"`),
  because that is the path in the compiled output. Missing `.js`
  extensions will compile-error.
- Test files are named `*.test.ts` under `tests/`, compiled to
  `dist/tests/*.test.js`, discovered by `node --test dist/tests/`.
- There is no pytest here. Do not create pyproject.toml, requirements.txt,
  conftest.py, or any Python file. Verification is `npm test`.

## Architecture

Disjoint modules under `src/`; inter-module calls go through the types
in `core.ts` so agents can work in parallel without collision.

```
src/
    core.ts        — Result types: Ok/Err, Issue {path, code, message}, Schema interface
    primitives.ts  — string(), number(), boolean() with constraint options
    composites.ts  — object(), array() with nested path reporting
    combinators.ts — optional(), nullable(), union(), literal(), withDefault()
    refine.ts      — refine() custom predicates + transform() mapping
    format.ts      — flatten() and prettyPrint() for issue lists
    index.ts       — public API surface (the `v` namespace re-exports)
tests/             — *.test.ts mirroring src modules
```

Data flow: `schema.parse(input)` → walks the value → collects
`Issue[]` with JSON-path-style paths (`["user", "emails", 0]`) →
returns `{ ok: true, value }` or `{ ok: false, issues }`. `parse`
never throws; a separate `parseOrThrow` wraps it.

## Definition of done

- `npm install && npm test` passes from a fresh clone
- ≥ 60 tests passing under `node --test`
- `tsc -p .` compiles with zero errors under `"strict": true`
- Zero runtime dependencies (`dependencies` in package.json is empty/absent)
- README.md shows a working usage example that compiles

---

## Story: Set up TypeScript scaffolding + baseline test harness
Files: package.json, tsconfig.json, .gitignore, src/index.ts, tests/smoke.test.ts, README.md
Type: architecture
Priority: 100
AC:
  - `npm install` succeeds (only devDependency: typescript ^5)
  - `npm test` runs `tsc -p .` then `node --test dist/tests/` and passes
  - tsconfig has strict:true, module nodenext, outDir dist, includes src/ and tests/
  - tests/smoke.test.ts contains one passing test importing from ../src/index.js
  - .gitignore covers node_modules/ and dist/
  - README.md has a one-paragraph description + install + test commands

## Story: Core result types — Ok/Err, Issue, Schema interface
Files: src/core.ts
Type: architecture
Priority: 95
Component: core
Depends: 1
AC:
  - `Issue` = { path: (string|number)[], code: string, message: string }
  - `ParseResult<T>` = { ok: true, value: T } | { ok: false, issues: Issue[] }
  - `Schema<T>` interface: parse(input: unknown) => ParseResult<T>
  - Helpers `ok(value)` and `err(issues)` construct results
  - `parseOrThrow(schema, input)` returns T or throws ValidationError carrying issues
  - No runtime dependencies; compiles under strict

## Story: Add tests for core result types
Files: tests/core.test.ts
Type: test
Priority: 94
Depends: 2
AC:
  - 8+ tests: ok() shape, err() shape, parseOrThrow success, parseOrThrow throws ValidationError with issues attached
  - Test that Issue paths and codes survive a round-trip through parseOrThrow
  - All imports use ../src/core.js extension style

## Story: Primitive schemas — string, number, boolean with constraints
Files: src/primitives.ts
Type: feature
Priority: 90
Component: primitives
Depends: 2
AC:
  - `string({ min?, max?, pattern? })` — length bounds + RegExp; wrong type → code "invalid_type"
  - `number({ min?, max?, int? })` — bounds, integer check; NaN is rejected
  - `boolean()` — strict (no coercion of "true"/1)
  - Constraint violations use distinct codes ("too_small", "too_big", "pattern", "not_integer")
  - Each issue message is human-readable and includes the offending constraint

## Story: Add tests for primitive schemas
Files: tests/primitives.test.ts
Type: test
Priority: 89
Depends: 4
AC:
  - 15+ tests covering happy path + every constraint + every failure code
  - Pin exact issue codes ("invalid_type", "too_small", "too_big", "pattern", "not_integer")
  - Test NaN rejection and that boolean() rejects "true" (string) and 1 (number)

## Story: Composite schemas — object and array with nested paths
Files: src/composites.ts
Type: architecture
Priority: 85
Component: composites
Depends: 4
AC:
  - `object({ key: Schema })` validates each property; unknown keys are stripped (not errors)
  - `array(Schema)` validates each element
  - Nested failures report full paths: ["user","emails",0] style
  - Multiple failures accumulate — parse returns ALL issues, not just the first
  - Non-object/non-array inputs → single "invalid_type" issue at the parent path

## Story: Add tests for composite schemas
Files: tests/composites.test.ts
Type: test
Priority: 84
Depends: 6
AC:
  - 12+ tests: flat object, nested object 3 deep, array of objects, path exactness
  - Test that TWO simultaneous failures both appear in issues with correct paths
  - Test unknown-key stripping and invalid_type at the container level

## Story: Combinators — optional, nullable, union, literal, withDefault
Files: src/combinators.ts
Type: feature
Priority: 80
Component: combinators
Depends: 6
AC:
  - `optional(s)` accepts undefined; `nullable(s)` accepts null
  - `literal(x)` matches exact primitive value via ===
  - `union([a, b, ...])` tries each; failure aggregates the branch issues under code "no_match"
  - `withDefault(s, d)` substitutes d when input is undefined
  - Combinators compose: optional(union([literal("a"), literal("b")])) works

## Story: Add tests for combinators
Files: tests/combinators.test.ts
Type: test
Priority: 79
Depends: 8
AC:
  - 12+ tests: each combinator alone + at least 3 composition cases
  - Test union failure carries "no_match" and branch issue details
  - Test withDefault only fires on undefined, not on null or wrong types

## Story: Refinements and transforms
Files: src/refine.ts
Type: feature
Priority: 75
Component: refine
Depends: 8
AC:
  - `refine(s, predicate, { code, message })` — post-parse predicate; false → issue with given code
  - `transform(s, fn)` — maps the parsed value; fn errors become issue code "transform_failed"
  - Refinements chain: refine(refine(s, p1), p2) runs both
  - Transform output feeds subsequent refinements in a chain

## Story: Add tests for refinements and transforms
Files: tests/refine.test.ts
Type: test
Priority: 74
Depends: 10
AC:
  - 10+ tests: passing/failing refine, custom codes, transform value mapping, throwing transform → "transform_failed", chained refine+transform ordering

## Story: Issue formatting — flatten and prettyPrint
Files: src/format.ts
Type: feature
Priority: 70
Component: format
Depends: 6
AC:
  - `flatten(issues)` → Record<string, string[]> keyed by dotted path ("user.emails.0")
  - Root-level issues key under "" (empty string)
  - `prettyPrint(issues)` → one line per issue: "user.emails.0: message (code)"
  - Deterministic ordering (input order preserved)

## Story: Add tests for issue formatting
Files: tests/format.test.ts
Type: test
Priority: 69
Depends: 12
AC:
  - 8+ tests pinning exact flatten keys and prettyPrint lines for nested failures
  - Root-path issue lands under "" key; numeric path segments render as "0" not "[0]"

## Story: Public API surface + typed inference + README usage
Files: src/index.ts, README.md
Type: feature
Priority: 65
Depends: 8
AC:
  - src/index.ts exports a `v` namespace object: v.string, v.number, v.boolean, v.object, v.array, v.optional, v.nullable, v.union, v.literal, v.withDefault, v.refine, v.transform, plus parse helpers and format helpers
  - `Infer<S>` type extracts the TypeScript type from a Schema (Infer<typeof userSchema>)
  - README usage example: declare a user schema, parse good + bad input, show flatten() output — and the example code actually compiles (mirror it in tests/smoke.test.ts or a dedicated test)
  - `npm test` green across the whole suite at this point
