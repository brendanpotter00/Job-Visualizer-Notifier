# Workday API 404 Error - Debugging Document

## Problem Statement

After restructuring the monorepo to move the frontend to `src/frontend/`, all API proxy endpoints are returning 404 errors. Specifically:

```
Request: POST http://localhost:3000/api/workday/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs
Status: 404 Not Found
```

This affects all API routes: `/api/workday/*`, `/api/greenhouse/*`, `/api/lever/*`, `/api/ashby/*`

## Root Cause Analysis

### Before the Restructure (Working State)
- Project structure:
  ```
  /
  ├── api/                    # Serverless functions
  ├── src/                    # Frontend React code
  ├── package.json            # Frontend dependencies
  ├── vercel.json             # Vercel configuration
  └── ...
  ```
- Running `vercel dev` from root would:
  1. Auto-detect the Vite app from root `package.json`
  2. Auto-detect API routes from `api/` directory
  3. Serve both frontend (port 3000) and API routes

### After the Restructure (Broken State)
- Project structure:
  ```
  /
  ├── api/                    # Serverless functions (still at root)
  ├── src/
  │   └── frontend/           # Frontend moved here
  │       ├── package.json    # Frontend dependencies
  │       ├── src/            # React code
  │       └── ...
  ├── vercel.json             # Still at root
  └── ...
  ```
- The `vercel.json` was updated with:
  ```json
  {
    "buildCommand": "cd src/frontend && npm run build",
    "devCommand": "cd src/frontend && npm run dev",
    "installCommand": "cd src/frontend && npm install",
    "outputDirectory": "src/frontend/dist"
  }
  ```

### The Core Issue

**Vercel Dev is NOT detecting or serving the API routes from the `api/` directory.**

When running `vercel dev --yes` from project root, the output shows:
```
Vercel CLI 42.3.0
Retrieving project…
> Running Dev Command "cd src/frontend && npm run dev"
```

**Missing:** No messages about API routes like:
```
λ /api/workday ready [<timestamp>]
λ /api/greenhouse ready [<timestamp>]
```

This indicates Vercel is only running the custom `devCommand` and **bypassing its normal API route detection**.

## Key Findings

### 1. API Directory Structure is Correct
```bash
$ ls api/
ashby.ts
greenhouse.ts
lever.ts
tsconfig.json
workday.ts
```
- All serverless functions exist at the correct location (`/api/`)
- Files are TypeScript with correct exports
- `api/workday.ts` contains valid Vercel serverless function code

### 2. Vercel Configuration Issue
The problem is in `/Users/brendanpotter/Documents/develop/Job-Visualizer-Notifier/vercel.json`:

```json
{
  "devCommand": "cd src/frontend && npm run dev"
}
```

**This custom `devCommand` tells Vercel to ONLY run the specified command and skip its normal initialization process**, which includes:
- Detecting and compiling TypeScript API routes
- Starting serverless function dev servers
- Setting up API route proxying

### 3. Vercel's Normal Behavior
When `devCommand` is **not** specified, Vercel:
1. Scans project structure
2. Detects framework (Vite, Next.js, etc.)
3. Detects API routes in `api/` or `pages/api/`
4. Compiles TypeScript serverless functions
5. Starts dev servers for both frontend and API routes

When `devCommand` **is** specified, Vercel:
1. Runs ONLY that command
2. Skips API route detection/compilation
3. Result: Frontend works, API routes return 404

## What We've Tried

### Attempt 1: Update npm Script ❌
**Action:** Changed `src/frontend/package.json`:
```json
"dev:vercel": "cd ../.. && vercel dev"
```

**Result:** Still 404. The issue isn't WHERE we run vercel from, it's the custom `devCommand` configuration.

### Attempt 2: Remove `devCommand` from vercel.json ❌
**Action:** Removed the `devCommand` line from `vercel.json`

**Result:** Vercel couldn't find `vite` command because it was looking at the root (which has no node_modules with vite).

