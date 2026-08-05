# Privacy review before publishing

Apply this review to every public revision of the skill repository.

## Forbidden package content

- personal names or handles
- email addresses, phone numbers, chat IDs or user IDs
- absolute home paths containing a username
- employer, customer, tenant or internal project names
- real profile names that reveal personal domains
- bot usernames, API keys, tokens, OAuth state or credential hashes
- private repository names or URLs
- cron IDs, session IDs, commit IDs from private work or database records
- `.env`, auth files, databases, logs, backups or generated scanner artifacts

## Safe replacements

- machine-specific home paths → `<home>/...` or `$HOME/...`
- profile names → `<profile>`
- container names → `<container>`
- repository names → `owner/repo`
- tokens and fingerprints → `[REDACTED]`
- job identifiers → `<job-id>`

## Required checks

1. List every tracked file.
2. Search source and documentation for known personal terms.
3. Search for absolute home paths.
4. Search for common credential formats and assignment names.
5. Run a dedicated secret scanner when available.
6. Inspect the staged diff manually.
7. Inspect Git history, not only the working tree.
8. Confirm no symlink points outside the repository.
9. Confirm examples use synthetic data.
10. After pushing, inspect the remote tree and clone/install into a clean temporary location.

## Example local commands

```bash
git ls-files
git diff --cached --check
git grep -nE '/Users/[^/]+|/home/[^/]+'
git grep -nEi '(api[_-]?key|token|password|secret)[[:space:]]*[:=][[:space:]]*[^<[]'
gitleaks git . --redact --no-banner
```

Scanner absence is setup debt, not proof of a clean package. At minimum run deterministic pattern checks and manually inspect all tracked text.

## Reporting

Report only:

- scanner used
- files scanned
- number and category of findings
- whether findings were remediated
- remaining uncertainty

Do not reproduce suspected secret values in the report.
