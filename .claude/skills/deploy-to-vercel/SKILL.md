---
name: deploy-to-vercel
description: |
  Trigger an on-demand Vercel PREVIEW deployment for the current PR branch.
  Automatic per-PR preview deploys are turned OFF in vercel.json
  (git.deploymentEnabled), so PRs no longer auto-deploy. This skill is the
  manual replacement: it kicks a git-source deployment through the Vercel REST
  API so the real Vercel GitHub App posts its native preview comment on the
  open PR — the same comment you used to get automatically, but only when you
  ask for it. Use when the user says "deploy to vercel", "deploy to vercel
  temporarily", "deploy this PR to vercel", or "spin up a preview".
trigger_phrases:
  - deploy to vercel
  - deploy to vercel temporarily
  - deploy this to vercel
  - deploy this pr to vercel
  - deploy the branch to vercel
  - spin up a vercel preview
  - vercel preview deploy
required_tools:
  - Bash
mode: read-write
---

# Deploy to Vercel (on demand)

## What this does and why it exists

Per-PR preview deploys are **disabled** for this project. The root `vercel.json`
contains:

```jsonc
"git": {
  "deploymentEnabled": {
    "main": true,   // production still auto-deploys on merge to main
    "**": false     // every other branch: NO automatic deploy (incl. feat/*, fix/*)
  }
}
```

So opening or pushing a PR no longer spins up a preview or drops the Vercel bot
comment. **This skill is the on-demand replacement.** When the user says
*"deploy to vercel"* (or *"deploy to vercel temporarily"* — same thing; every
preview is ephemeral), run a single git-source deployment through the Vercel
REST API. Because Vercel builds it from the branch commit on GitHub, the Vercel
GitHub App posts its native preview comment on the open PR — exactly the comment
that used to appear automatically.

`"deploy to vercel"` and `"deploy to vercel temporarily"` are synonyms here:
both produce a **preview** deployment of the current branch. They do **not**
mean production. (Production still auto-deploys when you merge to `main`; only
pass `--prod` to the script in the rare case the user explicitly asks to ship
production manually.)

## Prerequisite (one-time): a Vercel token

A git-source API deploy needs a Vercel access token. If `VERCEL_TOKEN` is not in
the environment and not in repo `.env.local`, the script stops with instructions.
To set it up: create a token at <https://vercel.com/account/tokens> for the
`brendanpotter00s-projects` team, then either `export VERCEL_TOKEN=…` or add
`VERCEL_TOKEN=…` to `.env.local` (already git-ignored).

## Steps

1. **Confirm context.** Make sure the user is on the feature branch they want to
   preview (`git rev-parse --abbrev-ref HEAD`) and that an open PR exists for it
   (`gh pr view --json number,url`). The bot comment only lands if there's an
   open PR for the branch — if there's none, the deploy still works but tell the
   user no PR comment will appear.

2. **Run the deploy script** from the repo root:

   ```bash
   bash .claude/skills/deploy-to-vercel/scripts/deploy_preview.sh
   ```

   The script: resolves the token → pushes the current branch to origin (Vercel
   builds the commit on GitHub, so HEAD must be pushed) → POSTs a preview
   git-source deployment to `https://api.vercel.com/v13/deployments` → prints the
   deployment id, preview URL, and inspector URL.

   Note: it deploys the **latest committed & pushed commit** of the branch.
   Uncommitted local changes are not included (that is inherent to git-source
   deploys; it is what lets the real bot comment appear).

3. **Report back.** Give the user the preview URL + inspector URL from the script
   output, and tell them the Vercel GitHub App will post/update the preview
   comment on the PR once the build reaches READY (usually a minute or two).

4. *(Optional)* If they want to watch it finish, poll with the Vercel MCP
   `get_deployment` tool using the printed deployment id, or
   `gh pr view <n> --json comments` to confirm the Vercel comment appeared.

## Project constants (already baked into the script)

| Thing | Value |
|-------|-------|
| Vercel team id | `team_k1U3D3dnN1fV5XnqAzCUg0MF` |
| Vercel project | `job-visualizer-notifier` (`prj_7moC3xZ9H5vKmEkGb0ROXMARzmtT`) |
| GitHub repo id | `1097855088` (`brendanpotter00/Job-Visualizer-Notifier`) |

## Production (rare)

Only if the user *explicitly* asks to push production by hand:

```bash
bash .claude/skills/deploy-to-vercel/scripts/deploy_preview.sh --prod
```

Normally you never need this — merging to `main` auto-deploys production.
