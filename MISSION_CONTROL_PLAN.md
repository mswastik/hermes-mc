# Mission Control — Upgrade Plan

_Status: PROPOSAL (awaiting approval before any code)._
_Date: 2026-07-17. Repo: `~/Downloads/repos/hermes-mc/`._

## Context & current state (verified)
- `mission-control-standalone.html` (9120) proxies to the standard dashboard API on 9119.
  Auth: it scrapes the dashboard's `window.__HERMES_SESSION_TOKEN__` from the 9119 root
  HTML and injects it into the page; the 9120 server forwards `X-Hermes-Session-Token`
  to 9119 server-side. No CORS, no dashboard relaunch, no interference.
- **Read endpoints confirmed 200** (with token): `/api/status`, `/api/sessions/stats`,
  `/api/analytics/usage?days=N`, `/api/cron/jobs`, `/api/skills`, `/api/tools/toolsets`,
  `/api/config`, `/api/logs`.
- **Write route confirmed present**: `PUT /api/config` (returns 422 on empty body = it
  validates input). `POST` → 405, so `PUT` is the verb. Full read/write is supported
  by the API — no hand-editing of `config.yaml` required.
- **Config schema captured** to `/tmp/hermes_config_schema.json` (84 top-level keys, each
  with typed sub-keys: `model`, `providers`, `agent`, `terminal`, `web`, `dashboard`,
  `security`, `memory`, `cron`, `tools`, `tts`, `voice`, `streaming`, `gateway`,
  `logging`, `mcp_servers`, `platforms`, `plugins`, `delegation`, `moa`, etc.).
- **9119 theming: OUT OF SCOPE** (it's a compiled SPA bundle; re-skinning = fork +
  rebuild). The 9120 page is fully ours to theme.

## Design decisions (confirmed with user)
- **Navigation = task-oriented tabs (1A)**, NOT a mirror of `config.yaml` nesting.
  Group related keys across the YAML so "change any config" is intuitive.
- **Config editing UX (2B)** = type-aware controls now (text / number / toggle /
  textarea), with **dropdown/select only for keys whose enum we already know** (pulled
  from `config.yaml` schema/categories). Unknown enums fall back to free text. No
  guessing of allowed-values we don't have.
- **Staged**: Stage 1 = richer READ-ONLY layout (all config info visible, no writes).
  Stage 2 = wire `PUT /api/config` for edits.

---

## STAGE 1 — Richer read-only layout (no writes)

### Layout shell (replaces current single-list-per-view)
- **Left rail (fixed, ~220px)**: app brand + nav. Items (task-oriented):
  - Overview (the current tiles/status)
  - Models & Providers
  - Connections / Platforms
  - Scheduling & Cron
  - Security & Privacy
  - Memory & Context
  - Tools & MCP
  - Skills
  - Sessions
  - Logs
  - Config (full tree, read-only)
- **Main pane**: selected section, **two-pane master/detail** where a list exists
  (sessions, jobs, skills, toolsets). Density: stat tiles + tables with sort +
  inline secondary metadata (status pills, `timeAgo` timestamps, sub-resource counts).
- **Top bar**: refresh, last-updated, gateway health pill (from `/api/status`).

### Per-section content (grounded in real endpoint shapes)
- **Overview**: gateway health (running/state/busy/drainable), version + update-available,
  active agents/sessions, connected platforms count — as a stat-tile grid + a compact
  platform list (from `/api/status`).
- **Models & Providers**: `model` (default), `providers` map, `fallback_providers`,
  `delegation` (model/provider/base_url), `moa` presets, `custom_providers`.
  Show default model prominently + provider chips.
- **Connections / Platforms**: `gateway.platforms` connection state, `platforms`
  (matrix/telegram/whatsapp), `mcp_servers` (trilium-notes, hermes-studio-*),
  `platform_toolsets`. Table: platform | state | connected?
- **Scheduling & Cron**: `/api/cron/jobs` list (name, schedule_display, enabled,
  state, paused_reason) + click → detail (prompt, skills, model, provider snapshot).
  Group active vs paused.
- **Security & Privacy**: `security` (allow_private_urls, redact_secrets,
  tirith_enabled, website_blocklist), `privacy.redact_pii`, `approvals.mode`,
  `command_allowlist`, `network.force_ipv4`, `dashboard.basic_auth/oauth`.
- **Memory & Context**: `memory` (enabled, user_profile_enabled, write_approval,
  char limits), `context.engine`, `context_file_max_chars`, `file_read_max_chars`,
  `compression`, `checkpoints`.
