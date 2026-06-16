#!/usr/bin/env python3
"""Push skills marked publish='yes' in skill_backup.db to the public hermes-skills repo."""

import sqlite3, os, shutil, subprocess, sys
from datetime import date

DB_PATH = "/home/master/Documents/database/skill_backup.db"
REPO_DIR = os.path.expanduser("~/Documents/Backup/hermes-skills")
SKILLS_BASE = os.path.expanduser("~/.hermes/skills")


def find_skill_dir(skill_name):
    """Find the directory containing a skill's SKILL.md by name."""
    for root, dirs, files in os.walk(SKILLS_BASE):
        if "SKILL.md" in files and os.path.basename(root) == skill_name:
            return root
    return None


def get_publish_skills():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT skill_name FROM skill_status WHERE publish='yes'").fetchall()
    return [r[0] for r in rows]


def sync(publish_skills):
    # Clone or reset repo
    if os.path.exists(REPO_DIR):
        shutil.rmtree(REPO_DIR)
    os.makedirs(REPO_DIR, exist_ok=True)

    copied = []
    skipped = []
    for name in publish_skills:
        src = find_skill_dir(name)
        if src is None:
            skipped.append(name)
            print(f"  SKIP {name}: not found under {SKILLS_BASE}")
            continue
        dst = os.path.join(REPO_DIR, name)
        shutil.copytree(src, dst, dirs_exist_ok=True)
        copied.append(name)

    if not copied:
        print("No skills to publish.")
        return

    # Git commit + push
    subprocess.run(["git", "init"], cwd=REPO_DIR, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Hermes Agent"], cwd=REPO_DIR, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "hermes@local"], cwd=REPO_DIR, check=True, capture_output=True)

    today = date.today().isoformat()
    msg = f"publish {len(copied)} skills — {today}"

    subprocess.run(["git", "add", "."], cwd=REPO_DIR, check=True, capture_output=True)
    result = subprocess.run(["git", "commit", "-m", msg], cwd=REPO_DIR, capture_output=True, text=True)
    if result.returncode != 0:
        print("  No changes to commit (nothing new).")
        return

    # Set remote and push
    subprocess.run(["git", "remote", "add", "origin", "git@github.com:andomiam/hermes-skills.git"], cwd=REPO_DIR, check=True, capture_output=True)
    result = subprocess.run(["git", "push", "-u", "origin", "main"], cwd=REPO_DIR, capture_output=True, text=True)
    if result.returncode != 0:
        # Try master branch
        subprocess.run(["git", "branch", "-M", "master"], cwd=REPO_DIR, check=True, capture_output=True)
        result = subprocess.run(["git", "push", "-u", "origin", "master"], cwd=REPO_DIR, capture_output=True, text=True)

    print(f"\nPublished {len(copied)} skills to hermes-skills (public)")
    if skipped:
        print(f"Skipped {len(skipped)} skills not found on disk.")


if __name__ == "__main__":
    publish = get_publish_skills()
    if not publish:
        print("No skills marked publish='yes'. Nothing to push.")
        sys.exit(0)
    sync(publish)
