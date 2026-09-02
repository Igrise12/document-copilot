# Frontend setup

This project uses a Vite + React SPA because the frontend is an internal tool that mainly needs fast iteration, authenticated app flows, and a clean connection to the FastAPI backend. We do not need the extra server-rendering, SEO, or full-stack routing features that Next.js is optimized for.

## Configure and run

```bash
cd frontend
cp .env.example .env.local
pnpm install
pnpm dev
```

Set `VITE_API_BASE_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, and `VITE_ALLOWED_EMAIL_DOMAIN` in `.env.local`. These are browser-visible values; never add the service-role key or database URL.

In Supabase, add `http://localhost:5173` to **Authentication → URL Configuration → Redirect URLs**. Add the deployed frontend URL there before production.

## Check

```bash
pnpm tsc --noEmit
pnpm lint
```
