# Seed data

- `advisories/tanstack-2026-05-11.json`: affected versions and IOCs for the
  May 11, 2026 TanStack compromise, as listed in TanStack's postmortem and
  StepSecurity's table. Re-check upstream before relying on it.
- `repos/`: four **fictional** repos shaped like a real org after that
  advisory. Lockfiles are trimmed to the packages that matter. Every secret
  name is just a name: no values exist anywhere.
- `owners.yml`: GitHub handle → chat handle and team. Change the chat
  handles to the accounts linked in your Switch server before a live run.

| Repo | What it exercises |
|---|---|
| `web-app` | `@tanstack/react-router@1.169.5` installed top-level, the `@tanstack/setup` IOC package, `release.yml` with `NPM_TOKEN` + `id-token: write` |
| `payments-api` | `@tanstack/history@1.161.9` nested under `@tanstack/router-core` (the top-level copy is safe), `deploy.yml` with AWS keys; root `CODEOWNERS` with invalid lines and a later line that wins |
| `docs-site` | affected only as a devDependency, lockfile v1, `pull_request_target` preview workflow (pwn-request shape), `docs/CODEOWNERS` |
| `infra-tools` | clean control case: `pnpm-lock.yaml` v9 with two YAML documents and a near-miss safe version |
