# CX Harness Frontend

Next.js App Router foundation for the CX Harness dashboard.

## Development

```bash
cp .env.example .env.local
npm install
npm run dev
```

The frontend API base URL is configured with
`NEXT_PUBLIC_API_BASE_URL`. Dashboard pages and API queries will be added in
later milestones.

## Quality checks

```bash
npm run typecheck
npm run lint
npm run format:check
npm run build
```
