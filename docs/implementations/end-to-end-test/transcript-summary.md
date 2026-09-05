# Transcript summary — Lauren Tan on trusting coding agents (Dune / Grokbot)

Lauren Tan (Cursor; ex-Meta React core team; ex-Netflix TL/EM) gives a ~60-minute talk + Q&A on how she built up trust in AI coding agents at Cursor, culminating in a strict internal architecture ("Dune") that let her automerge PRs and let non-engineers ship features in Grokbot.

## TL;DR

- **Trust, not code quality, is the real bottleneck** — without trust you're stuck micromanaging agents one at a time; with it you can automerge dozens of PRs unreviewed.
- **Verification is the single most important agent skill** — an agent that can actually run/test/trace the app (not just guess) closes the loop and stops hallucinated "smoking gun" fixes.
- **A "feature map" file teaches agents how to navigate the app UI**, turning vague bug reports/screenshots into actionable investigations.
- **Evals are unit tests for skills** — sub-agents run in disguised directories (so they don't know they're being tested) and get hill-climbed with `/loop` until scores are high, cross-checked by a different-model judge agent to avoid bias.
- **Cloud agents pay off once trust is established locally** — e.g. "Benny," an agent that reproduces bug reports autonomously in the cloud and confirms fixes.
- **Greenfield/vibe-coded apps are the biggest risk** — with no guardrails, agents optimize for shortcuts and the codebase spirals into "organic architecture."
- **Dune is Lauren's strict, CI-enforced architecture for Grokbot** (600+ PRs to build) — banned `useEffect`, banned code comments, and hard import/dependency boundaries (e.g. Electron main vs. renderer).
- **"The shortest path is the best path"** — design conventions so the laziest/shortcut way an agent would code something is also the correct way.
- **Enforcement should be layered, hardest-first**: architecture/directory conventions > CI/static analysis/compiler > rules/skills/bugbot (soft, easily forgotten).
- **Any human code-review comment should become a hard rule/lint/CI check** — repeatedly explaining the same thing in review is treated as a code smell.

## Timestamp map

| Time | Topic | Key points |
|---|---|---|
| **[0:00]** | Intro — speaker background | Cursor (~5 months), ex-Meta React core team (React compiler), ex-Netflix tech lead → EM |
| **[2:22]** | Talk framing + the "trust curve" | Core question: how do you trust agents; draws a curve of trust-in-agents vs. time; losing trust → micromanagement mode |
| **[5:26]** | Current state: automerging PRs | Agents automerge PRs for her; woke up to ~20 landed PRs already reviewed on main; ~1,000 PRs shipped last month |
| **[7:48]** | Verification = the #1 skill | Agent must actually run code, take CPU traces/heap snapshots, drive a simulator — "closes the loop"; doesn't guarantee good code but enables correct code |
| **[8:34]** | Origin story: Agent Window ("Glass") perf work | Week-1 story: manually reading Chrome DevTools traces; agent had no idea what it was looking at; human was the bottleneck/verifier |
| **[11:37]** | Control skills + the "feature map" | Skill teaches agent to drive the app via Chrome DevTools Protocol / Apple simulator tools; feature map file lets agent navigate to any feature from a vague bug report or screenshot |
| **[15:28]** | What Pstack is | Lauren's plugin (riff on Gary Tan's "Gstack" / Y Combinator); built incrementally, not designed upfront — grew from observed agent failure modes |
| **[19:20]** | Maintaining skills via evals | Eval = "unit test for an agent"; Pstack ships an "eval playbook" under potato mode; coordinator spawns sub-agents in disguised directory names so they don't know they're being evaluated |
| **[22:25]** | Hill-climbing evals / judge-agent bias check | Eval produces a score; can hill-climb with `/loop` until e.g. 10/10; separate judge-agent (different model) cross-checks for bias |
| **[24:43]** | Chef/kitchen analogy + local-to-cloud progression | Engineer as head chef designing the environment, not cooking everything; recommends starting local to observe agents, then moving to cloud agents (e.g. "Benny," which reproduces bug reports autonomously) |
| **[30:07]** | Recap of the trust journey | Verification skills → local trust → cloud scaling → automerge; no shortcut, it's personal trust-building |
| **[32:25]** | Rewrite/refactor debate | Should you rewrite an app? Brownfield apps with existing guardrails/conventions are often fine for agents; big-tech infra already caters to "least capable engineer" |
| **[33:58]** | Greenfield risk — "organic architecture" | Vibe-coded apps (like early Grokbot) have no guardrails; agents take shortcuts; codebase spirals out of human understanding |
| **[37:04]** | The Dune refactor | 600+ PRs to refactor Grokbot onto Dune; Lauren says she no longer reads the code; benefits designers/PMs/GTM who can now contribute |
| **[38:34]** | Q&A: PR size & CI overview | No hard PR-size cap (ranges ~50–1,000+ lines), but agents encouraged to split work into atomic PRs for git-history/revert clarity; Grokbot/Cursor virtualization powered by "pretext" library |
| **[40:51]** | Dune specifics — banned patterns | Dune described as "like Next.js for Electron apps," designed for agents to write; `useEffect` banned (CI fails); code comments banned (agents write irrelevant/stale historical comments) |
| **[43:08]** | Electron process isolation enforced by CI | Renderer vs. main-thread separation; literal `electron-main`/`electron-renderer` directories with import/dependency-graph CI checks to prevent accidental cross-imports causing jank |
| **[45:27]** | Layers of enforcement + Dune "nouns" | Architecture/directory conventions (strongest — Feature, Entrypoints, Transcript cards as collocated single-directory "nouns") > CI/lints/compiler diagnostics > rules/skills/bugbot (soft, agents can forget) |
| **[46:59]** | "Shortest path is the best path" | Core design principle: since agents default to the shortcut, make the shortcut the correct/conventional way to build a feature |
| **[48:32]** | Code review as anti-pattern | Repeatedly explaining a rule in code review = code smell; convert it into a lint rule / CI failure / architectural elimination instead of relying on human review |
| **[50:50]** | Q&A: token cost & ROI | Acknowledges she works at an AI lab with "unlimited tokens"; frames investment as ROI — upfront refactor cost vs. staying lean instead of hiring a large eng org |
| **[53:58]** | Grok 4.6 announcement | Announced same day as the talk; same cost per token as 4.5 but more capable; framed as Cursor/xAI optimizing the cost-vs-intelligence frontier |
| **[55:33]** | Team-wide payoff | "An army of engineers" shipping improvements/bug fixes daily as the payoff of the investment |
| **[56:20]** | Q&A: product/GTM teams & Grokbot UX | Grokbot described as an accessible, iMessage-like interface for non-engineers (PMs, designers, GTM); PMs now ship code/PRs themselves; cited as evidence Dune's constraints hold up |
| **[58:36]** | Wrap-up | Thanks, pointer to DM Lauren on Twitter (potato/potatoe) for more questions, possible future Twitter Space |

