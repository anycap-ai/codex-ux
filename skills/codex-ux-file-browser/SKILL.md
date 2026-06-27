---
name: codex-ux-file-browser
description: Launch and use Codex UX File Browser, a local read-only browser for collecting precise AgentUX notes on workspace text files and images. Use when the user wants to review many files, add notes to long documents, mark code or Markdown ranges, annotate screenshots/images, expose notes through window.AgentUX.getSnapshot() or /snapshot.json, or ask Codex to read and respond to anchored notes.
---

# Codex UX File Browser

Use this skill to run a local file browser that lets the user browse workspace files, add precise notes, and expose those notes as AgentUX intents in a snapshot. Notes are user-facing language; the protocol object is an intent anchored to a target. Intents can be questions, observations, warnings, approvals, context, or concrete edit requests. The web UI is read-only: it never edits project files. Codex reads the snapshot, then answers, uses context, explains, or edits files with normal workspace tools only when the intent asks for it or clearly implies it.

## Start Review Browser

Preferred fast path: run the bundled startup script from this skill directory. Let `SKILL_DIR` mean the absolute directory containing the loaded `SKILL.md`; substitute that path directly and do not search installed plugin caches when the skill path is already available. Do not paste Python resolver snippets into the terminal; the startup script owns Python discovery.

```bash
"$SKILL_DIR/scripts/start-file-browser.sh" "$PWD"
```

The startup script prints one JSON object. Read `url`, then open it in the Codex in-app Browser yourself before responding. Read `snapshotUrl` when the user asks Codex to handle notes.

### Open In-App Browser

Opening the page is part of this skill's startup task. Do not stop after printing or summarizing the URL.

When the in-app Browser plugin is available, use it immediately: make the Browser visible, reuse the selected tab when present, otherwise create a new tab, then navigate to `url`. If browser control tools are not already exposed but tool discovery is available, search for the in-app Browser control tool and use it. Only fall back to giving the user the URL when in-app Browser control is unavailable or fails.

The startup script resolves Python, runs `scripts/launch.py` with `--reuse --detach --json`, and exits after printing startup details. `--reuse` checks the current workspace registry under `~/.codex-ux/file-browser/workspaces/`, matches `workspaceRoot`, verifies `url + /api/meta`, and reuses the existing browser when it is healthy. `--detach` starts a background server only when no healthy server exists for that workspace. Do not trust registry files without the launcher's health check, because they can be stale after a previous process exits.

The launcher returns:

- `url`: open this in the in-app browser.
- `snapshotUrl`: GET this endpoint when the user asks Codex to read notes.
- `sessionPath`: temp JSON path where notes are stored.
- `registryPath`: stable handoff JSON path for the current workspace.

The launcher binds to a random available port by default. Do not assume `8787` or reconstruct the URL from defaults; read stdout and treat the printed `url` and `snapshotUrl` values as the source of truth.

Use foreground mode only when the user explicitly wants to keep the server attached to the terminal:

```bash
"$SKILL_DIR/scripts/start-file-browser.sh" "$PWD" --foreground
```

Use a fixed port only when the user explicitly asks for one:

```bash
"$SKILL_DIR/scripts/start-file-browser.sh" "$PWD" --port 8790
```

## Browser Workflow

1. Open the printed `URL` in the Codex in-app Browser yourself.
2. Let the user add notes:
   - Text/code/Markdown: select a range and write a note in the floating composer.
   - Images: choose Area, Pin, or Draw, mark the image, then write a note.
   - Use the command palette or file search to move quickly across files.
3. Preferred handoff: the user clicks `Send` in the browser. Read the launcher-provided `registryPath`, match `workspaceRoot` to the current workspace, then read `handoff.snapshotUrl` exactly as provided. Always inspect the snapshot `intents` array before responding; do not answer from the chat message or handoff prompt alone. Handoff snapshot URLs may include `?intents=open` and intentionally expose only open intents, not resolved intents.
4. Fallback handoff: when the user asks to handle notes manually, read the printed `Snapshot` endpoint:

```bash
curl -s "$SNAPSHOT_URL"
```

