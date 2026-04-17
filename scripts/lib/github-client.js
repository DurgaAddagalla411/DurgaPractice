// ============================================================
// SHARED GITHUB CLIENT — Reusable helper used by ALL agents.
//
// WHY THIS EXISTS:
// Every agent needs to talk to the GitHub API (read issues,
// create branches, open PRs, post comments). Instead of
// duplicating that setup code in every script, we centralize
// it here. This follows the DRY principle.
//
// WHAT IT PROVIDES:
// - Pre-configured Octokit instance (GitHub SDK)
// - Helper functions for common operations:
//     • getRepoInfo()       — parse owner/repo from env
//     • createBranch()      — create a new git branch
//     • createOrUpdateFile() — commit a file to a branch
//     • createPullRequest() — open a PR
//     • addComment()        — post a comment on an issue/PR
//     • addLabels()         — add labels to an issue/PR
// ============================================================

import { Octokit } from "@octokit/rest";

// -----------------------------------------------------------
// Initialize Octokit with the GitHub token from environment.
//
// GITHUB_TOKEN is provided by:
// - GitHub Actions (automatically via `secrets.GITHUB_TOKEN`)
// - Your local .env file (for testing locally)
// -----------------------------------------------------------
const octokit = new Octokit({
  auth: process.env.GITHUB_TOKEN,
});

// -----------------------------------------------------------
// getRepoInfo() — Extracts owner and repo name from the
// GITHUB_REPOSITORY environment variable.
//
// GitHub Actions automatically sets this to "owner/repo".
// For local development, you set it in your .env file.
//
// Example: "octocat/hello-world" → { owner: "octocat", repo: "hello-world" }
// -----------------------------------------------------------
export function getRepoInfo() {
  const [owner, repo] = process.env.GITHUB_REPOSITORY.split("/");
  if (!owner || !repo) {
    throw new Error(
      'GITHUB_REPOSITORY must be in "owner/repo" format. ' +
        `Got: "${process.env.GITHUB_REPOSITORY}"`
    );
  }
  return { owner, repo };
}

// -----------------------------------------------------------
// getDefaultBranch() — Finds the repo's default branch name.
//
// Most repos use "main", but some older ones use "master".
// Instead of hardcoding, we ask the GitHub API.
// -----------------------------------------------------------
export async function getDefaultBranch() {
  const { owner, repo } = getRepoInfo();
  const { data } = await octokit.rest.repos.get({ owner, repo });
  return data.default_branch;
}

// -----------------------------------------------------------
// createBranch(branchName, fromBranch) — Creates a new branch.
//
// HOW IT WORKS:
// 1. Gets the latest commit SHA from the source branch
// 2. Creates a new git reference pointing to that SHA
//
// This is equivalent to: git checkout -b branchName fromBranch
//
// PARAMETERS:
//   branchName — name of the new branch (e.g., "fix/issue-42")
//   fromBranch — base branch to branch from (default: repo's default)
// -----------------------------------------------------------
export async function createBranch(branchName, fromBranch) {
  const { owner, repo } = getRepoInfo();

  // If no base branch specified, use the repo's default
  const baseBranch = fromBranch || (await getDefaultBranch());

  // Step 1: Get the SHA (commit hash) of the latest commit on the base branch
  const { data: refData } = await octokit.rest.git.getRef({
    owner,
    repo,
    ref: `heads/${baseBranch}`,
  });

  // Step 2: Create a new branch reference pointing to that same commit
  // The new branch starts as an exact copy of the base branch.
  await octokit.rest.git.createRef({
    owner,
    repo,
    ref: `refs/heads/${branchName}`,
    sha: refData.object.sha,
  });

  console.log(`✅ Branch created: ${branchName} (from ${baseBranch})`);
  return branchName;
}

