#!/usr/bin/env python3
"""Bulk-fill description fields in the skill-curator DB from SKILL.md files.

Usage:
    python3 fill_descriptions.py              # dry-run (prints what would change)
    python3 fill_descriptions.py --apply       # actually update the DB

Extracts descriptions from frontmatter `description:` field first,
falls back to the first meaningful paragraph after YAML frontmatter.
Skips skills that already have non-empty descriptions unless --force is used.
"""

import argparse
import os
import re
import sqlite3
import sys

DB_PATH = "/home/master/Documents/database/skill_curator.db"
SKILLS_DIR = os.path.expanduser("~/.hermes/skills")


def extract_description(skill_path):
    """Extract description from a SKILL.md file.

    Priority:
      1. Frontmatter `description:` field (stripped, joined)
      2. First meaningful paragraph after YAML frontmatter body
    Returns empty string if nothing found.
    """
    try:
        with open(skill_path, errors="replace") as f:
            content = f.read()

        # Priority 1: frontmatter description field
        desc_match = re.search(
            r"^description:\s*[\"']?(.+?)[\"']?\s*$", content, re.MULTILINE
        )
        if desc_match:
            desc = desc_match.group(1).strip().strip('"').strip("'").strip()
            desc = " ".join(desc.split())  # collapse whitespace
            return desc[:300]

        # Priority 2: first meaningful paragraph after frontmatter
        body = content
        if content.startswith("---"):
            end_fm = content.find("---", 3)
            if end_fm > 0:
                body = content[end_fm + 3 :]

        paragraphs = re.split(r"\n\s*\n", body.strip())
        for p in paragraphs[:5]:
            lines = [l.strip() for l in p.split("\n") if l.strip()]
            text = " ".join(lines)
            # Skip headers, code blocks, tables, short fragments
            if (
                not text.startswith("#")
                and not text.startswith("|")
                and not text.startswith("```")
                and len(text) > 20
            ):
                return text[:300]

        return ""
    except Exception as e:
        return f"Error reading {skill_path}: {e}"


def scan_skills():
    """Walk SKILLS_DIR, find author='Hermes Agent' SKILL.md files."""
    results = []
    for root, dirs, files in os.walk(SKILLS_DIR):
        if ".curator_backups" in root or ".hub" in root:
            continue
        if "SKILL.md" not in files:
            continue
        skill_path = os.path.join(root, "SKILL.md")
        with open(skill_path, errors="replace") as f:
            author = None
            for line in f:
                if line.startswith("author:"):
                    author = line.split(":", 1)[1].strip()
                    break
            else:
                continue
        if not author or not author.startswith("Hermes Agent"):
            continue
        skill_name = os.path.basename(os.path.dirname(skill_path))
        results.append((skill_name, skill_path))
    return sorted(results)


def main():
    parser = argparse.ArgumentParser(description="Fill descriptions in skill-curator DB")
    parser.add_argument("--apply", action="store_true", help="Actually update the DB")
    parser.add_argument("--force", action="store_true", help="Re-fill existing descriptions too")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)

    # Ensure columns exist (idempotent migration)
    for col_sql in [
        "ALTER TABLE skill_status ADD COLUMN publish TEXT DEFAULT 'no'",
        "ALTER TABLE skill_status ADD COLUMN description TEXT DEFAULT ''",
        "ALTER TABLE skill_status ADD COLUMN note TEXT DEFAULT ''",
    ]:
        try:
            conn.execute(col_sql)
        except Exception:
            pass

    # Sync DB with scanned skills (INSERT OR IGNORE for new ones)
    scanned = scan_skills()
    for name, _ in scanned:
        conn.execute(
            "INSERT OR IGNORE INTO skill_status (skill_name, author) VALUES (?, ?)",
            (name, "Hermes Agent"),
        )

    # Get all skills from DB
    rows = conn.execute("SELECT skill_name FROM skill_status ORDER BY skill_name").fetchall()

    changes = []
    for (skill_name,) in rows:
        # Find matching SKILL.md
        matched_path = None
        for name, path in scanned:
            if name == skill_name:
                matched_path = path
                break

        current_desc = conn.execute(
            "SELECT description FROM skill_status WHERE skill_name=?", (skill_name,)
        ).fetchone()
        current_desc = current_desc[0] if current_desc else ""

        if not args.force and current_desc.strip():
            continue  # skip already-filled unless --force

        desc = extract_description(matched_path) if matched_path else ""
        changes.append((skill_name, current_desc[:60], desc[:80]))

    print(f"{'Skill':<35} {'Current (trunc)':<40} {'New (trunc)':<60}")
    for name, cur, new in changes:
        marker = " [APPLY]" if args.apply else ""
        print(f"{name:<35} {cur:<40} {new:<60}{marker}")

    if not changes:
        print("No changes needed.")
        conn.close()
        return

    if args.apply:
        for name, _, desc in changes:
            conn.execute(
                "UPDATE skill_status SET description=?, updated_at=datetime('now') WHERE skill_name=?",
                (desc, name),
            )
        conn.commit()
        print(f"\nApplied {len(changes)} descriptions.")
    else:
        print("\n(Dry run — add --apply to update the DB)")

    # Report any skills with no extractable description
    remaining = conn.execute(
        "SELECT skill_name FROM skill_status WHERE description='' OR description IS NULL"
    ).fetchall()
    if remaining:
        print(f"\n{len(remaining)} skill(s) still have empty descriptions (no SKILL.md or unextractable):")
        for r in remaining:
            print(f"  - {r[0]}")

    conn.close()


if __name__ == "__main__":
    main()