If controlling the browser, `await window.AgentUX.getSnapshot()` is also available in the page main world. Some automation runtimes evaluate JavaScript in an isolated world; when `window.AgentUX` is not visible there, read `/snapshot.json` or discover it from `document.documentElement.dataset.agentuxSnapshotEndpoint` / `link[rel="agentux-snapshot"]`.

## Handling Notes

Handle open notes as AgentUX intents in a batch, not as a slow per-note audit:

1. Read the snapshot once and work from its open `intents` array. If the handoff URL includes `?intents=open`, do not fetch the full snapshot unless the user asks about resolved intents.
2. Triage each intent body before reading files. Use the snapshot alone when it contains enough context to answer; read `target.locator.absolutePath` or `workspaceRoot + target.locator.path` only when needed for a safe answer or edit.
3. Group intents by file and batch file reads. For text anchors, start from line/column and use `selectedText`, `contextBefore`, and `contextAfter` only as quick fallback when the nearby text no longer matches. Do not recompute or verify `anchorHash` during normal intent handling.
4. Locate image, PDF, HTML, and CSV anchors by their provided original coordinate or range space. Do not treat browser screen coordinates as authoritative.
5. Read the `body` field as the user's intent. It may be a question, observation, warning, approval, context, quick marker, or edit request. A body value of `mark` usually means the user marked the location without extra wording; use the current user request or thread context to decide what to do with that location.
6. Edit files only when the intent asks for it or clearly implies it. When editing, make the smallest file edits that satisfy the intent and preserve unrelated user changes.
7. Accumulate handled intent ids and resolve them once at the end with `POST /api/intents/resolve` using `{ "ids": ["intent_..."] }`, or `await window.AgentUX.resolveIntents(["intent_..."])` when controlling the page.
8. Resolve only intents you actually handled. Leave ambiguous, unsafe, or still-pending intents open and report why.
9. Unless the user explicitly asks about resolved intents, do not mention, summarize, or list them in the final reply.
10. Make the final reply user-friendly and easy to map back to the notes. When multiple open intents exist, clearly distinguish which response belongs to which intent, usually with short headers or compact labels that include the file/location and a brief paraphrase. Group closely related intents when that is clearer, and avoid rigid status-table formatting unless it genuinely helps.

Read [references/agentux-contract.md](references/agentux-contract.md) when implementing or debugging snapshot handling.

## API Surface

The local Python server serves the packaged frontend from `assets/file-browser/dist` and exposes:

- `GET /api/meta`
- `GET /api/files`
- `GET /api/file?path=<relativePath>`
- `GET /api/image?path=<relativePath>`
- `GET /api/search?q=<query>`
- `GET /api/session`
- `PUT /api/session`
- `POST /api/handoff/send`
- `POST /api/intents/resolve`
- `GET /snapshot.json`
- `GET /snapshot.json?intents=open`

`POST /api/handoff/send` writes the current workspace registry, stores the latest handoff JSON in the temp session directory, and attempts to open the current Codex thread, set the prompt directly in the Codex composer through macOS Accessibility, and press Enter. It works best with `CODEX_THREAD_ID` in the launcher environment. If automation does not send, read the workspace registry or the returned `snapshotUrl` directly; do not retry older handoff modes.

`GET /snapshot.json?intents=open` returns a handoff-focused snapshot whose `intents` and `files` include only open intents. Use the exact handoff URL unless the user explicitly asks about resolved intents.

`POST /api/intents/resolve` accepts `{ "ids": ["intent_..."] }` and marks those intents `status: "resolved"`. It returns `resolvedIds`, `missingIds`, and the latest `intents` array.

The scanner skips `.git`, `node_modules`, build outputs, caches, common lock files, large files, and likely secret-bearing files such as `.env`, private keys, credentials, and certificate files.

The page also exposes:

- `window.AgentUX.getSnapshot()` in the page main world
- `window.AgentUX.getIntents()` in the page main world
- `window.AgentUX.resolveIntents(["intent_..."])` in the page main world
- `document.documentElement.dataset.agentuxSnapshotEndpoint`
- `<link rel="agentux-snapshot" href="/snapshot.json">`

## Runtime Contents

The runtime server is Python stdlib only. This publishable skill contains the packaged app in `assets/file-browser/dist`; it does not need frontend source dependencies at runtime.

Do not add `node_modules`, cache directories, source-repo build instructions, or temporary session files to the skill.
