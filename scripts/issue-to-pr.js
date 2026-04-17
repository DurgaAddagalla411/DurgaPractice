// ============================================================
// AGENT 1: ISSUE-TO-PR AGENT (The Star of the Show)
// ============================================================
//
// WHAT THIS DOES:
// Reads a GitHub issue, uses Claude AI to understand the bug or
// feature request, generates the code fix, and automatically
// creates a Pull Request with the changes.
//
// THE FULL FLOW:
//   1. Triggered when a GitHub issue gets labeled "ai-fix"
//   2. Reads the issue title and body to understand the problem
//   3. Reads the relevant source code from the repository
//   4. Sends everything to Claude with a prompt like:
//      "Here's the bug report and the code. Generate a fix."
//   5. Claude analyzes the issue and produces corrected code
//   6. Agent creates a new branch: "ai-fix/issue-{number}"
//   7. Commits the AI-generated code to that branch
//   8. Opens a Pull Request linking back to the original issue
//   9. Posts a comment on the issue saying "PR created!"
//
// HOW TO TRIGGER:
//   - Automatically: Add the "ai-fix" label to any issue
//   - Manually: ISSUE_NUMBER=42 node scripts/issue-to-pr.js
//
// ENVIRONMENT VARIABLES NEEDED:
//   - GITHUB_TOKEN        — GitHub access token
//   - GITHUB_REPOSITORY   — "owner/repo"
//   - ANTHROPIC_API_KEY   — Claude API key
//   - ISSUE_NUMBER        — The issue to process
// ============================================================

import { askAIJSON } from "./lib/ai-client.js";
import {
  getIssue,
  getFileContent,
  listFiles,
  createBranch,
  createOrUpdateFile,
  createPullRequest,
  addComment,
  addLabels,
} from "./lib/github-client.js";

// -----------------------------------------------------------
// STEP 1: Parse the issue number from environment.
//
// When triggered by GitHub Actions, the workflow YAML passes
// the issue number as an environment variable.
// When testing locally, you set it manually: ISSUE_NUMBER=42
// -----------------------------------------------------------
const issueNumber = parseInt(process.env.ISSUE_NUMBER);

if (!issueNumber) {
  console.error("❌ ISSUE_NUMBER environment variable is required.");
  console.error("   Usage: ISSUE_NUMBER=42 node scripts/issue-to-pr.js");
  process.exit(1);
}

console.log(`\n🚀 Issue-to-PR Agent starting for issue #${issueNumber}\n`);

// -----------------------------------------------------------
// STEP 2: Fetch the issue details from GitHub.
//
// We need the title and body to understand what the user
// is reporting (bug, feature request, etc.)
// -----------------------------------------------------------
console.log("📖 Reading issue details...");
const issue = await getIssue(issueNumber);

console.log(`   Title: ${issue.title}`);
console.log(`   Labels: ${issue.labels.map((l) => l.name).join(", ") || "none"}`);

// -----------------------------------------------------------
// STEP 3: Read the repository's source code.
//
// The AI needs to see the current code to generate a fix.
// We read all files in the src/ directory and combine them
// into a single context string.
//
// WHY: Claude needs the full picture to understand the
// codebase structure and produce code that fits in.
// -----------------------------------------------------------
console.log("📂 Reading repository source code...");

// List all files in src/ directory
const sourceFiles = await listFiles("src");

// Read the content of each source file
let codeContext = "";
for (const file of sourceFiles) {
  if (file.type === "file") {
    try {
      const content = await getFileContent(file.path);
      codeContext += `\n--- FILE: ${file.path} ---\n${content}\n`;
    } catch (error) {
      console.log(`   ⚠️ Could not read ${file.path}: ${error.message}`);
    }
  }
}

console.log(`   Read ${sourceFiles.filter((f) => f.type === "file").length} source files`);

// -----------------------------------------------------------
// STEP 4: Ask Claude to analyze the issue and generate a fix.
//
// We send Claude:
//   - A system prompt explaining its role
//   - The issue details (title + body)
//   - The full source code
//   - Instructions to return structured JSON with the fix
//
// Claude returns a JSON object with:
//   {
//     "analysis": "What the issue is about...",
//     "changes": [
//       {
//         "file": "src/app.js",
//         "content": "...the corrected file content...",
//         "description": "What was changed and why"
//       }
//     ],
//     "pr_title": "Short title for the PR",
//     "pr_body": "Detailed PR description in Markdown"
//   }
// -----------------------------------------------------------
console.log("🤖 Asking Claude to analyze and generate fix...");

