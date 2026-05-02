# Security & quality audit — TheCee (`thecee`)

**Date:** 2026-05-01  
**Scope:** Next.js app (`src/`), FastAPI backend (`app/`), config, WebSocket, auth utilities.

---

## Summary

| Severity | Finding | Status |
|----------|---------|--------|
| **High** | JWT passed in WebSocket URL query string (leaks via logs, Referer, browser history, proxies) | **Fixed:** first-frame JSON auth `{"type":"auth","access_token":"..."}` |
| **High** | `.env.local` / `.env.production` were tracked in git (risk of real secrets + env drift) | **Fixed:** removed from index; remain gitignored locally |
| **High** | Default `SECRET_KEY` usable if production misconfigured | **Fixed:** `Settings` rejects weak/default secrets when `ENVIRONMENT=production` |
| **Medium** | JWT payload base64 decode could fail on unpadded segments | **Fixed:** padding added in `decodePayload` |
| **Medium** | CSP allows `'unsafe-inline'` / `'unsafe-eval'` (Next.js + dev ergonomics tradeoff) | **Documented** — tighten only with nonce/hash strategy if required |
| **Low** | Access/refresh tokens in `localStorage` (XSS → token theft) | **Documented** — acceptable for SPA MVP; httpOnly cookies + CSRF if threat model requires |

---

## Details

### 1. WebSocket authentication (fixed)

**Risk:** Passing `?token=` exposes the bearer token to server access logs, reverse proxies, analytics, and the `Referer` header on subresource requests.

**Change:** Client opens `wss://.../ws/simulation/{id}` with **no** query token; immediately sends  
`{"type":"auth","access_token":"<jwt>"}` then `ping`. Server `accept()`s, reads first text frame, validates, then registers the socket (`skip_accept=True` on manager).

**Files:** `app/api/v1/websocket.py`, `app/core/websocket.py`, `src/lib/websocket.ts`, `app/api/v1/simulations.py` (diagnostic text).

### 2. Environment files in version control (fixed)

**Risk:** Local or staging URLs and any accidental secrets in `.env*` committed to GitHub.

**Change:** `git rm --cached` on tracked `.env.local` / `.env.production`; patterns for iCloud duplicates (`* 2.env*`, etc.) in `.gitignore`.

### 3. Production JWT secret (fixed)

**Risk:** `SECRET_KEY` default (`dev-secret-change-in-prod`) or short placeholders could ship in production.

**Change:** Pydantic `model_validator` on `Settings` — if `ENVIRONMENT` is `production`, require length ≥ 32 and reject known weak strings.

### 4. Client JWT decode robustness (fixed)

**Risk:** `atob` on JWT payload without base64 padding could throw on some tokens.

**Change:** `src/lib/auth.ts` — pad base64url before `atob`.

### 5. Not changed (by design)

- **CSP script-src:** Next.js often needs relaxed script policy; production hardening would use nonces and remove `unsafe-eval` where possible.
- **localStorage tokens:** Moving to httpOnly cookies requires CSRF tokens and same-site tuning — out of scope for this pass.

---

## Verification performed

- `npm run typecheck` (TypeScript) — pass  
- Python modules: syntax validated; full runtime test requires project venv with dependencies installed.

---

## Recommendations (next steps)

1. Run **`pip-audit`** / **`npm audit`** in CI on a schedule.  
2. Add integration test for WebSocket auth handshake (first frame).  
3. If handling regulated data, plan migration from `localStorage` to **httpOnly** session cookies + CSRF protection.
