# Skill Backup - Banish Button Fix

## Issue 1: Banish button not working (auto-reset)
When clicking "Banish" on a kept skill, the banished flag gets auto-reset to 0 on next page load.

### Root Cause
In `sync_skills()` line 94, the condition checked:
```python
if row and row["banished"] == 1 and old_banished == 1:
    # un-banish
```

`old_banished` is a snapshot taken at sync start. When user sets banished=1 via API, then on next page load:
- Snapshot captures `old_banished = 1` (user's change)
- Skill exists on disk → in `manual`
- Condition matches → auto-un-banish to 0

### Fix
Track previous sync's known_names. Only auto-un-banish if skill was previously NOT in `manual` (disappeared from disk between syncs):
```python
prev_known = getattr(sync_skills, '_prev_known', None)
if prev_known is None:
    # First run: initialize with all currently-known DB skills so nothing gets auto-un-banished
    prev_known = {r["skill_name"] for r in conn.execute("SELECT skill_name FROM skill_status").fetchall()}
sync_skills._prev_known = prev_known
# ... later ...
if row and row["banished"] == 1 and old_banished == 1 and s["name"] not in prev_known:
    # un-banish (skill reappeared on disk)
```

## Issue 2: Banish button visibility
"Banish" button should only be visible when viewing the **Ignore** tab. Not on Keep or Publish tabs.

### Fix
Wrapped banish button in `if (activeTab === 'ignore')` check for kept skills in render().

## Issue 3: Cleanup button un-banishing items
The `/api/skills/banished` DELETE endpoint was setting `banished=0` after deleting from disk, removing the banished status.

### Fix
Removed the `UPDATE skill_status SET banished=0` line — banished skills now stay in DB with `banished=1` forever until manually removed or reappear on disk (auto-un-banish).