- **Tools & MCP**: `/api/tools/toolsets` (label, platform, enabled, available,
  configured, tool count) + `tools`, `tool_output` limits, `code_execution`.
- **Skills**: `/api/skills` (name, category, enabled, usage, provenance) filterable by category.
- **Sessions**: `/api/sessions/stats` (total, active_store, archived, messages,
  by_source) + recent session list (need `/api/sessions?limit=...` — confirm route).
- **Logs**: `/api/logs` with file/level filters (level select: ALL/INFO/WARNING/ERROR).
- **Config (full tree, read-only)**: recursive expandable tree of the 84-key config,
  showing key | type | value. Search box to jump to a key. This is the "see
  everything" view; Stage 2 makes it editable.

### Reusable UI primitives to add (in the HTML)
- `StatGrid`, `Table` (sortable), `Pill`/`Badge` (status colors), `EmptyState`,
  `Section`, `Field` (label + value renderer by type), `Tree` (recursive config).
- Hook helper `useAsync` already exists; add `useAsyncMemo` / `sortState` as needed.
- Keep the error boundary + `Cache-Control: no-store`.

### Stage 1 deliverable
All sections render real data, denser + more informative, read-only. No `PUT`.

---

## STAGE 2 — Read/Write config editing (2B controls)

### Editing model
- A dedicated **Config editor** view (or edit-mode toggle on the Config tree) that
  renders each leaf as a **type-aware control**:
  - `bool` → toggle
  - `int` / `float` → number input (with unit hint where known)
  - `str` → text input
  - `list` → tag/line editor (one item per line)
  - `dict` → nested sub-form (recursive)
  - **known enum** → `<select>` dropdown (options from a curated `ENUMS` map below)
  - **unknown enum** → free text input (safe fallback)
- **Staging**: edits accumulate in a local `draft` state; **Save** sends
  `PUT /api/config` with the *full* edited config object (server validates → 422 on
  bad shape, 200 on success). **Discard** resets draft.
- **Validation**: client-side required/type check before PUT; surface server 422
  `detail` as field errors.
- **Feedback**: toast on save success/failure; auto-refresh the tree from response.

### Curated ENUMS (dropdown options we KNOW — sourced from config semantics)
- `display.interface` → e.g. `[cli, tui, web, desktop]` (confirm from schema)
- `approvals.mode` → `[auto, ask, deny]`
- `terminal.backend` → `[pty, pipe, docker]`
- `web.search_backend` / `extract_backend` → `[duckduckgo, bing, ...]`
- `gateway.strict` → bool already; `logging.level` → `[DEBUG, INFO, WARNING, ERROR]`
- `streaming.transport` → `[sse, ws, ...]`
- Others added as we confirm valid values from `config.yaml` (the source of truth).
  Unknown keys = free text. **No invented allowed-values.**

### Stage 2 deliverable
Full read/write of any config key via type-aware + dropdown controls, validated
through `PUT /api/config`. (If a specific key is server-read-only, the API 422 will
tell us and we mark it read-only in the UI.)

---

## File changes
- `mission-control-standalone.html` — major: new shell (left rail + main pane),
  all new section Views, UI primitives, (Stage 2) editor + `ENUMS` + `PUT` handler.
- `mc_srv.py` — unchanged (proxy already forwards token + handles PUT/POST/DELETE/OPTIONS).
  May add a `/api/config` write pass-through (already covered by the generic proxy).
- `start-mission-control.sh` — unchanged (auto-starts 9119, vendors React, runs server).
- `vendor/react*.js` — unchanged (local, pinned 18.3.1).
- `hermes-mission-control.html` / `~/.hermes/plugins/...` — left for review (non-functional
  legacy plugin; not touched).

## Verification (each stage)
- Server-side: curl each endpoint via 9120 proxy WITH token → 200.
- Browser: hard-refresh 9120; every tab populates with real data.
- Stage 2: edit a `bool` (e.g. `memory.enabled`) → Save → `PUT` 200 → toggle
  reflects in `/api/config` on reload. Negative: empty/invalid → 422 surfaced, no crash.
- No regression to 9119 (still 200, untouched).

## Open questions to confirm during build (not blocking)
1. Is there a `/api/sessions` list route (for the Sessions section list), or only `/stats`?
2. Exact enum values for `display.interface`, `approvals.mode`, `terminal.backend`
   (read from `config.yaml` at build time).
3. Are any config keys server-read-only (would 422 on PUT)? We'll discover via testing.
