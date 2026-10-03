# Vercel Deployment Guide for Tollgate Dashboard

This guide describes how to deploy the Tollgate Dashboard (`apps/dashboard`) on Vercel while connecting to the live Tollgate Gateway API hosted on Render (`https://tollgate-gateway.onrender.com`).

---

## 1. Deployment Architecture

```text
[ Client Browser ]
        │
        ▼ (HTTPS Same-Origin Requests: /api/v1/...)
[ Vercel Edge Network ]
        │
        ├─► Static Assets (Vite SPA) ──► Cached globally on Vercel CDN
        │
        └─► /api/* (Vercel Rewrite)  ──► https://tollgate-gateway.onrender.com/api/*
                                                 │
                                                 ▼
                                        [ Render FastAPI Gateway ]
                                        - Authentication & RBAC
                                        - Tenant Analytics (/dashboard/*)
                                        - PostgreSQL (pgvector) & Redis
```

### Why Use Same-Origin Vercel Rewrites?
1. **Zero Browser CORS Headaches**: Requests are sent to the same origin (`https://<your-app>.vercel.app/api/v1/...`). Vercel proxies them to Render over HTTPS server-to-server.
2. **Path & Query String Preservation**: The `:path*` wildcard in `apps/dashboard/vercel.json` preserves all query parameters (e.g., `?range=24h&project_id=...`).
3. **Graceful Fallback**: If `VITE_API_BASE_URL` is explicitly configured at build time, the frontend automatically routes directly to that absolute origin.

---

## 2. Vercel Project Configuration

When importing the repository into Vercel, configure the project with the following settings:

| Setting | Value | Notes |
| :--- | :--- | :--- |
| **Framework Preset** | `Vite` | Auto-detected by Vercel |
| **Root Directory** | `apps/dashboard` | **Crucial**: Points Vercel to the frontend sub-app |
| **Build Command** | `npm run build` | Compiles TypeScript and runs `vite build` to `dist/` |
| **Output Directory** | `dist` | Default output directory for Vite |
| **Install Command** | `npm install` | Uses `apps/dashboard/package.json` |

---

## 3. Environment Variables

### Recommended (Vercel Rewrite Mode)
No build-time environment variables are strictly required because `apps/dashboard/vercel.json` proxies all `/api/*` calls directly to `https://tollgate-gateway.onrender.com/api/*`.

### Optional (Direct Browser-to-Gateway Mode)
If you prefer direct browser-to-Render communication without proxying through Vercel's edge network:

| Variable Name | Required? | Example Value | Description |
| :--- | :---: | :--- | :--- |
| `VITE_API_BASE_URL` | Optional | `https://tollgate-gateway.onrender.com` | Overrides relative `/api/v1` and routes requests directly to the Render origin. |

---

## 4. Render Gateway Security & CORS Configuration

If requests are routed **directly** from the browser to Render using `VITE_API_BASE_URL`, the Render gateway's CORS policy must authorize the Vercel domain.

On the Render Dashboard for `tollgate-gateway`:
1. Navigate to **Environment Variables**.
2. Set `TOLLGATE_CORS_ALLOWED_ORIGINS` to include your Vercel deployment URL:
   ```text
   TOLLGATE_CORS_ALLOWED_ORIGINS=https://<your-app>.vercel.app,https://app.tollgate.ai
   ```
3. *Note*: When using the default **Vercel Rewrite Mode**, requests originate from Vercel's edge proxy, eliminating cross-origin browser restrictions.

---

## 5. Local Development vs. Production

- **Local Development (`npm run dev`)**:
  - Vite dev server runs on `http://localhost:3000`.
  - In `vite.config.ts`, local requests to `/api` are proxied to `process.env.VITE_API_BASE_URL || 'http://localhost:8000'`.
- **Production (Vercel)**:
  - Static bundle is served from Vercel CDN.
  - Client calls `buildApiUrl(endpoint)` which resolves to `/api/v1/...` (or `VITE_API_BASE_URL` if set).
  - Vercel rewrites forward `/api/*` to `https://tollgate-gateway.onrender.com/api/*`.
