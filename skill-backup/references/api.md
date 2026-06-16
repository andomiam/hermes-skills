# Skill Curator API Reference

Base URL: `http://localhost:8086`

## GET /api/skills

Returns all skills with their current status.

**Response:** JSON array of objects:
```json
[
  {
    "skill_name": "b64",
    "status": "keep",
    "author": "Hermes Agent",
    "publish": "no"
  }
]
```

The `publish` field indicates whether the skill is marked for public publishing (`"yes"`) or not (`"no"`). Skills with `status="keep"` and `publish="yes"` appear in both the Keep and Publish tabs.

## PUT /api/skills/<name>/status

Set a skill's status.

**Body:** `{"status": "keep"}` or `{"status": "ignore"}`

**Response:** `{"ok": true}`

**Error (400):** If status is not "keep" or "ignore".

## PUT /api/skills/<name>/publish

Toggle a skill's publish flag. Auto-sets status to "keep" if toggling on for non-kept skills.

**Body:** `{"value": "yes"}` or `{"value": "no"}`

**Response:** `{"ok": true}`

**Error (400):** If value is not "yes" or "no".
**Error (404):** If skill not found.

## GET /api/skills/<name>/publish

Get a skill's current publish flag.

**Response:** `{"publish": "no"}` or `{"publish": "yes"}`

**Error (404):** If skill not found.

## DELETE /api/skills/<name>/status

Remove a skill from the DB entirely.

**Response:** `{"ok": true}`

## GET /api/scan

Force re-scan of `~/.hermes/skills` directory. Updates DB with any new skills found.

**Response:** `{"scanned": <count>}`

## PUT /api/skills/<name>/banished

Toggle a skill's banished flag. When set to "yes", deletes the SKILL.md from disk and sets `banished=1` in DB (persists regardless of disk state). When set to "no", un-banishes but keeps file on disk.

**Body:** `{"value": "yes"}` or `{"value": "no"}`

**Response:** `{"ok": true}`

**Error (400):** If value is not "yes" or "no".
**Error (404):** If skill not found.

## GET /api/skills/<name>/banished

Get a skill's current banish flag.

**Response:** `{"banished": true}` or `{"banished": false}`

**Error (404):** If skill not found.
