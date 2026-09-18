# Frontend

## Pages

| Path | Page | Status | Description |
| --- | --- | --- | --- |
| `/` | Landing page | Implemented | Public top page for the personalized learning concept and sign-in entry point. |
| `/login` | Login page | TBD | Google sign-in entry page if a dedicated login route is needed. |
| `/dashboard` | Dashboard | TBD | Authenticated home page after sign-in. |

## Rendering Model

The frontend is designed as a SPA-first application.

| Topic | Decision |
| --- | --- |
| Rendering | Prefer static files and client-side rendering. |
| Data loading | Fetch learning and user data from backend APIs. |
| Server runtime | Do not require a frontend server runtime for the MVP. |
| SSR | Treat SSR as a future option only when there is a clear need such as public SEO pages, dynamic OGP, or server-side session rendering. |
