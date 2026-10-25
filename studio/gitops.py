"""Git per game. Main repo stays on `main`; every ticket works in its own worktree + branch.
Nothing reaches main except `merge_commit`, which the studio only calls after Gate 3 approval."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

AUTHOR = ["-c", "user.name=AI Game Studio", "-c", "user.email=studio@localhost", "-c", "commit.gpgsign=false"]


class GitError(Exception):
    pass


def git(cwd: Path, *args: str, check: bool = True) -> str:
    p = subprocess.run(["git", *AUTHOR, *args], cwd=str(cwd), capture_output=True, text=True)
    if check and p.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {p.stderr.strip() or p.stdout.strip()}")
    return p.stdout


def init_repo(repo: Path) -> None:
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "Initial Godot 4.3 project skeleton")


def head(cwd: Path, ref: str = "HEAD") -> str:
    return git(cwd, "rev-parse", ref).strip()


def ensure_worktree(repo: Path, wt: Path, branch: str) -> None:
    if wt.exists() and (wt / ".git").exists():
        return
    if wt.exists():
        shutil.rmtree(wt)
    wt.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "prune")
    exists = git(repo, "branch", "--list", branch).strip() != ""
    if exists:
        git(repo, "worktree", "add", "-q", str(wt), branch)
    else:
        git(repo, "worktree", "add", "-q", "-b", branch, str(wt), "main")


def sync_with_main(wt: Path) -> list[str]:
    """Merge main into the ticket branch. Returns conflicted files (left with markers for the agent)."""
    p = subprocess.run(["git", *AUTHOR, "merge", "--no-edit", "-q", "main"], cwd=str(wt), capture_output=True, text=True)
    if p.returncode == 0:
        return []
    files = git(wt, "diff", "--name-only", "--diff-filter=U", check=False).split()
    if not files:
        git(wt, "merge", "--abort", check=False)
    return files


def commit_all(wt: Path, message: str) -> bool:
    git(wt, "add", "-A")
    if not git(wt, "status", "--porcelain").strip():
        return False
    git(wt, "commit", "-q", "-m", message)
    return True


def ahead_of_main(wt: Path) -> int:
    return int(git(wt, "rev-list", "--count", "main..HEAD").strip() or 0)


def diff_vs_main(wt: Path, limit: int = 200_000) -> tuple[str, list[str]]:
    d = git(wt, "diff", "main...HEAD")
    files = git(wt, "diff", "--name-only", "main...HEAD").split()
    if len(d) > limit:
        d = d[:limit] + f"\n... diff truncated ({len(d)} bytes total)\n"
    return d, files


def merge_commit(repo: Path, sha: str, message: str) -> tuple[bool, str]:
    """Merge exactly the approved commit into main. Returns (ok, detail)."""
    if git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() != "main":
        git(repo, "checkout", "-q", "main")
    p = subprocess.run(["git", *AUTHOR, "merge", "--no-ff", "-q", "-m", message, sha], cwd=str(repo),
                       capture_output=True, text=True)
    if p.returncode != 0:
        git(repo, "merge", "--abort", check=False)
        return False, (p.stdout + p.stderr).strip()
    return True, head(repo)


def remove_worktree(repo: Path, wt: Path) -> None:
    git(repo, "worktree", "remove", "--force", str(wt), check=False)
    if wt.exists():
        shutil.rmtree(wt, ignore_errors=True)
    git(repo, "worktree", "prune", check=False)
