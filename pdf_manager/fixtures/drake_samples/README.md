# Drake sample PDFs (local only)

Place representative Drake client packets here for parser development and corpus audits.

**Do not commit PDF files** — they may contain taxpayer PII. Only this README and `manifest.yaml` belong in git.

## Run corpus audit

From repo root (Docker stack running):

```bash
docker compose build pdf_web && docker compose up -d pdf_web
docker compose run --rm -T pdf_web python manage.py audit_drake_corpus
```

Report is written inside the container to `/home/app/data/reports/corpus_audit.json` (writable by the app user).

To save the report on your Mac as well:

```bash
docker compose run --rm -T \
  -v "$(pwd)/pdf_manager/fixtures:/app/fixtures" \
  pdf_web \
  python manage.py audit_drake_corpus \
    --output fixtures/drake_samples_reports/corpus_audit.json
```

Or copy it out after a run:

```bash
docker compose run --rm -T pdf_web python manage.py audit_drake_corpus
docker cp "$(docker compose ps -q pdf_web):/home/app/data/reports/corpus_audit.json" \
  pdf_manager/fixtures/drake_samples_reports/corpus_audit.json
```

Fast structural-only pass (no full parse):

```bash
python manage.py audit_drake_corpus --no-parse
```

## Manifest & outline registry

| File | Purpose |
|------|---------|
| `manifest.yaml` | Structural tags per sample (committed; no PII) |
| `outline_registry.yaml` | Drake bookmark → role mapping for parser rebuild (schema v1) |

Re-run the corpus audit after adding samples so `corpus_audit.json` stays current.
