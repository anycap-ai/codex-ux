# AgentUX Core

AgentUX is a small contract between an agent product and a shared web surface.
It lets the surface expose user intent to the agent, and lets the agent author
a temporary view for the user without taking ownership of the app.

The core model is intentionally narrow:

- `snapshot`: surface to agent. Current surface state, user intents, and active view metadata.
- `view`: agent to surface. Desired temporary focus, viewport, overlays, and optional agent layer.
- `target`: the thing both sides are pointing at.
- `intent`: user-authored context attached to a target.

Everything else is app-specific or an extension.

## Design Principles

- Keep the core thin. A surface should implement AgentUX without becoming a plugin platform.
- Use `target`, not `resource`, as the main pointing abstraction. A target can be a file range, canvas node, timeline segment, video frame region, table range, DOM range, or 3D object.
- Make user intent and agent-authored view separate. An intent is authored by the user. A view is authored by the agent.
- Treat `layer` as important but optional. A surface can disable it, downgrade it, or clear it.
- Prefer desired state over command queues. The agent writes the view it wants; the surface reconciles it.
- Make every cross-boundary action auditable through events when events are supported.
- Unknown fields are ignored. Unknown required capabilities are rejected or downgraded.

## Snapshot

`GET /snapshot.json` returns the current AgentUX state.

```json
{
  "schemaVersion": "agentux.snapshot.v1",
  "surface": {
    "id": "codex-ux-file-browser",
    "kind": "workspace-review",
    "title": "File Browser",
    "capabilities": {
      "view": false,
      "layer": false,
      "events": false,
      "hostActions": []
    }
  },
  "sessionId": "session_...",
  "createdAt": "2026-06-27T00:00:00.000Z",
  "viewRevision": 0,
  "currentTarget": null,
  "intents": []
}
```

Snapshots should include structured state and compact context. They should not
embed full source files, full media files, or large app documents unless the
surface is explicitly designed for that.

## Target

A target combines a stable locator with a position inside a named space.

```json
{
  "kind": "file",
  "locator": {
    "type": "workspace-path",
    "path": "docs/spec.md",
    "absolutePath": "/workspace/docs/spec.md"
  },
  "anchor": {
    "type": "text-range",
    "space": "source-text",
    "startLine": 42,
    "endLine": 45,
    "startColumn": 1,
    "endColumn": 18
  }
}
```

The protocol does not require every surface to use files. The same shape can
point at an infinite canvas region:

```json
{
  "kind": "canvas-region",
  "locator": {
    "type": "surface-entity",
    "id": "board_main"
  },
  "anchor": {
    "type": "rect",
    "space": "canvas-world",
    "x": -1840,
    "y": 920,
    "width": 760,
    "height": 420
  }
}
```

Or a video editor timeline segment:

```json
{
  "kind": "media-segment",
  "locator": {
    "type": "surface-entity",
    "id": "sequence_main"
  },
  "anchor": {
    "type": "timeline-range",
    "space": "timeline",
    "trackId": "v1",
    "startMs": 9320,
    "endMs": 15180
  }
}
```

Each anchor type must define its coordinate or structure space. The most common
spaces are:

- `source-text`
- `rendered-document`
- `image-pixels`
- `canvas-world`
- `viewport`
- `timeline`
- `media-frame`
- `audio-waveform`
- `table-grid`
- `dom-document`
- `scene-3d`

## Intent

An intent is user-authored context attached to a target. It can be a question,
instruction, approval, warning, marker, or edit request. Agents must read the
body as intent, not assume every intent asks for a file change.

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
      "absolutePath": "/workspace/docs/spec.md"
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
  },
  "body": "Rewrite this section with less jargon.",
  "status": "open",
  "createdAt": "...",
  "updatedAt": "..."
}
```

Surfaces may expose user-facing words such as note, comment, issue, or marker.
Those are product language. The protocol object is still an intent.

## View

`view` is the agent-authored desired state for the shared surface. It is
temporary, dismissible, and separate from user intent.

```json
{
  "schemaVersion": "agentux.view.v1",
  "revision": 8,
  "focus": {
    "target": {
      "kind": "canvas-region",
      "locator": {
        "type": "surface-entity",
        "id": "board_main"
      },
      "anchor": {
        "type": "rect",
        "space": "canvas-world",
        "x": -1840,
        "y": 920,
        "width": 760,
        "height": 420
      }
    }
  },
  "viewport": {
    "space": "canvas-world",
    "centerX": -1460,
    "centerY": 1130,
    "zoom": 0.82
  },
  "overlays": [],
  "layer": null
}
```

Core host actions are deliberately few:

- `focusTarget`
- `setViewport`
- `createIntent`
- `emitEvent`
- `clearView`

These are enough for a useful guided review loop without exposing arbitrary app
internals.

## Agent Layer

`layer` is an optional field inside `view`. It is how agents author richer
temporary experiences when a surface supports it.

```json
{
  "layer": {
    "enabled": true,
    "placement": "side-panel",
    "sandbox": "strict",
    "source": {
      "type": "html",
      "html": "<div id=\"agent-ui\"></div>",
      "css": ".risk { font-weight: 600; }",
      "js": "AgentUXLayer.emitEvent({ type: 'ready' })"
    },
    "permissions": ["readSnapshot", "emitEvents", "navigateTargets"]
  }
}
```

The layer is where an agent can create a purpose-built temporary UI: review
tour, checklist, mini-map, comparison panel, timeline navigator, visual
debugger, or a custom inspector. The boundary is what keeps that flexibility
safe:

- The layer cannot directly access the host DOM.
- Network access is disabled unless the surface explicitly grants it.
- The layer cannot read host cookies, local storage, or credentials.
- The layer can call only declared host actions.
- All user interactions crossing the boundary are emitted as events.
- The host can reject, downgrade, or clear the layer at any time.
- Destructive app actions are outside AgentUX core and require explicit host policy.

Primitives such as highlight or callout are useful helpers, not the core model.
If a surface supports no layer, it can still render a simple focus state from
the `view` object.

## Events

Events are an optional append-only response stream from surface to agent.

```json
{
  "id": "evt_...",
  "type": "view.action",
  "viewRevision": 8,
  "actionId": "next",
  "target": null,
  "createdAt": "2026-06-27T00:00:00.000Z"
}
```

Recommended endpoint:

```text
GET /api/agentux/events?after=<event-id>
```

Events are not required for a read-only review surface, but they become
important once a surface supports view actions or agent layer interactions.

## Compatibility Policy

During early Codex UX development, AgentUX can make breaking changes. Once a
surface declares a protocol version in public distribution, it should keep that
version stable and add new behavior through capabilities or new schema versions.
