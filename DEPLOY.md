# Dokploy deployment

This follows Octo Flow's Dokploy layout: one Compose application, separate public web and API domains, and an external PostgreSQL database.

## Configure Dokploy

1. Create a PostgreSQL database reachable from the Dokploy server.
2. Create a **Docker Compose** application from this repository and select `compose.dokploy.yml` as the Compose file.
3. Add these variables in the application's **Environment** tab:

   ```env
   DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require
   UPDATER_TOKEN=replace-with-a-long-random-secret
   CORS_ORIGINS=https://app.example.com
   VITE_API_BASE_URL=https://api.example.com
   UPDATER_API_URL=https://api.example.com
   MCP_ALLOWED_HOSTS=api.example.com
   # Optional: enables AI-generated answers
   OPENROUTER_API_KEY=
   LLM_MODEL=google/gemini-3.5-flash-lite
   ```

4. Attach `app.example.com` to the `web` service on container port **80**, and `api.example.com` to the `api` service on container port **8000**. Enable HTTPS for both domains. Replace the example origins above with these exact public origins (no trailing slash). `MCP_ALLOWED_HOSTS` must contain the public API hostname (bare hostname is enough — the server also accepts any port on it), otherwise every `POST /mcp` through Cloudflare/Dokploy is rejected with `421 Invalid Host header` before any MCP logic runs. `UPDATER_API_URL` is a fallback for the same check.
5. Deploy the stack. The API creates its tables on startup; it needs a database user allowed to create tables. If `MCP_ALLOWED_HOSTS` was missing on a previous deploy, redeploy after setting it — reloading the MCP client alone cannot fix a `421`.

`VITE_API_BASE_URL` is baked into the frontend at build time. Redeploy the stack after changing it. Keep `DATABASE_URL`, `UPDATER_TOKEN`, and `OPENROUTER_API_KEY` in Dokploy, outside Git. The browser prompts for `UPDATER_TOKEN`; local MCP clients use the same token with `UPDATER_API_URL=https://api.example.com`.

## Verify

```bash
curl -f https://api.example.com/api/health
curl -f https://app.example.com/healthz
```

Open the web domain, enter the configured token, and confirm the updates view loads. The health endpoint checks that the API process is serving requests; it does not check PostgreSQL connectivity.
