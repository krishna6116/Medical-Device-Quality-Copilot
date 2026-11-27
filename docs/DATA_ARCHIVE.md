# Data archive

The downloaded openFDA files and the search embeddings are not in git (see `.gitignore`). On 2026-11-26 they were archived as a GitHub release so the exact snapshot behind the published results survives after openFDA updates its data, and the local copies were deleted to free space.

- Release: [data-2026-11](https://github.com/krishna6116/Medical-Device-Quality-Copilot/releases/tag/data-2026-11)
- Archive: `mdqc_data_2026-11.tar.gz` (about 460 MB), sha256 `1053d01db9d9ff44af1b1200c1451b7cdd3e1802d52dd83968dec07bc65cbe0f`
- `files.sha256`: one checksum for each of the 33 files inside

| Folder | Contents | Used by |
|---|---|---|
| `data/raw/` | reports received 2022-2024 and all recalls, 5 product codes (also pinned by `data/checksums.sha256`) | Phases 1-6 |
| `data/raw_new/` | reports received 2025-2026 | Phase 7 drift |
| `data/raw_all/` | 2022-2026 reports and recalls joined | Phase 7c |
| `data/processed/` | bge-small-en-v1.5 embeddings and full-corpus failure modes | Phases 3-4, 7c |

## Restore

From the repository folder (Git Bash):

```bash
gh release download data-2026-11 -R krishna6116/Medical-Device-Quality-Copilot
sha256sum mdqc_data_2026-11.tar.gz      # must equal the value above
tar --force-local -xzf mdqc_data_2026-11.tar.gz
sha256sum -c files.sha256               # every file must say OK
```

The Python environments were deleted at the same time; recreate them with `python -m venv .venv` and `pip install -r requirements.txt` (plus `requirements-embed.txt` for embeddings), and `.venv-app` from `app/requirements.txt`. The PostgreSQL databases were kept. The Power BI CSV files in `data/powerbi/` were kept (the report reads them); `python -m dashboards.powerbi_export` rebuilds them.
