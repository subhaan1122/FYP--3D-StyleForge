# StyleForge Frontend

React + Vite frontend for the StyleForge virtual try-on and 3D avatar system.

## Quick Start

```bash
npm install
npm run dev      # Starts on http://localhost:5002
```

The dev server proxies `/api` requests to the backend at `http://localhost:5000`.

## Structure

- `src/pages/` — Home and TryOn pages
- `src/components/` — Reusable UI components (upload, viewer, layout)
- `src/api/` — Axios client and API functions
- `src/hooks/` — Custom hooks (file upload, polling)
- `src/styles/` — CSS variables, global styles, component styles
