# Document Copilot frontend

## Local setup

```bash
cd frontend
cp .env.example .env.local
pnpm install
pnpm dev
```

Set these browser-safe values in `.env.local`:

- `VITE_API_BASE_URL`
- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_ANON_KEY`
- `VITE_ALLOWED_EMAIL_DOMAIN`

Never put the Supabase service-role key or database URL in this file.

## Supabase auth

In Supabase, leave Email enabled and add `http://localhost:5173` to **Authentication → URL Configuration → Redirect URLs**. Add the deployed frontend URL there before production.

The app supports password sign-up and sign-in for the configured email domain only. Supabase still controls whether email confirmation is required.

## Checks

```bash
pnpm tsc --noEmit
pnpm lint
pnpm build
```