## Key concepts — Dune

- **What Dune is**: the internal code name for Grokbot's architecture — described as analogous to "Next.js for Electron apps," purpose-built for agents to write code against. **[40:51]**
- **Public "nouns" / conventions**: Feature (all code for a feature collocated in one directory), Entrypoints, and Transcript cards (the chat-card UI elements) are the framework's named building blocks with a conventional way to create each. Note: the transcript does not mention a "Client" or "Host" noun explicitly — only Feature, Entrypoints, and Transcript cards are named. **[45:27]–[46:13]**
- **"Shortest path is the best path"**: the guiding design principle — since agents gravitate to the quickest/shortcut solution, the framework is built so that shortcut is also the correct, sanctioned way to do the work. **[46:59]**
- **Banned `useEffect`**: called out as one of React's biggest foot-guns; CI fails if it's used in Dune/Grokbot code. **[40:51]**
- **Banned code comments**: agents were found to write comments describing irrelevant historical context (e.g. misattributed one-off review feedback as a "durable global rule"), so comments are banned outright in CI. **[41:36]–[42:23]**
- **CI-enforced import/dependency boundaries**: literal `electron-main` / `electron-renderer` directories with CI checks on the dependency graph, to stop performance-sensitive renderer-thread code from accidentally importing heavy/blocking code. **[43:08]–[44:40]**
- **Layered enforcement (hard → soft)**: (1) codebase/architecture conventions — strongest, because agents copy existing patterns; (2) static analysis — CI checks, lints, compiler diagnostics (makes CI fail, i.e. hard); (3) rules, skills, and "bugbot" (Cursor's CI code-review tool) — softer, since agents can forget or inconsistently apply them. Lauren explicitly says she doesn't rely on the soft layer alone. **[45:27]–[48:32]**
- **Code review → hard rule conversion**: whenever a human has to repeatedly explain the same thing in code review, that's treated as a code smell — the fix is to turn it into a lint rule, a CI failure, or eliminate the problem category entirely (rather than keep relying on human review). **[50:04]**

## Notable quotes

*(Captions are auto-generated/approximate — punctuation and exact wording may be off.)*

- **[5:26]** "I actually have my agents now automerging PRs for me... I woke up today and there were like 20 PRs landed and I just reviewed them on main[e] — they were already landed and they were good."
- **[33:58]** "Before AI slop, we had human slop."
- **[37:04]** "I don't really look at the code anymore... I spent a lot of tokens to get the codebase to this point where I no longer have to look at it."
- **[46:59]** "The shortest path is the best path" — because that's exactly how agents love to write code: they take shortcuts, so make the shortcut the best way to solve the problem.
- **[48:32]** "If you only have rules and bugbot and skills and a style guide for your code, ... it's only a matter of time before your code base looks like complete trash."
- **[50:04]** "Every time you have to [comment on a PR], you should consider that as a code smell... how do I turn this into a hard rule? ... How do I even categorically eliminate this problem entirely?"