// SYSTEM PROMPT — Defines Claude's role and behavior
const systemPrompt = `You are an expert software engineer acting as an automated GitHub coding agent.
Your job is to read a GitHub issue (bug report or feature request) and the existing source code,
then produce a complete, working fix.

RULES:
1. Return ONLY valid JSON — no markdown, no explanation outside JSON.
2. Include the COMPLETE file content for any file you modify (not just the diff).
3. Make minimal, focused changes — don't refactor unrelated code.
4. Add clear code comments explaining what you changed and why.
5. Ensure the fix actually addresses the issue described.
6. Write production-quality code with proper error handling.

RESPONSE FORMAT (strict JSON):
{
  "analysis": "Brief explanation of what the issue is and your approach to fixing it",
  "changes": [
    {
      "file": "path/to/file.js",
      "content": "...complete corrected file content...",
      "description": "What was changed in this file and why"
    }
  ],
  "pr_title": "fix: Short description (under 70 chars)",
  "pr_body": "## Summary\\nWhat this PR does...\\n\\n## Changes\\n- Change 1\\n- Change 2\\n\\n## Linked Issue\\nCloses #ISSUE_NUMBER"
}`;

// USER MESSAGE — The actual task with issue + code context
const userMessage = `Please analyze this GitHub issue and generate a fix.

## GitHub Issue #${issueNumber}
**Title:** ${issue.title}
**Body:**
${issue.body || "(no description provided)"}
**Labels:** ${issue.labels.map((l) => l.name).join(", ") || "none"}

## Current Source Code
${codeContext}

Generate the fix as JSON. Make sure pr_body references "Closes #${issueNumber}".`;

// Call Claude and get structured response
const aiResponse = await askAIJSON(systemPrompt, userMessage);

console.log(`\n📋 AI Analysis: ${aiResponse.analysis}\n`);
console.log(`   Files to change: ${aiResponse.changes.length}`);
aiResponse.changes.forEach((change) => {
  console.log(`   - ${change.file}: ${change.description}`);
});

// -----------------------------------------------------------
// STEP 5: Create a new branch for the fix.
//
// Branch naming convention: ai-fix/issue-{number}
// This makes it easy to identify AI-generated branches.
//
// The branch is created from the repo's default branch (main).
// -----------------------------------------------------------
const branchName = `ai-fix/issue-${issueNumber}`;
console.log(`\n🌿 Creating branch: ${branchName}`);

try {
  await createBranch(branchName);
} catch (error) {
  if (error.status === 422) {
    // Branch already exists — likely a retry. That's okay.
    console.log(`   ⚠️ Branch already exists, will update it.`);
  } else {
    throw error;
  }
}

// -----------------------------------------------------------
// STEP 6: Commit the AI-generated code changes.
//
// For each file that Claude modified, we commit the new
// content to our branch using the GitHub Contents API.
//
// This is equivalent to:
//   git checkout ai-fix/issue-42
//   echo "new content" > src/app.js
//   git add src/app.js
//   git commit -m "fix: description"
// -----------------------------------------------------------
console.log("📝 Committing AI-generated changes...");

for (const change of aiResponse.changes) {
  await createOrUpdateFile(
    branchName,
    change.file,
    change.content,
    `fix(#${issueNumber}): ${change.description}`
  );
}

// -----------------------------------------------------------
// STEP 7: Create the Pull Request.
//
// The PR:
// - Has an AI-generated title and description
// - Links back to the original issue (Closes #N)
// - Targets the default branch (main)
// - Comes from our ai-fix branch
// -----------------------------------------------------------
console.log("🔀 Creating Pull Request...");

const pr = await createPullRequest({
  title: aiResponse.pr_title,
  body:
    aiResponse.pr_body +
    "\n\n---\n🤖 *This PR was automatically generated by the Issue-to-PR Agent using Claude AI.*",
  head: branchName,
});

// -----------------------------------------------------------
// STEP 8: Add labels and comment on the original issue.
//
// This closes the loop — the person who filed the issue gets
// a notification that an AI has created a fix for them.
// -----------------------------------------------------------
console.log("🏷️ Adding labels...");
await addLabels(pr.number, ["ai-generated", "automated-pr"]);

console.log("💬 Commenting on the original issue...");
await addComment(
  issueNumber,
  `🤖 **AI Agent Update**\n\n` +
    `I've analyzed this issue and created a fix:\n\n` +
    `**Pull Request:** #${pr.number}\n` +
    `**Branch:** \`${branchName}\`\n\n` +
    `**What I changed:**\n` +
    aiResponse.changes
      .map((c) => `- \`${c.file}\`: ${c.description}`)
      .join("\n") +
    `\n\n` +
    `Please review the PR and let me know if any adjustments are needed.`
);

// -----------------------------------------------------------
// DONE! Print a summary.
// -----------------------------------------------------------
console.log("\n" + "=".repeat(60));
console.log("🎉 Issue-to-PR Agent completed successfully!");
console.log("=".repeat(60));
console.log(`   Issue:   #${issueNumber} — ${issue.title}`);
console.log(`   Branch:  ${branchName}`);
console.log(`   PR:      #${pr.number} — ${pr.html_url}`);
console.log("=".repeat(60) + "\n");
