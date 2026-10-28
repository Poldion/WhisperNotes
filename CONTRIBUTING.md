# Contributing

Bug reports, ideas and pull requests are welcome.

## Development setup

You don't need an Apple GPU or a graphics card: `backend/tools/mock_whisper_server.py` stands in for `whisper-server`,
everything else runs for real.

```bash
cd backend && pip install uv && uv sync
cd frontend && npm ci
cd discord-bot && npm ci
```

Dashboard with hot reload: start the backend in `backend/` with
`uv run uvicorn app.main:app --port 8000 --env-file .env.dev`, then `cd frontend && npm run dev` →
`http://localhost:5173/dashboard/`. Dashboard jobs need `ffmpeg`/`ffprobe` on the `PATH`.

## Tests

```bash
cd backend && uv run pytest -q
cd frontend && npm run check-i18n && npm run build
cd discord-bot && npm test
```

CI (`.github/workflows/ci.yml`, GitHub Actions) runs all three on every push and pull request.

## Translations

The interface text is written in German in the code and translated with `t('…')` (gettext style: the German text
is the key). Every new text needs an entry in `frontend/src/i18n.en.ts`, otherwise `npm run check-i18n` fails. Server
messages work the same way with `tr()` and `backend/app/i18n.py`; the summary prompts live in
`backend/app/prompts.py` (one set per language). A new language means another dictionary and prompt set.

## Guidelines

- Keep changes small and in the style of the surrounding code; comments explain *why*, not *what*.
- Commit messages: a short summary line, then what changed and why.
- Line endings: LF (see `.gitattributes`).
- No private data in commits, tests or examples: no tokens, real names or real addresses – use placeholders such as
  `nas.local`.
- Report security issues privately, see [SECURITY.md](SECURITY.md).

## Deutsch

Beiträge auf Deutsch sind genauso willkommen wie auf Englisch. Die Doku unter `docs/` gibt es teilweise nur auf
Deutsch, und die Texte im Code sind deutsch.
