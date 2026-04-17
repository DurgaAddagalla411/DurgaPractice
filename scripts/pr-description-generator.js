// ============================================================
// AGENT 3: PR DESCRIPTION GENERATOR
// ============================================================
//
// WHAT THIS DOES:
// Automatically generates rich, detailed PR descriptions by
// analyzing the code diff. Many developers leave PR descriptions
// blank or write "fixed stuff" — this agent fills in the gap.
//
// THE FLOW:
//   1. Triggered when a PR is opened with an empty description
//   2. Reads the PR diff to understand what changed
//   3. Sends the diff to Claude for analysis
//   4. Claude generates a structured description with:
//      - Summary of changes
//      - Type of change (bug fix, feature, refactor, etc.)
//      - Files changed and why
//      - Testing suggestions
//      - Breaking changes (if any)
//   5. Agent updates the PR description on GitHub
//
// WHY THIS IS VALUABLE:
// - Saves developers time writing descriptions
// - Ensures consistent, high-quality PR documentation
// - Helps reviewers understand changes quickly
// - Creates a searchable history of why changes were made
//
// HOW TO TRIGGER:
//   - Automatically: GitHub Action on pull_request.opened
//   - Manually: PR_NUMBER=5 node scripts/pr-description-generator.js
// ============================================================

import { askAI } from "./lib/ai-client.js";
import {
  getPullRequest,
  getPullRequestDiff,
  getPullRequestFiles,
  addLabels,
  octokit,
  getRepoInfo,
} from "./lib/github-client.js";

// -----------------------------------------------------------
// STEP 1: Parse the PR number.
// -----------------------------------------------------------
const prNumber = parseInt(process.env.PR_NUMBER);

if (!prNumber) {
  console.error("❌ PR_NUMBER environment variable is required.");
  process.exit(1);
}

console.log(`\n📝 PR Description Generator starting for PR #${prNumber}\n`);

// -----------------------------------------------------------
// STEP 2: Fetch PR details and diff.
// -----------------------------------------------------------
console.log("📖 Fetching PR details...");

const [pr, diff, files] = await Promise.all([
  getPullRequest(prNumber),
  getPullRequestDiff(prNumber),
  getPullRequestFiles(prNumber),
]);

console.log(`   Title: ${pr.title}`);
console.log(`   Current description: ${pr.body ? "exists" : "empty"}`);
console.log(`   Files changed: ${files.length}`);

// -----------------------------------------------------------
// STEP 3: Generate the description using Claude.
//
// We ask Claude to write a Markdown description that follows
// a consistent template. This makes PRs easy to scan.
//
// Unlike the other agents, we ask for plain text (Markdown)
// instead of JSON, since the output IS the description.
// -----------------------------------------------------------
console.log("🤖 Generating PR description...");

const systemPrompt = `You are a technical writer who specializes in writing clear, concise Pull Request descriptions.
Analyze the code diff and generate a professional PR description in Markdown.

RULES:
1. Be concise but thorough — describe WHAT changed and WHY.
2. Group changes logically by area/feature.
3. Highlight breaking changes prominently.
4. Include a testing checklist.
5. Use the exact template format below.
6. Do NOT wrap the output in code fences — return raw Markdown.

TEMPLATE:
## Summary
(1-3 sentences describing the overall change)

## Type of Change
- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Refactoring (no functional changes)
- [ ] Documentation update
- [ ] CI/CD or tooling change

(Check the relevant one)

## Changes Made
(Bullet list of specific changes, grouped by file or area)

## Testing
- [ ] (Suggested test scenarios based on the changes)

## Additional Notes
(Any context, trade-offs, or follow-up work needed)`;

const userMessage = `Generate a PR description for this Pull Request.

## PR #${prNumber}: ${pr.title}
**Author:** ${pr.user.login}
**Branch:** ${pr.head.ref} → ${pr.base.ref}
**Existing description:** ${pr.body || "(empty)"}

## Changed Files:
${files.map((f) => `- ${f.filename} (+${f.additions} -${f.deletions}) — ${f.status}`).join("\n")}

## Diff:
\`\`\`diff
${diff}
\`\`\`

Generate the Markdown description now.`;

const description = await askAI(systemPrompt, userMessage, {
  temperature: 0.3, // Slightly creative for better writing
});

// -----------------------------------------------------------
// STEP 4: Update the PR description on GitHub.
//
// We use the GitHub API to update the PR body.
// We prepend the AI-generated description but keep any
// existing content the author may have written.
// -----------------------------------------------------------
console.log("📝 Updating PR description...");

const { owner, repo } = getRepoInfo();

const finalBody =
  description +
  (pr.body ? `\n\n---\n### Original Description\n${pr.body}` : "") +
  `\n\n---\n🤖 *Description auto-generated by PR Description Agent using Claude AI*`;

await octokit.rest.pulls.update({
  owner,
  repo,
  pull_number: prNumber,
  body: finalBody,
});

// -----------------------------------------------------------
// STEP 5: Auto-label the PR based on the changes.
//
// We add labels based on what files were changed.
// This helps with filtering and routing PRs.
// -----------------------------------------------------------
console.log("🏷️ Auto-labeling PR...");

const autoLabels = ["ai-described"];

// Detect change types from file paths
const filePatterns = {
  "src/": "app-code",
  "test": "has-tests",
  ".github/": "ci-cd",
  "docs/": "documentation",
  "package.json": "dependencies",
};

for (const file of files) {
  for (const [pattern, label] of Object.entries(filePatterns)) {
    if (file.filename.includes(pattern) && !autoLabels.includes(label)) {
      autoLabels.push(label);
    }
  }
}

await addLabels(prNumber, autoLabels);

// -----------------------------------------------------------
// DONE!
// -----------------------------------------------------------
console.log("\n" + "=".repeat(60));
console.log("🎉 PR Description Generator completed!");
console.log("=".repeat(60));
console.log(`   PR:          #${prNumber} — ${pr.title}`);
console.log(`   Labels:      ${autoLabels.join(", ")}`);
console.log(`   Description: Updated with AI-generated content`);
console.log("=".repeat(60) + "\n");
