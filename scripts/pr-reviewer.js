// ============================================================
// AGENT 2: AI PR REVIEW AGENT
// ============================================================
//
// WHAT THIS DOES:
// Automatically reviews Pull Requests like a senior developer.
// When a PR is opened or updated, this agent:
//   1. Reads the PR diff (what lines changed)
//   2. Sends the diff to Claude for analysis
//   3. Claude checks for bugs, security issues, performance
//      problems, and code style
//   4. Agent posts a detailed review comment on the PR
//   5. Optionally approves or requests changes
//
// WHY THIS IS VALUABLE:
// - Catches bugs before human reviewers even look at the PR
// - Reviews happen in seconds, not hours/days
// - Consistent quality bar — never misses common issues
// - Frees up senior devs to focus on architecture, not typos
//
// HOW TO TRIGGER:
//   - Automatically: GitHub Action on pull_request events
//   - Manually: PR_NUMBER=5 node scripts/pr-reviewer.js
//
// ENVIRONMENT VARIABLES:
//   - GITHUB_TOKEN      — GitHub access token
//   - GITHUB_REPOSITORY — "owner/repo"
//   - ANTHROPIC_API_KEY  — Claude API key
//   - PR_NUMBER          — The PR to review
// ============================================================

import { askAIJSON } from "./lib/ai-client.js";
import {
  getPullRequest,
  getPullRequestDiff,
  getPullRequestFiles,
  submitReview,
  addLabels,
} from "./lib/github-client.js";

// -----------------------------------------------------------
// STEP 1: Parse the PR number from environment.
// -----------------------------------------------------------
const prNumber = parseInt(process.env.PR_NUMBER);

if (!prNumber) {
  console.error("❌ PR_NUMBER environment variable is required.");
  console.error("   Usage: PR_NUMBER=5 node scripts/pr-reviewer.js");
  process.exit(1);
}

console.log(`\n🔍 AI PR Review Agent starting for PR #${prNumber}\n`);

// -----------------------------------------------------------
// STEP 2: Fetch PR details, diff, and changed files.
//
// We gather three pieces of information:
// - PR metadata (title, description, author)
// - The raw diff (line-by-line changes)
// - List of changed files (with stats like additions/deletions)
// -----------------------------------------------------------
console.log("📖 Fetching PR details...");

const [pr, diff, files] = await Promise.all([
  getPullRequest(prNumber),
  getPullRequestDiff(prNumber),
  getPullRequestFiles(prNumber),
]);

console.log(`   Title: ${pr.title}`);
console.log(`   Author: ${pr.user.login}`);
console.log(`   Files changed: ${files.length}`);
console.log(
  `   Lines: +${files.reduce((sum, f) => sum + f.additions, 0)} / -${files.reduce((sum, f) => sum + f.deletions, 0)}`
);

// -----------------------------------------------------------
// STEP 3: Send the PR to Claude for review.
//
// Claude acts as a senior code reviewer, analyzing:
// - Correctness: Does the code do what it claims?
// - Security: SQL injection, XSS, secrets exposure?
// - Performance: N+1 queries, memory leaks, O(n²)?
// - Maintainability: Readability, naming, complexity?
// - Tests: Are changes tested? Are tests meaningful?
//
// The response is structured JSON so we can programmatically
// post review comments and decide approve/request-changes.
// -----------------------------------------------------------
console.log("🤖 Asking Claude to review the PR...");

const systemPrompt = `You are a senior software engineer performing a thorough code review.
Analyze the Pull Request diff and provide actionable, specific feedback.

REVIEW CATEGORIES (check each one):
1. **Bugs & Correctness** — Logic errors, edge cases, null/undefined risks
2. **Security** — Injection, XSS, hardcoded secrets, auth issues
3. **Performance** — Unnecessary loops, memory leaks, N+1 queries
4. **Code Quality** — Naming, readability, DRY violations, complexity
5. **Error Handling** — Missing try/catch, unhandled promises, silent failures
6. **Testing** — Are changes tested? Are edge cases covered?

RULES:
- Be specific: reference exact file names and line contexts.
- Be constructive: suggest fixes, don't just point out problems.
- Praise good code too — don't only be negative.
- If the PR is solid, say so clearly.
- Return ONLY valid JSON.

SEVERITY LEVELS:
- "critical"  — Must fix before merge (bugs, security holes)
- "warning"   — Should fix, but not a blocker
- "suggestion" — Nice to have improvement
- "praise"    — Something done well

RESPONSE FORMAT (strict JSON):
{
  "summary": "Overall assessment of the PR in 2-3 sentences",
  "verdict": "APPROVE" | "REQUEST_CHANGES" | "COMMENT",
  "risk_level": "low" | "medium" | "high",
  "comments": [
    {
      "file": "path/to/file.js",
      "line_context": "the code around the issue",
      "severity": "critical | warning | suggestion | praise",
      "category": "bugs | security | performance | quality | error-handling | testing",
      "message": "Detailed explanation of the issue and suggested fix"
    }
  ],
  "checklist": {
    "bugs_found": false,
    "security_issues": false,
    "performance_concerns": false,
    "tests_adequate": true,
    "docs_needed": false
  }
}`;