// -----------------------------------------------------------
// createOrUpdateFile(branch, path, content, message)
//
// Commits a single file to a branch via the GitHub API.
// If the file already exists, it updates it; otherwise creates it.
//
// HOW IT WORKS:
// - GitHub's Contents API lets you create/update files with a
//   single API call — no need to clone the repo locally.
// - If updating, you must provide the file's current SHA so
//   GitHub knows which version you're replacing (prevents conflicts).
//
// PARAMETERS:
//   branch  — target branch to commit to
//   path    — file path in the repo (e.g., "src/utils.js")
//   content — the full file content (will be base64 encoded)
//   message — git commit message
// -----------------------------------------------------------
export async function createOrUpdateFile(branch, path, content, message) {
  const { owner, repo } = getRepoInfo();

  // Check if the file already exists (we need its SHA to update it)
  let existingSha;
  try {
    const { data } = await octokit.rest.repos.getContent({
      owner,
      repo,
      path,
      ref: branch,
    });
    existingSha = data.sha;
  } catch (error) {
    // File doesn't exist yet — that's fine, we'll create it
    if (error.status !== 404) throw error;
  }

  // Create or update the file
  // The GitHub API requires content to be Base64 encoded
  await octokit.rest.repos.createOrUpdateFileContents({
    owner,
    repo,
    path,
    message,
    content: Buffer.from(content).toString("base64"),
    branch,
    ...(existingSha && { sha: existingSha }),
  });

  console.log(`✅ File committed: ${path} → ${branch}`);
}

// -----------------------------------------------------------
// getFileContent(path, branch) — Read a file's content from the repo.
//
// Returns the decoded (UTF-8) content of the file.
// Useful for agents that need to read existing code before modifying it.
// -----------------------------------------------------------
export async function getFileContent(path, branch) {
  const { owner, repo } = getRepoInfo();

  const { data } = await octokit.rest.repos.getContent({
    owner,
    repo,
    path,
    ref: branch || (await getDefaultBranch()),
  });

  // GitHub returns file content as Base64 — decode it
  return Buffer.from(data.content, "base64").toString("utf-8");
}

// -----------------------------------------------------------
// listFiles(path, branch) — List files in a directory.
//
// Returns an array of { name, path, type } objects.
// type is "file" or "dir".
// -----------------------------------------------------------
export async function listFiles(path = "", branch) {
  const { owner, repo } = getRepoInfo();

  const { data } = await octokit.rest.repos.getContent({
    owner,
    repo,
    path,
    ref: branch || (await getDefaultBranch()),
  });

  return Array.isArray(data)
    ? data.map((item) => ({
        name: item.name,
        path: item.path,
        type: item.type,
      }))
    : [{ name: data.name, path: data.path, type: data.type }];
}

// -----------------------------------------------------------
// createPullRequest({ title, body, head, base })
//
// Opens a new Pull Request on the repo.
//
// PARAMETERS:
//   title — PR title (short, descriptive)
//   body  — PR description (supports Markdown)
//   head  — the branch with your changes
//   base  — the branch you want to merge into (usually "main")
//
// RETURNS: The created PR object (includes .number, .html_url)
// -----------------------------------------------------------
export async function createPullRequest({ title, body, head, base }) {
  const { owner, repo } = getRepoInfo();
  const baseBranch = base || (await getDefaultBranch());

  const { data: pr } = await octokit.rest.pulls.create({
    owner,
    repo,
    title,
    body,
    head,
    base: baseBranch,
  });

  console.log(`✅ PR created: #${pr.number} — ${pr.html_url}`);
  return pr;
}

// -----------------------------------------------------------
// addComment(issueNumber, body) — Post a comment on an issue or PR.
//
// In GitHub's API, issues and PRs share the same comment system.
// So this works for both.
// -----------------------------------------------------------
export async function addComment(issueNumber, body) {
  const { owner, repo } = getRepoInfo();

  await octokit.rest.issues.createComment({
    owner,
    repo,
    issue_number: issueNumber,
    body,
  });

  console.log(`✅ Comment added to #${issueNumber}`);
}

// -----------------------------------------------------------
// addLabels(issueNumber, labels) — Add labels to an issue or PR.
//
// labels is an array of label name strings, e.g. ["bug", "ai-fix"].
// If a label doesn't exist on the repo, GitHub will create it.
// -----------------------------------------------------------
export async function addLabels(issueNumber, labels) {
  const { owner, repo } = getRepoInfo();

  await octokit.rest.issues.addLabels({
    owner,
    repo,
    issue_number: issueNumber,
    labels,
  });

  console.log(`✅ Labels added to #${issueNumber}: ${labels.join(", ")}`);
}

