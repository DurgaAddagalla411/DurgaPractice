# GitHub Agents — Setup Guide

## Prerequisites

- **Node.js 20+** installed
- **GitHub account** with a repository to test on
- **Groq API key** from [console.groq.com/keys](https://console.groq.com/keys) (free!)

---

## Step 1: Create a GitHub Repository

1. Go to [github.com/new](https://github.com/new)
2. Name it `gitagents` (or anything you like)
3. Make it **public** or **private**
4. Do NOT initialize with README (we'll push our code)

## Step 2: Add Secrets to Your Repository

The agents need API keys to work. GitHub Actions uses **Secrets** to store them securely.

1. Go to your repo → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Add this secret:
   - **Name:** `GROQ_API_KEY`
   - **Value:** Your Groq API key (starts with `gsk_...`)

> **Note:** `GITHUB_TOKEN` is automatically provided by GitHub Actions — you don't need to add it.

## Step 3: Install Dependencies Locally

```bash
cd gitagents
npm install
```

## Step 4: Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit: GitHub Agents for PR automation"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/gitagents.git
git push -u origin main
```

## Step 5: Test Each Agent

### Agent 1: Issue → PR
1. Go to your repo → **Issues** → **New Issue**
2. Title: `Bug: GET /users/:id returns 200 for non-existent users`
3. Body: `When requesting a user that doesn't exist, the API returns 200 with undefined data instead of a 404 error.`
4. Create the "ai-fix" label (Issues → Labels → New Label)
5. Add the "ai-fix" label to your issue
6. Watch the **Actions** tab — a PR will be created!

### Agent 2: AI PR Review
- Opens a PR → review happens automatically

### Agent 3: PR Description
- Opens a PR with empty description → description is generated

### Agent 4: Auto-Merge
- Passes all CI checks on a Dependabot PR → auto-merges

### Agent 5: Stale Cleanup
- Go to **Actions** → **Stale PR Cleanup** → **Run workflow**

---

## Local Testing

To test agents locally without GitHub Actions:

```bash
# Copy and edit environment variables
cp .env.example .env
# Edit .env with your real values

# Test Issue-to-PR Agent
ISSUE_NUMBER=1 node scripts/issue-to-pr.js

# Test PR Review Agent
PR_NUMBER=1 node scripts/pr-reviewer.js

# Test PR Description Generator
PR_NUMBER=1 node scripts/pr-description-generator.js

# Test Auto-Merge Agent
PR_NUMBER=1 node scripts/auto-merge.js

# Test Stale PR Cleanup
node scripts/stale-pr-cleanup.js
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────┐
│                   GITHUB EVENTS                      │
├──────────┬──────────┬──────────┬──────────┬─────────┤
│  Issue   │  PR      │  PR      │  Checks  │  Cron   │
│  Labeled │  Opened  │  Opened  │  Passed  │  Daily  │
│ "ai-fix" │          │          │          │  9am    │
└────┬─────┴────┬─────┴────┬─────┴────┬─────┴────┬────┘
     │          │          │          │          │
     ▼          ▼          ▼          ▼          ▼
┌─────────┐┌─────────┐┌─────────┐┌─────────┐┌─────────┐
│ Agent 1 ││ Agent 2 ││ Agent 3 ││ Agent 4 ││ Agent 5 │
│ Issue→PR││ Review  ││ Describe││ Merge   ││ Stale   │
└────┬────┘└────┬────┘└────┬────┘└────┬────┘└────┬────┘
     │          │          │          │          │
     ▼          ▼          ▼          ▼          ▼
┌─────────────────────────────────────────────────────┐
│          GROQ AI (Llama 3.3 70B / Mixtral)           │
│         Ultra-fast inference on LPU hardware         │
│    Analyzes code, generates fixes, writes reviews    │
└─────────────────────────────────────────────────────┘
     │          │          │          │          │
     ▼          ▼          ▼          ▼          ▼
┌─────────────────────────────────────────────────────┐
│                GITHUB API (Octokit)                  │
│     Creates branches, commits, PRs, comments,        │
│     labels, merges, closes                           │
└─────────────────────────────────────────────────────┘
```