const userMessage = `Review this Pull Request.

## PR #${prNumber}: ${pr.title}
**Author:** ${pr.user.login}
**Description:**
${pr.body || "(no description)"}

## Changed Files (${files.length} files):
${files.map((f) => `- ${f.filename} (+${f.additions} -${f.deletions})`).join("\n")}

## Full Diff:
\`\`\`diff
${diff}
\`\`\`

Provide your review as JSON.`;

const review = await askAIJSON(systemPrompt, userMessage);

// -----------------------------------------------------------
// STEP 4: Format the review as a GitHub comment.
//
// We convert Claude's structured JSON into a nice Markdown
// comment that looks professional on GitHub.
// -----------------------------------------------------------
console.log(`\n📋 Review Summary: ${review.summary}`);
console.log(`   Verdict: ${review.verdict}`);
console.log(`   Risk Level: ${review.risk_level}`);
console.log(`   Comments: ${review.comments.length}`);

// Build the review body in Markdown
let reviewBody = `## 🤖 AI Code Review\n\n`;
reviewBody += `**Summary:** ${review.summary}\n\n`;
reviewBody += `**Risk Level:** ${review.risk_level === "high" ? "🔴" : review.risk_level === "medium" ? "🟡" : "🟢"} ${review.risk_level}\n\n`;

// Checklist
reviewBody += `### Checklist\n`;
reviewBody += `- [${review.checklist.bugs_found ? "x" : " "}] Bugs found\n`;
reviewBody += `- [${review.checklist.security_issues ? "x" : " "}] Security issues\n`;
reviewBody += `- [${review.checklist.performance_concerns ? "x" : " "}] Performance concerns\n`;
reviewBody += `- [${review.checklist.tests_adequate ? "x" : " "}] Tests adequate\n`;
reviewBody += `- [${review.checklist.docs_needed ? "x" : " "}] Documentation needed\n\n`;

// Group comments by severity
const severityOrder = ["critical", "warning", "suggestion", "praise"];
const severityEmoji = {
  critical: "🔴",
  warning: "🟡",
  suggestion: "💡",
  praise: "✅",
};

for (const severity of severityOrder) {
  const comments = review.comments.filter((c) => c.severity === severity);
  if (comments.length === 0) continue;

  reviewBody += `### ${severityEmoji[severity]} ${severity.charAt(0).toUpperCase() + severity.slice(1)} (${comments.length})\n\n`;

  for (const comment of comments) {
    reviewBody += `**\`${comment.file}\`** — ${comment.category}\n`;
    reviewBody += `> ${comment.message}\n`;
    if (comment.line_context) {
      reviewBody += `> \`${comment.line_context}\`\n`;
    }
    reviewBody += `\n`;
  }
}

reviewBody += `---\n🤖 *Review by AI PR Review Agent using Claude*`;

// -----------------------------------------------------------
// STEP 5: Submit the review on GitHub.
//
// The review can be:
// - APPROVE: Code looks good, merge away
// - REQUEST_CHANGES: Issues found, please fix before merging
// - COMMENT: Feedback provided, but not blocking
// -----------------------------------------------------------
console.log("📝 Posting review on GitHub...");

await submitReview({
  prNumber,
  body: reviewBody,
  event: review.verdict,
});

// Add labels based on risk level
const labels = ["ai-reviewed"];
if (review.risk_level === "high") labels.push("needs-attention");
if (review.checklist.security_issues) labels.push("security");

await addLabels(prNumber, labels);

// -----------------------------------------------------------
// DONE!
// -----------------------------------------------------------
console.log("\n" + "=".repeat(60));
console.log("🎉 AI PR Review Agent completed!");
console.log("=".repeat(60));
console.log(`   PR:       #${prNumber} — ${pr.title}`);
console.log(`   Verdict:  ${review.verdict}`);
console.log(`   Comments: ${review.comments.length}`);
console.log(`   Risk:     ${review.risk_level}`);
console.log("=".repeat(60) + "\n");
