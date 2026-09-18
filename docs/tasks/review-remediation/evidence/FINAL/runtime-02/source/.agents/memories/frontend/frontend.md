# Frontend Common Rules

## Language

- TypeScript only — no plain JavaScript files

## Styling

- Tailwind CSS only — no inline styles, no CSS modules

## Package Manager

- pnpm only

## API Client

- Generate API client code from the OpenAPI definition. Do not handwrite API clients.

## Component Rules

- Named exports only (except Next.js `page.tsx` / `layout.tsx` which require default export)
- One component per file

## Documentation

- When adding, removing, or changing frontend pages, update the Pages table in `docs/FRONTEND.md`
