# BiasRadar Football frontend

Next.js App Router frontend for the BiasRadar Football controversy-analysis
experience. The scaffold uses TypeScript, Tailwind CSS, ESLint, and Motion.

## Getting Started

Copy the public environment example and start FastAPI and Next.js in separate
terminals:

```bash
cp .env.example .env.local
```

From the repository root:

```bash
uv run biasradar-api
```

From `frontend/`:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000). The API defaults to
`http://127.0.0.1:8000` and can be changed with
`NEXT_PUBLIC_BIASRADAR_API_URL`.

The first fixture-backed animated report is available at:

```text
http://localhost:3000/topics/demo
```

Never place a Supabase secret key in this frontend or in a `NEXT_PUBLIC_*`
variable. Browser requests go through the allow-listed FastAPI contract.

The report route uses TypeScript contracts matching the FastAPI overview, incident,
narrative, and timeline responses. Its fixture is intentionally isolated in
`src/lib/fixtures` so live API fetching can replace it without changing the visual
components.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
