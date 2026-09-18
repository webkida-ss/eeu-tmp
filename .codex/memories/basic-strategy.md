## Language

**This project is English-first. All code, comments, and documents must be written in English.**

Use English for all documents and code comments. Even if instructions or notes are given in Japanese, write documents in English. Chat responses can be in Japanese.

## Development Approach

Fix the frontend experience first, then progressively integrate the backend.

Use the repository pattern and inject the infrastructure layer via DI.

1. Verify behavior quickly using local JSON files for reads and in-memory storage for writes — no API calls yet.
2. Define the API contract and connect to mocks.
3. Replace mocks with the real API.

## Schema-Driven Development

Use a single API schema as the source of truth for API contracts.

Generate every artifact that can reasonably be generated from the schema, including backend server code, API component types, frontend API clients, and client services used by microservices.

Do not hand-write code that should be derived from the schema unless there is a clear project constraint that prevents generation.

## Implementation Style

Break implementation into small units. Explain each step and wait for approval before proceeding. Only move ahead continuously if explicitly told to do so (e.g. "go ahead" or "implement all of this").

## Default Tech Stack

- **Frontend**: Next.js (preferred) / Nuxt.js — TypeScript / Tailwind CSS / pnpm
- **Backend**: Rust + Axum (preferred) / Go + Echo
- **Infrastructure**: AWS (all-in)
- **Auth**: Google OAuth
