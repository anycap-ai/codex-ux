# AgentUX File Browser Binding

This document binds the generic AgentUX core model to the File Browser app.
The user-facing product language stays simple: users add notes. The protocol
language is stricter: each note is an `intent` attached to a file `target`.

Read this together with [AgentUX Core](agentux-core.md).

## Runtime Contract

The File Browser exposes:

- `GET /api/meta`
- `GET /snapshot.json`
- `GET /snapshot.json?intents=open`
- `GET /api/session`
- `PUT /api/session`
- `POST /api/intents/resolve`
- `POST /api/handoff/send`

The browser also exposes:

- `window.AgentUX.getSnapshot()`
- `window.AgentUX.getIntents()`
- `window.AgentUX.requestHandoff()`
- `window.AgentUX.resolveIntents(["intent_..."])`
- `document.documentElement.dataset.agentuxSnapshotEndpoint`
- `<link rel="agentux-snapshot" href="/snapshot.json">`

The app currently does not implement `agentux.view.v1`, events, or agent layer.
Those capabilities are declared as disabled in the snapshot surface object.

## Host Context

The launcher detects its Codex host from the parent process tree and reports it
as `codexHost`:

- `codex-app`: launched from the Codex desktop app. Handoff may use macOS
  Accessibility automation to send the prompt back to the active Codex app
  thread.
- `codex-cli`: launched from Codex CLI. Handoff never controls the desktop app;
  it creates the same handoff payload and the browser copies the prompt for the
  user to paste into the CLI session.

`GET /api/meta`, handoff responses, and workspace registry files include
`codexHost`. Startup, meta, and workspace registry payloads also include
`codexHostSource`; `process-tree` means the launcher identified the host from
an ancestor process, and `default` means it used the safe CLI fallback. Server
reuse must match both `workspaceRoot` and `codexHost`.

## Snapshot Shape

```json
{
  "schemaVersion": "agentux.snapshot.v1",
  "surface": {
    "id": "codex-ux-file-browser",
    "kind": "workspace-review",
    "title": "File Browser",
    "workspaceRoot": "/absolute/workspace/root",
    "capabilities": {
      "view": false,
      "layer": false,
      "events": false,
      "hostActions": []
    }
  },
  "workspaceRoot": "/absolute/workspace/root",
  "sessionId": "session_...",
  "createdAt": "2026-06-27T00:00:00.000Z",
  "intentPurpose": "general-agent-context",
  "openIntentCount": 0,
  "viewRevision": 0,
  "currentTarget": null,
  "agentGuidance": [],
  "files": [],
  "intents": []
}
```

Snapshots intentionally do not include full file contents. Agents should read
original files from the workspace only when needed to answer safely or make an
edit.

`GET /snapshot.json?intents=open` returns a handoff-focused snapshot whose
`intents` and `files` include only open intents. `Send` uses this filtered
URL so agents do not see resolved intents during normal handoff handling.

## File Target

All current File Browser targets use `workspace-path` locators.

```json
{
  "kind": "file",
  "locator": {
    "type": "workspace-path",
    "path": "docs/spec.md",
    "absolutePath": "/absolute/workspace/root/docs/spec.md"
  },
  "anchor": {
    "type": "text-range",
    "space": "source-text",
    "startLine": 42,
    "endLine": 45,
    "startColumn": 1,
    "endColumn": 18,
    "selectedText": "...",
    "contextBefore": "...",
    "contextAfter": "...",
    "anchorHash": "sha256:..."
  }
}
```

Canonical AgentUX anchors include `space`. Current File Browser snapshots omit
`space` until view support lands; agents should infer it from the anchor type in
this binding.

## Text Intent

```json
{
  "id": "intent_...",
  "kind": "intent",
  "purpose": "note",
  "target": {
    "kind": "file",
    "locator": {
      "type": "workspace-path",
      "path": "docs/spec.md",
      "absolutePath": "/absolute/workspace/root/docs/spec.md"
    },
    "anchor": {
      "type": "text-range",
      "startLine": 42,
      "endLine": 45,
      "startColumn": 1,
      "endColumn": 18,
      "selectedText": "...",
      "contextBefore": "...",
      "contextAfter": "...",
      "anchorHash": "sha256:..."
    }
  },
  "body": "Rewrite this section with less jargon.",
  "status": "open",
  "createdAt": "...",
  "updatedAt": "..."
}
```

