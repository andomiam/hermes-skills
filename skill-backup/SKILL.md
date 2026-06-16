---
name: skill-backup
description: "Web UI for curating which manual skills to keep or ignore for backups. Auto-scans ~/.hermes/skills for 'Hermes Agent' authored skills and stores decisions in a SQLite DB."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [skills, backup, filtering]
---

# Skill Backup (Manual Keep/Ignore Filter)

Web UI for curating which manual skills to keep or ignore for backups. Auto-scans `~/.hermes/skills` for "Hermes Agent" authored skills and stores decisions in a SQLite DB.

## Distinction from Built-in `hermes curator`

| | `skill-backup` (this tool) | `hermes curator` (built-in) |
|---|---|---|
| **Purpose** | Manual keep/ignore filter for backup selection | Automated lifecycle: stale → archive → restore |
| **Scope** | Only agent-created skills with `author: "Hermes Agent"` | Same, but also handles bundled + hub-installed (read-only) |
| **Actions** | Keep / Ignore per skill; Publish toggle for public listing | Status transitions (stale, archive, unarchive, pin) |
| **CLI** | Web UI at port 8086 | `hermes curator <verb>` (`status`, `run`, `pin`, etc.) |

Do not confuse the two — they serve different stages of skill management. This tool is for deciding which skills to include in backups; the built-in curator handles automated maintenance.

## Launch

```bash
cd /home/master/Documents/Tools/skill-backup && python3 app.py
# Runs at http://localhost:8086
```

Also registered with the Tools Dashboard as `skill-curator` (port 8086, auto-start mode).

### Restarting

Kill stale process first — Flask dev server ignores SIGTERM:
```bash
fuser -k 8086/tcp; sleep 1; cd /home/master/Documents/Tools/skill-backup && python3 app.py &
```

## How it works