### Attempt 3: Create Root package.json with Workspaces ❌
**Action:** Created root `package.json` with:
```json
{
  "workspaces": ["src/frontend"]
}
```

**Result:** Npm workspaces didn't hoist vite to root, so Vercel still couldn't find it.

### Attempt 4: Simplified Root package.json ❌
**Action:** Simplified root `package.json` without workspaces:
```json
{
  "scripts": {
    "dev": "cd src/frontend && npm run dev"
  }
}
```

**Result:** Vercel still runs the custom `devCommand` and skips API detection.

## Current State

### Files Modified
1. **`src/frontend/package.json`** (line 9):
   ```json
   "dev:vercel": "cd ../.. && vercel dev"
   ```

2. **`vercel.json`** (lines 3-5):
   ```json
   "buildCommand": "cd src/frontend && npm run build",
   "devCommand": "cd src/frontend && npm run dev",
   "installCommand": "cd src/frontend && npm install",
   "outputDirectory": "src/frontend/dist"
   ```

3. **`package.json`** (root - newly created):
   ```json
   {
     "name": "job-visualizer-notifier-monorepo",
     "scripts": {
       "dev": "cd src/frontend && npm run dev",
       "build": "cd src/frontend && npm run build"
     }
   }
   ```

### Current Behavior
- ✅ Frontend serves on port 3000 (Vite)
- ❌ API routes return 404
- ❌ No API route initialization in Vercel output

## What Still Needs to Be Done

### Option 1: Custom Vercel Dev Script (Recommended)
Since Vercel's `devCommand` bypasses API detection, we need to:

1. **Remove `devCommand` from `vercel.json`** completely
2. **Install frontend dependencies at root** so Vercel can find them:
   ```bash
   # Symlink or copy node_modules
   ln -s src/frontend/node_modules node_modules
   # OR hoist dependencies to root
   ```
3. **Update vercel.json** to point to the right directories without custom commands

### Option 2: Use Vercel's Multi-App Support
Vercel has built-in support for monorepos. Configure it properly:

1. **Use a `vercel.json` at root** that tells Vercel about the structure:
   ```json
   {
     "buildCommand": "cd src/frontend && npm run build",
     "installCommand": "cd src/frontend && npm install",
     "outputDirectory": "src/frontend/dist",
     "functions": {
       "api/**/*.ts": {
         "runtime": "@vercel/node@latest"
       }
     }
   }
   ```
   Note: Removed `devCommand` entirely!

2. **Ensure API routes are explicitly configured** using the `functions` property

### Option 3: Run Two Separate Dev Servers
This is a workaround, not a proper fix:

1. Terminal 1: `cd /path/to/root && vercel dev --listen 3001` (API routes only)
2. Terminal 2: `cd src/frontend && npm run dev` (Frontend only, configure proxy)

This defeats the purpose of Vercel Dev's integration.

## Recommended Next Steps

1. **Try Option 2 first** - Add explicit `functions` configuration to `vercel.json`
2. **Remove the custom `devCommand`** - Let Vercel auto-detect the framework
3. **Create a symlink for node_modules** - Let Vercel find frontend dependencies
4. **Test the fix**:
   ```bash
   cd /Users/brendanpotter/Documents/develop/Job-Visualizer-Notifier
   vercel dev --yes
   # Should see API route initialization messages
   curl -X POST http://localhost:3000/api/workday/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs \
     -H "Content-Type: application/json" \
     -d '{"appliedFacets":{},"limit":1,"offset":0,"searchText":""}'
   # Should return 200, not 404
   ```

## References

- Vercel Dev Documentation: https://vercel.com/docs/cli/dev
- Vercel Monorepo Guide: https://vercel.com/docs/monorepos
- Vercel Serverless Functions: https://vercel.com/docs/functions/serverless-functions

## Status

**Current Status:** 🔴 Blocked - API routes not being served

**Blocker:** Vercel Dev's custom `devCommand` bypasses API route detection

**Priority:** High - Blocks all API functionality including Workday job fetching
