# ============================================================
# SHARED GITHUB CLIENT — Talks to GitHub API via PyGithub.
#
# WHAT IT PROVIDES:
#   - get_repo()             → PyGithub repo object
#   - get_issue(number)      → issue object
#   - get_file_content(path) → file content as string
#   - list_files(path)       → list of files in a directory
#   - create_branch(name)    → create a new branch
#   - create_or_update_file() → commit a file to a branch
#   - create_pull_request()  → open a PR
#   - add_comment()          → post a comment on issue/PR
#   - add_labels()           → add labels to issue/PR
#   - get_pull_request()     → PR object
#   - get_pr_diff()          → raw diff text
#   - get_pr_files()         → list of changed files
#   - submit_review()        → post a PR review
#   - merge_pr()             → merge a PR
#   - close_pr()             → close a PR
#   - list_open_prs()        → all open PRs
#
# USAGE:
#   from lib.github_client import get_repo, get_issue, create_branch
# ============================================================

import os
import base64
import requests
from github import Github, GithubException
from lib.logger import create_logger

# Create logger for GitHub operations
log = create_logger("GitHub-API")

# -----------------------------------------------------------
# Initialize PyGithub with the token from environment.
# -----------------------------------------------------------
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO_NAME = os.environ.get("GITHUB_REPOSITORY", "")

gh = Github(GITHUB_TOKEN)


def get_repo():
    """Get the PyGithub repo object."""
    return gh.get_repo(REPO_NAME)


# -----------------------------------------------------------
# ISSUE OPERATIONS
# -----------------------------------------------------------

def get_issue(issue_number: int):
    """Fetch a GitHub issue by number."""
    repo = get_repo()
    return repo.get_issue(number=issue_number)


# -----------------------------------------------------------
# FILE OPERATIONS — Read files from the repo
# -----------------------------------------------------------

def get_file_content(file_path: str, branch: str = None) -> str:
    """
    Read a file's content from the repo.
    Returns the decoded UTF-8 content.
    """
    repo = get_repo()
    ref = branch or repo.default_branch
    content = repo.get_contents(file_path, ref=ref)
    return base64.b64decode(content.content).decode("utf-8")


def list_files(dir_path: str = "", branch: str = None) -> list:
    """
    List files in a directory.
    Returns list of dicts: [{"name": "app.js", "path": "src/app.js", "type": "file"}]
    """
    repo = get_repo()
    ref = branch or repo.default_branch
    contents = repo.get_contents(dir_path, ref=ref)
    return [
        {"name": item.name, "path": item.path, "type": item.type}
        for item in contents
    ]


# -----------------------------------------------------------
# BRANCH OPERATIONS
# -----------------------------------------------------------

def create_branch(branch_name: str, from_branch: str = None) -> str:
    """
    Create a new branch from the base branch.
    Equivalent to: git checkout -b branch_name
    """
    repo = get_repo()
    base = from_branch or repo.default_branch

    # Get the SHA of the latest commit on the base branch
    base_ref = repo.get_git_ref(f"heads/{base}")
    sha = base_ref.object.sha

    # Create the new branch pointing to that commit
    repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=sha)
    log.success(f"Branch created: {branch_name} (from {base})")
    return branch_name


# -----------------------------------------------------------
# FILE COMMIT OPERATIONS
# -----------------------------------------------------------

def create_or_update_file(branch: str, file_path: str, content: str, commit_message: str):
    """
    Commit a file to a branch via GitHub API.
    Creates the file if it doesn't exist, updates if it does.
    """
    repo = get_repo()

    # Check if file already exists (need its SHA to update)
    try:
        existing = repo.get_contents(file_path, ref=branch)
        repo.update_file(
            path=file_path,
            message=commit_message,
            content=content,
            sha=existing.sha,
            branch=branch,
        )
    except GithubException as e:
        if e.status == 404:
            # File doesn't exist — create it
            repo.create_file(
                path=file_path,
                message=commit_message,
                content=content,
                branch=branch,
            )
        else:
            raise

    log.success(f"File committed: {file_path} → {branch}")


# -----------------------------------------------------------
# PULL REQUEST OPERATIONS
# -----------------------------------------------------------

def create_pull_request(title: str, body: str, head: str, base: str = None) -> dict:
    """
    Open a new Pull Request.
    Returns dict with: number, html_url, title
    """
    repo = get_repo()
    base_branch = base or repo.default_branch

    pr = repo.create_pull(title=title, body=body, head=head, base=base_branch)
    log.success(f"PR created: #{pr.number} — {pr.html_url}")

    return {"number": pr.number, "html_url": pr.html_url, "title": pr.title}


def get_pull_request(pr_number: int):
    """Fetch a PR object by number."""
    repo = get_repo()
    return repo.get_pull(pr_number)


def get_pr_diff(pr_number: int) -> str:
    """
    Get the raw unified diff of a PR.
    Uses the GitHub REST API directly since PyGithub doesn't support diff format.
    """
    url = f"https://api.github.com/repos/{REPO_NAME}/pulls/{pr_number}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3.diff",
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.text


def get_pr_files(pr_number: int) -> list:
    """
    List files changed in a PR.
    Returns list of dicts with: filename, additions, deletions, status
    """
    repo = get_repo()
    pr = repo.get_pull(pr_number)
    return [
        {
            "filename": f.filename,
            "additions": f.additions,
            "deletions": f.deletions,
            "status": f.status,
        }
        for f in pr.get_files()
    ]


def submit_review(pr_number: int, body: str, event: str):
    """
    Submit a PR review.
    event: "APPROVE", "REQUEST_CHANGES", or "COMMENT"
    """
    repo = get_repo()
    pr = repo.get_pull(pr_number)
    pr.create_review(body=body, event=event)
    log.success(f"Review submitted on PR #{pr_number}: {event}")


def merge_pr(pr_number: int, method: str = "squash"):
    """
    Merge a PR.
    method: "merge", "squash", or "rebase"
    """
    repo = get_repo()
    pr = repo.get_pull(pr_number)
    pr.merge(merge_method=method)
    log.success(f"PR #{pr_number} merged via {method}")


def close_pr(pr_number: int):
    """Close a PR without merging."""
    repo = get_repo()
    pr = repo.get_pull(pr_number)
    pr.edit(state="closed")
    log.success(f"PR #{pr_number} closed")


def list_open_prs() -> list:
    """List all open PRs in the repo."""
    repo = get_repo()
    return list(repo.get_pulls(state="open", sort="updated", direction="desc"))


# -----------------------------------------------------------
# COMMENT & LABEL OPERATIONS
# -----------------------------------------------------------

def add_comment(issue_number: int, body: str):
    """Post a comment on an issue or PR."""
    repo = get_repo()
    issue = repo.get_issue(number=issue_number)
    issue.create_comment(body=body)
    log.success(f"Comment added to #{issue_number}")


def add_labels(issue_number: int, labels: list):
    """Add labels to an issue or PR."""
    repo = get_repo()
    issue = repo.get_issue(number=issue_number)

    for label_name in labels:
        try:
            repo.get_label(label_name)
        except GithubException:
            # Label doesn't exist — create it
            repo.create_label(name=label_name, color="7057ff")

    issue.add_to_labels(*labels)
    log.success(f"Labels added to #{issue_number}: {', '.join(labels)}")