1. **Auto-scan**: On every API call, scans `~/.hermes/skills` for SKILL.md files with `author:` starting with "Hermes Agent"
2. **DB sync**: Inserts new skills as `pending`, removes deleted ones from DB (marks them pending again if they reappear)
3. **Curate**: User marks each skill as `keep` or `ignore` via the web UI, and optionally toggles publish flag for public listing
4. **Backup integration**: `backup-manual-skills` reads only `status='keep'` entries; publish flag is separate (for public listing)

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/skills` | GET | List all skills with status (keep/ignore/pending) and publish flag |
| `/api/skills/<name>/status` | PUT | Set skill status: `{"status": "keep"}` or `{"status": "ignore"}` |
| `/api/skills/<name>/publish` | PUT | Toggle publish flag: `{"value": "yes"}` or `{"value": "no"}` (auto-sets keep if needed) |
| `/api/skills/<name>/publish` | GET | Get current publish flag for a skill |
| `/api/skills/<name>/status` | DELETE | Remove skill from DB entirely |
| `/api/skills/<name>/details` | PUT | Save description/note: `{\"description\": \"...\", \"note\": \"...\"}` |
| `/api/skills/<name>/banished` | GET | Get current banish flag for a skill |
| `/api/skills/<name>/disk` | DELETE | Delete skill from disk but keep in DB (resets banished, sets pending) |
| `/api/scan` | GET | Force re-scan of skills directory |

## Web UI Features (Tabbed Interface)

### Modal Details Editor

Clicking any skill card opens a modal overlay with editable fields:
- **Skill name** and **author** displayed as read-only headers
- **Description** textarea — free-text field for summarizing what the skill does
- **Note** textarea — free-text field for reminders, context, or TODOs
- **Save** button writes to `PUT /api/skills/<name>/details` (persists description + note in DB), then auto-closes the modal
- **Close** button closes without saving (was "Cancel" — renamed for clarity)
- Close also works by clicking the dark overlay backdrop or pressing Escape

Action buttons on cards use `event.stopPropagation()` so they don't trigger the modal. Cards show a pointer cursor and "Click to edit details" tooltip.

## Web UI Features (Tabbed Interface)

The current UI uses **tabbed filtering** instead of a single mixed list:

### Tabs
- Five tabs in order: **Keep → Publish → Pending → Ignore → Banished** — each shows only matching skills
- Default tab is "Keep"
- Each tab has colored styling matching its status:
  - Keep → green (#4ade80) with ✓ icon
  - Ignore → red (#f87171) with ✗ icon
  - Publish → lighter blue (#93c5fd) with 📤 icon — shows skills that are both kept AND marked for public publishing
  - Pending → yellow (#fbbf24) with ? icon
  - Banished → grey-brown (#8b7d6b) with 🚫 icon — deleted from disk but remembered; persists in DB regardless of disk state
- Tab counts shown as badges next to tab names

### Banished Skills
A "banished" skill is one that was deleted from disk but we want to remember it. Banished skills **persist in DB forever** regardless of whether they reappear on disk after a Hermes update — no auto-delete happens.

To banish a skill: click "🚫 Banish" on any kept skill, or toggle banish in the Banished tab. To un-banish (keep on disk): click "🔓 Un-banish". Bulk delete from disk via the "Delete All Banished" button at the top of the Banished tab — no per-item Del Disk buttons remain.

### Publish Behavior
- The **Publish** tab lists only skills where `status='keep'` AND `publish='yes'` (the "keep-publish" concept)
- Skills in the Keep tab also show a 📤 Pub / 📥 Unpub toggle button to mark/unmark for publishing
- Published skills display a blue "Publish" badge alongside their status badge
- Toggling publish on a non-kept skill auto-sets its status to "keep" first

### Layout
- Search bar + Rescan button in the header row (same line as title) — saves vertical space
- Stats bar shows all three counts for quick reference
- No bulk action buttons ("Keep All Pending" / "Ignore All Pending") — too dangerous

### Skill Info Layout (on cards)
- **Line 1**: skill name + author on the same line, side by side. Name inherits tab color; author is grey (#888).
- **Line 2**: description/note preview — shows first 120 chars of description and first 80 chars of note (separated by " · "). Truncated with ellipsis if too long. If no description or note exists, shows "Click to add description or note" in dim grey (#666).
- Skill names colored by status: green for keep, red for ignore, yellow for pending, light blue (#93c5fd) for published skills (publish-color class).

### Color-Coded List Items
- Cards have colored left borders matching status (green keep, red ignore, yellow pending).
- Status badges also color-coded.

## DB Schema

```sql
CREATE TABLE skill_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- keep / ignore / pending
    author TEXT,
    publish TEXT NOT NULL DEFAULT 'no',      -- yes | no — marks for public listing
    description TEXT DEFAULT '',             -- free-text summary of what the skill does
    note TEXT DEFAULT '',                    -- user notes/reminders about this skill
    banished INTEGER NOT NULL DEFAULT 0,     -- 1 = deleted from disk, persists in DB regardless of disk state
    updated_at TEXT DEFAULT (datetime('now'))
);
```

DB path: `/home/master/Documents/database/skill_backup.db`

The `publish` column enables the "keep-publish" concept: a skill with `status='keep'` and `publish='yes'` appears in both the Keep tab and the Publish tab. The backup integration (`backup-manual-skills`) reads only `status='keep'` entries; the publish flag is for public listing purposes.

The `banished` column tracks skills deleted from disk but remembered: they persist in DB forever regardless of whether they reappear on disk after a Hermes update — no auto-delete happens. Use the bulk "Delete All Banished" button to delete all banished skills from disk at once (keeps records in DB).

The `description` and `note` columns are user-editable via the modal details editor (click any skill card). They persist in the DB and round-trip through `/api/skills`.

## Dual-Repo Publishing Workflow

Two independent flags control two separate repos:

| Flag | Value | Destination Repo | Purpose |
|------|-------|------------------|---------|
| `status` | `keep`, `ignore`, `pending` | `hermes-skills-keep` (private) | Personal backup archive |
| `publish` | `yes`, `no` | `hermes-skills` (public) | Public listing for others to discover |

These are **independent**: a skill can be kept but not published, published but not kept, both, or neither. The web UI's Publish tab shows skills where BOTH flags are set (`status='keep' AND publish='yes'`).

### Sync Scripts
```bash
# Push publish='yes' skills → hermes-skills (public)
python3 /home/master/Documents/Tools/skill-backup/scripts/publish-skills.py

# Push status='keep' skills → hermes-skills-keep (private backup)
python3 /home/master/Documents/Tools/skill-backup/scripts/push-to-repo.py
```

Both scripts: find skill dirs recursively under `~/.hermes/skills`, git init, commit with date-stamped message, force-push to `master` branch of respective repos. Run after changing keep/publish status in the web UI. Since each run recreates the repo from scratch (different file timestamps → different commit hashes), both scripts use `-f` (force push) and target `master` directly — no fallback logic needed.

## Pitfalls

- **Publish inflates keep count**: Toggling publish on a non-kept skill auto-sets status='keep'. Review carefully before running backups if you've used publish toggles liberally.
- **Empty keep-list = no backups**: If no skills are marked "keep", the backup script backs up nothing. Always mark at least a few as "keep" before running `backup-manual-skills`.
- **Consolidated skills**: Skills like `web-app-patterns` (consolidated from sqlite-web-app + flask-dashboard) may have multiple SKILL.md files — only the umbrella directory gets scanned, not sub-skill directories.
- **Author detection is line-based**: Only checks first `author:` line in SKILL.md frontmatter. If author appears elsewhere or has different casing, it won't match.
- **Port 8086 conflicts on restart**: Flask dev server ignores SIGTERM. Always kill first: `fuser -k 8086/tcp; sleep 1`. Add sleep after kill for OS socket release.
- **Stale HTML in browser**: After UI changes, Flask dev server serves cached templates even on Ctrl+Shift+R hard-refresh. The fix: kill the process with `kill -9 <pid>` (or `fuser -k 8086/tcp`), wait **3 seconds** for OS socket release, then restart (`python3 app.py`). If multiple processes are running, kill all of them first. Confirmed June 15 — this is a persistent issue when deploying UI changes.
- **Bash wrapper leaves Python child alive**: When launched via `bash -lic set +m; cd ... && python3 app.py &`, killing the bash wrapper PID (found via `ps aux | grep skill-backup`) leaves the actual Python child running. Find it with `ps aux | grep "python3 app.py" | grep -v grep` and kill that PID directly. Confirmed June 16 — Tools Dashboard may only show/kill the wrapper PID.
- **DB migration idempotency**: The `ALTER TABLE ADD COLUMN publish` in init_db() is wrapped in try/except for idempotency, but on first run after adding the column, existing DB entries get default 'no'. If migrating an older DB that already has the column from a previous manual ALTER TABLE, no error occurs — just verify with `SELECT publish FROM skill_status LIMIT 1` after init.
- **CSS class removal during patches**: When patching CSS in app.py (e.g., replacing `.skill-info { ... }` block), existing color classes like `keep-color`, `ignore-color`, `pending-color` can be accidentally removed if the old_string doesn't include them. Always read the full file around the edit point before patching, and verify all four status color classes (`keep-color`, `publish-color`, `ignore-color`, `pending-color`) still exist after a CSS patch.
- **GitHub branch mismatch (master vs main)**: The local repo pushes to `master` branch, but GitHub's web UI defaults to showing `main`. After running `publish-skills.py`, always verify the remote is updated on BOTH branches — check with `git fetch origin && git log --oneline -3 origin/main` and compare against `origin/master`. If they diverge (old commits on main), push master to main: `git push origin master:main`. This prevents the misleading situation where local looks up-to-date but GitHub shows stale content.
- **Banished skills persist forever**: Banished skills stay in DB regardless of disk state — no auto-delete on reappear. When a banished skill reappears on disk (e.g., after Hermes update), it's automatically un-banished but keeps its existing status (`keep`/`ignore`/`pending`). To remove from disk: use the bulk "Delete All Banished" button at the top of the Banished tab. No per-item Del Disk buttons exist. The banish state is independent of `status` — a skill can be both `keep` and `banished`, which means "delete from disk but remember me".
- **Banish button auto-reset in sync_skills()**: The `sync_skills()` function has an auto-un-banish check: if a skill was previously banished (`old_banished == 1`) and still exists on disk, it gets un-banished. This fires on EVERY page load because the snapshot captures the user's change. Fix: track `_prev_known` across sync calls — only un-banish if the skill was NOT in `manual` during the previous sync (i.e., truly disappeared from disk and reappeared). Code pattern:
  ```python
  prev_known = getattr(sync_skills, '_prev_known', None)
  if prev_known is None:
      # First run after restart: initialize with all DB skills so nothing gets falsely un-banished
      prev_known = {r["skill_name"] for r in conn.execute("SELECT skill_name FROM skill_status").fetchall()}
  sync_skills._prev_known = prev_known
  # ... later ...
  if row and row["banished"] == 1 and old_banished == 1 and s["name"] not in prev_known:
      conn.execute("UPDATE skill_status SET banished=0 WHERE skill_name=?", (s["name"],))
  sync_skills._prev_known = known_names
  ```
- **First-run `_prev_known` must initialize from DB**: On first call after server restart, `sync_skills._prev_known` is None. If initialized as empty set `{}`, ALL banished skills that exist on disk get falsely un-banished (they appear to "reappear" because they weren't in the empty prev_known). Must initialize with all currently-known DB skill names instead.
- **Cleanup button keeps banished=1**: The `DELETE /api/skills/banished` endpoint deletes from disk but does NOT set `banished=0`. Banished skills stay in DB forever until manually removed or reappear on disk (auto-un-banish). This applies to both the Cleanup header button and the "Delete All Banished" button in the Banished tab.
- **Bulk delete all**: Click the "Delete All Banished" button at the top of the Banished tab to remove ALL banished skills from disk in one click. Records stay in DB with their current status (not reset to pending).
- **Per-item Reset button**: Each banished skill has a "🔄 Reset" button that checks if the skill exists on disk: if yes → un-banish and keep in DB; if no → remove from DB entirely. This is useful for cleaning up stale entries after manual deletions.
- **No per-item Del Disk buttons**: Individual "🗑️ Del Disk" buttons were removed from banished items (2026-06-16). Only the bulk "Delete All Banished" button at the top of the Banished tab remains for disk deletion. To delete a single banished skill, use Reset (if it exists on disk) or Delete All.
- **All tabs equally visible**: Ignore and Banished cards have no opacity dimming — removed `opacity: 0.6` from `.skill-card.ignore` and `opacity: 0.5` from `.skill-card.banished`. All five tabs (Keep, Publish, Pending, Ignore, Banished) render at full brightness.
- **Action buttons are tab-contextual**: In `app.py`'s JS `render()` function, action buttons (Keep/Ignore/Banish/Pub) are conditionally shown based on the current `activeTab`. "🚫 Banish" only appears when viewing the Ignore tab — not visible on Keep or Publish tabs. Fixed 2026-06-16: moved banish from `s.status === 'keep'` block into an `if (activeTab === 'ignore')` guard for kept skills, so it's hidden outside the Ignore tab.
- **Cleanup button**: A "🧹 Cleanup" button appears next to Rescan in the header bar. Calls `DELETE /api/skills/banished` which deletes ALL banished skills from disk (same endpoint as the "Delete All Banished" button in the Banished tab). Shows a confirmation dialog with count before executing. Useful for bulk-cleaning without navigating to the Banished tab.

## Support Files

- `references/api.md` — full REST API endpoint documentation
- `references/plan.md` — Banish button fix: sync_skills `_prev_known` tracking, first-run init, cleanup behavior
- `scripts/publish-skills.py` — Push skills with `publish='yes'` to the public `hermes-skills` repo
- `scripts/push-to-repo.py` — Push skills with `status='keep'` to the private `hermes-skills-keep` backup repo
