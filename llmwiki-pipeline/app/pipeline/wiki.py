"""Step 3 of the pipeline: persist wiki docs and commit them to the repo.

Generated markdown is written to the wiki directory (``WIKI_DIR``, default
``app/wiki``). "Committing" a reviewed doc runs ``git add`` + ``git commit`` so
the change lands in this repository.
"""

from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path

from .config import PROJECT_ROOT, wiki_path


def _ensure_wiki_dir() -> Path:
    d = wiki_path()
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_filename(slug: str, when: date | None = None) -> str:
    when = when or date.today()
    safe_slug = re.sub(r"[^\w가-힣-]+", "-", slug, flags=re.UNICODE).strip("-") or "untitled"
    return f"{when.isoformat()}-{safe_slug}.md"


def save_doc(markdown: str, slug: str, filename: str | None = None, when: date | None = None) -> Path:
    """Write a markdown doc to the wiki directory and return its path."""
    d = _ensure_wiki_dir()
    name = filename or build_filename(slug, when)
    if not name.endswith(".md"):
        name += ".md"
    path = d / name
    path.write_text(markdown, encoding="utf-8")
    return path


def _parse_title(markdown: str) -> str:
    # front-matter title first
    fm = re.search(r'^---\s*\n(.*?)\n---\s*\n', markdown, flags=re.DOTALL)
    if fm:
        t = re.search(r'^title:\s*"?(.*?)"?\s*$', fm.group(1), flags=re.MULTILINE)
        if t:
            return t.group(1).strip()
    # else first H1
    h1 = re.search(r"^#\s+(.+)$", markdown, flags=re.MULTILINE)
    return h1.group(1).strip() if h1 else ""


def list_docs() -> list[dict]:
    """List wiki docs (filename, path, title), newest filename first."""
    d = wiki_path()
    if not d.exists():
        return []
    docs = []
    for p in sorted(d.glob("*.md"), reverse=True):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            text = ""
        docs.append({"filename": p.name, "path": str(p), "title": _parse_title(text) or p.stem})
    return docs


def read_doc(filename: str) -> str:
    path = (wiki_path() / filename).resolve()
    _assert_within_wiki(path)
    return path.read_text(encoding="utf-8")


def delete_doc(filename: str, commit: bool = True, message: str | None = None) -> dict:
    """Delete a wiki doc from disk and (optionally) commit its removal.

    Returns ``{"filename", "deleted", "commit"}``. ``commit`` is None when the
    caller opted out; otherwise it is the ``git_commit`` result (which reports
    ``committed: False`` when the file was untracked, i.e. nothing to commit)."""
    path = (wiki_path() / filename).resolve()
    _assert_within_wiki(path)
    if path.suffix != ".md":
        raise ValueError("위키 문서(.md)만 삭제할 수 있습니다.")
    if not path.exists():
        raise FileNotFoundError(f"문서를 찾을 수 없습니다: {filename}")

    title = ""
    try:
        title = _parse_title(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass

    path.unlink()

    commit_result = None
    if commit:
        msg = message or f"docs(wiki): remove {title or path.stem}"
        commit_result = git_commit([path], msg)
    return {"filename": path.name, "deleted": True, "commit": commit_result}


def _assert_within_wiki(path: Path) -> None:
    wiki = wiki_path().resolve()
    if wiki not in path.parents and path != wiki:
        raise ValueError(f"Refusing to access path outside wiki dir: {path}")


def _run_git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )


def git_commit(paths: list[Path], message: str) -> dict:
    """Commit ONLY the given paths (pathspec-scoped) so unrelated staged
    changes are never swept into a wiki commit. Returns
    ``{"ok", "committed", "output"}``."""
    rel = [str(Path(p).resolve()) for p in paths]
    add = _run_git(["add", "--", *rel])
    if add.returncode != 0:
        return {"ok": False, "committed": False, "output": (add.stderr or add.stdout).strip()}

    # Nothing changed for these paths? report gracefully instead of committing.
    diff = _run_git(["diff", "--cached", "--quiet", "--", *rel])
    if diff.returncode == 0:
        return {"ok": True, "committed": False, "output": "No changes to commit."}

    # Pathspec-limited commit: only the listed paths are included even if other
    # files happen to be staged in the index.
    commit = _run_git(["commit", "-m", message, "--", *rel])
    out = (commit.stdout + commit.stderr).strip()
    return {"ok": commit.returncode == 0, "committed": commit.returncode == 0, "output": out}


def save_and_commit(
    markdown: str,
    slug: str,
    message: str | None = None,
    filename: str | None = None,
) -> dict:
    """Save a doc then commit it. Returns ``{"path", "filename", "commit"}``."""
    path = save_doc(markdown, slug, filename=filename)
    title = _parse_title(markdown) or slug
    msg = message or f"docs(wiki): add {title}"
    commit = git_commit([path], msg)
    return {"path": str(path), "filename": path.name, "commit": commit}
