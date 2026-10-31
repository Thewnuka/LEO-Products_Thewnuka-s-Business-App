# Deployment files

Examples only: they contain **no real domains, passwords or keys**. Copy them, then fill in your own values.

| File | Use |
|---|---|
| `env.production.example` | Template for the server's `.env` (production settings, PostgreSQL, HTTPS, email, payments) |
| `linux/gunicorn.service.example` | systemd service running the app with Gunicorn |
| `linux/nginx.conf.example` | Nginx: HTTPS, public product photos, proxy to Gunicorn |
| `windows/start-server.ps1` | Run the production server on a Windows PC with Waitress |

Step-by-step instructions: **DEVELOPMENT_GUIDE.md → "Going live"**.
