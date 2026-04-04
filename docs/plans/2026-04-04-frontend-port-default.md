# Frontend Port Default Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Change the local frontend dev server to prefer port `5174` instead of `5173`, while preserving Vite's automatic fallback to the next free port and updating user-facing setup docs.

**Architecture:** Keep the current Vite server configuration model and only adjust the default port selection path. Document the new default and the override variable in the README and `.env.example` so quick-start users see the actual behavior before starting the frontend.

**Tech Stack:** Vite, Vue 3, npm, Markdown docs, dotenv-style env examples

---

### Task 1: Update Default Dev Server Port

**Files:**
- Modify: `web/vite.config.ts`

**Step 1: Update the default port**

Change the fallback in `web/vite.config.ts` from `5173` to `5174`.

**Step 2: Preserve automatic fallback behavior**

Do not add `strictPort: true`; Vite should keep choosing the next free port if the preferred one is busy.

**Step 3: Verify configuration shape**

Run: `Get-Content web\\vite.config.ts`

Expected: The config still uses `env.VITE_PORT` when provided and falls back to `5174` otherwise.

### Task 2: Align Docs And Example Env

**Files:**
- Modify: `README.md`
- Modify: `.env.example`

**Step 1: Update quick-start docs**

Change the README frontend URL example from `http://localhost:5173` to `http://localhost:5174`, and note that Vite will automatically pick the next free port if needed.

**Step 2: Add example frontend env vars**

Add `VITE_PORT=5174` and `VITE_API_BASE_URL=http://localhost:8000` to `.env.example` near the local development settings, and expand the CORS example to include `http://localhost:5174`.

**Step 3: Verify references**

Run: `rg -n "5173|5174|VITE_PORT|VITE_API_BASE_URL" README.md .env.example web`

Expected: The new default is documented consistently, and older `5173` references only remain where backward compatibility is intentionally described.

### Task 3: Verify Runtime Behavior

**Files:**
- No file changes

**Step 1: Start the frontend dev server**

Run: `npm run dev -- --host 127.0.0.1`

Expected: Vite reports `http://127.0.0.1:5174/` when that port is free, or the next free port if `5174` is occupied.

**Step 2: Confirm the backend proxy still works**

Run: POST a small JSON payload to `/api/v1/chat` through the started frontend URL.

Expected: The request is proxied to the backend and returns an HTTP response from the API rather than a frontend-side `404`.