Line and column values are the primary locator. Use selected text and context as
fallback when nearby text no longer matches or a risky edit needs extra
confidence. `anchorHash` is a protocol/debug field; agents should not recompute
it during normal intent handling.

## Image Intent

```json
{
  "id": "intent_...",
  "kind": "intent",
  "purpose": "note",
  "target": {
    "kind": "file",
    "locator": {
      "type": "workspace-path",
      "path": "assets/example.png",
      "absolutePath": "/absolute/workspace/root/assets/example.png"
    },
    "anchor": {
      "type": "image-rect",
      "imageWidth": 1600,
      "imageHeight": 900,
      "x": 240,
      "y": 180,
      "width": 320,
      "height": 180
    }
  },
  "body": "Make this region read as the primary action.",
  "status": "open",
  "createdAt": "...",
  "updatedAt": "..."
}
```

Image coordinates are original image pixels, never browser screen coordinates.
Supported image anchors are `image-rect`, `image-point`, and `image-path`.

## HTML Intent

Rendered HTML intents use browser document CSS pixels. They are meant for visual
or copy feedback on the rendered page, while source-mode text ranges continue
to use `text-range`.

```json
{
  "id": "intent_...",
  "kind": "intent",
  "purpose": "note",
  "target": {
    "kind": "file",
    "locator": {
      "type": "workspace-path",
      "path": "public/index.html",
      "absolutePath": "/absolute/workspace/root/public/index.html"
    },
    "anchor": {
      "type": "html-text",
      "documentWidth": 1280,
      "documentHeight": 720,
      "selectedText": "Start reviewing",
      "contextBefore": "...",
      "contextAfter": "...",
      "startPath": [1, 0, 2],
      "endPath": [1, 0, 2],
      "startOffset": 0,
      "endOffset": 15,
      "rects": [{ "x": 320, "y": 180, "width": 120, "height": 22 }]
    }
  },
  "body": "Make this call to action more specific.",
  "status": "open",
  "createdAt": "...",
  "updatedAt": "..."
}
```

`html-rect` anchors store the marked rectangle in document CSS pixels and also
store the target DOM element used to reproject the mark after responsive
layout changes. `targetPath` is a child-node path from `document.body` to the
target element, and `targetRect` is that element's document rectangle when the
mark was created. Viewers should reproject the mark by preserving its original
edge offsets from `targetRect`, not by scaling the rectangle proportionally with
the target element.

```json
{
  "anchor": {
    "type": "html-rect",
    "documentWidth": 1280,
    "documentHeight": 720,
    "x": 720,
    "y": 220,
    "width": 360,
    "height": 140,
    "targetPath": [1, 3],
    "targetRect": { "x": 680, "y": 180, "width": 440, "height": 220 }
  }
}
```

Agents should treat DOM paths and coordinates as fast hints and validate
against the current file before editing.

## PDF Intent

PDF intents use page coordinates measured at the page's native PDF viewport
scale. `pdf-rect` anchors can represent either an area mark or a text
selection. Text selections include `selectedText`, nearby context, and optional
per-line `rects` in the same coordinate space.

```json
{
  "anchor": {
    "type": "pdf-rect",
    "pageNumber": 2,
    "pageWidth": 612,
    "pageHeight": 792,
    "x": 90,
    "y": 120,
    "width": 260,
    "height": 36,
    "rects": [{ "x": 90, "y": 120, "width": 260, "height": 16 }],
    "selectedText": "The selected PDF text",
    "contextBefore": "...",
    "contextAfter": "..."
  }
}
```

## Agent Rules

- Read the provided AgentUX snapshot and inspect its `intents` array before responding.
- Treat only `status: "open"` as requiring an agent response.
- Triage intent body before reading files. If the snapshot has enough context to answer, respond without extra file reads.
- Group intents by file and batch file reads.
- Read `body` as the user's actual intent. It may ask for an answer, provide context, point out a concern, approve something, mark a location, or request an edit.
- Blank note text is normalized to `body: "mark"`. Treat that as a lightweight location marker.
- Use anchors as fast locators. For text anchors, start from line/column and nearby text.
- Edit files only when the intent asks for it or clearly implies it.
- After fully handling open intents, resolve their ids in one `POST /api/intents/resolve` when possible, with body `{ "ids": ["intent_..."] }`.
- Resolve only intents you actually handled. Leave ambiguous, unsafe, or still-pending intents open and report why.
- Do not ask the user to restate context already present in the snapshot.
- Make the final reply easy to map back to the user's notes in the File Browser.
