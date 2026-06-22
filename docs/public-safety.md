# Public Safety Rules

This repository is intended to be public.

Never commit:

- credentials, tokens, cookies, API keys, signing keys, service-account files, or auth caches;
- `.env` files or environment dumps;
- local absolute paths containing usernames;
- hostnames, IP addresses, SSH aliases, VPN details, or private network topology;
- client names, private repo names, unreleased product details, or customer data;
- local cache, telemetry, session, prompt-history, browser, or task-state files;
- generated artifacts that may contain private context.

Before pushing, run a content scan for obvious leaks:

```bash
rg -n 'token|secret|password|api[_-]?key|private[_-]?key|BEGIN .*KEY|ssh-rsa|gho_|github_pat|sk-' .
rg -n '/Users/|/home/|\.env|ddns|localhost:[0-9]+|[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' .
```

If a useful workflow depends on private details, document the shape of the workflow and keep the private values in a separate ignored local file or private repository.