// -----------------------------------------------------------
// getIssue(issueNumber) — Fetch full details of a GitHub issue.
// -----------------------------------------------------------
export async function getIssue(issueNumber) {
  const { owner, repo } = getRepoInfo();

  const { data } = await octokit.rest.issues.get({
    owner,
    repo,
    issue_number: issueNumber,
  });

  return data;
}

// -----------------------------------------------------------
// getPullRequest(prNumber) — Fetch full details of a PR.
// -----------------------------------------------------------
export async function getPullRequest(prNumber) {
  const { owner, repo } = getRepoInfo();

  const { data } = await octokit.rest.pulls.get({
    owner,
    repo,
    pull_number: prNumber,
  });

  return data;
}

// -----------------------------------------------------------
// getPullRequestDiff(prNumber) — Get the raw diff of a PR.
//
// This returns the unified diff text showing exactly what
// lines were added/removed. Used by the PR review agent.
// -----------------------------------------------------------
export async function getPullRequestDiff(prNumber) {
  const { owner, repo } = getRepoInfo();

  const { data } = await octokit.rest.pulls.get({
    owner,
    repo,
    pull_number: prNumber,
    mediaType: { format: "diff" },
  });

  return data;
}

// -----------------------------------------------------------
// getPullRequestFiles(prNumber) — List files changed in a PR.
// -----------------------------------------------------------
export async function getPullRequestFiles(prNumber) {
  const { owner, repo } = getRepoInfo();

  const { data } = await octokit.rest.pulls.listFiles({
    owner,
    repo,
    pull_number: prNumber,
  });

  return data;
}

// -----------------------------------------------------------
// createReviewComment({ prNumber, body, path, line })
//
// Posts an inline review comment on a specific line of a PR.
// This is what shows up as "review comments" in the PR diff view.
// -----------------------------------------------------------
export async function createReviewComment({ prNumber, body, path, line }) {
  const { owner, repo } = getRepoInfo();

  await octokit.rest.pulls.createReviewComment({
    owner,
    repo,
    pull_number: prNumber,
    body,
    path,
    line,
    side: "RIGHT",
    commit_id: (await getPullRequest(prNumber)).head.sha,
  });
}

// -----------------------------------------------------------
// submitReview({ prNumber, body, event })
//
// Submits a full PR review (APPROVE, REQUEST_CHANGES, or COMMENT).
// -----------------------------------------------------------
export async function submitReview({ prNumber, body, event }) {
  const { owner, repo } = getRepoInfo();

  await octokit.rest.pulls.createReview({
    owner,
    repo,
    pull_number: prNumber,
    body,
    event, // "APPROVE" | "REQUEST_CHANGES" | "COMMENT"
  });

  console.log(`✅ Review submitted on PR #${prNumber}: ${event}`);
}

// -----------------------------------------------------------
// mergePullRequest(prNumber, method) — Merge a PR.
//
// method: "merge" | "squash" | "rebase"
// -----------------------------------------------------------
export async function mergePullRequest(prNumber, method = "squash") {
  const { owner, repo } = getRepoInfo();

  await octokit.rest.pulls.merge({
    owner,
    repo,
    pull_number: prNumber,
    merge_method: method,
  });

  console.log(`✅ PR #${prNumber} merged via ${method}`);
}

// -----------------------------------------------------------
// listOpenPullRequests() — List all open PRs in the repo.
// -----------------------------------------------------------
export async function listOpenPullRequests() {
  const { owner, repo } = getRepoInfo();

  const { data } = await octokit.rest.pulls.list({
    owner,
    repo,
    state: "open",
    sort: "updated",
    direction: "desc",
  });

  return data;
}

// -----------------------------------------------------------
// closePullRequest(prNumber) — Close a PR without merging.
// -----------------------------------------------------------
export async function closePullRequest(prNumber) {
  const { owner, repo } = getRepoInfo();

  await octokit.rest.pulls.update({
    owner,
    repo,
    pull_number: prNumber,
    state: "closed",
  });

  console.log(`✅ PR #${prNumber} closed`);
}

// Export the raw octokit instance for advanced use cases
export { octokit };
