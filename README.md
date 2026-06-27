# Codex UX

Codex UX is a workspace for building richer, browser-based UX surfaces for Codex.

The goal is broader than file review: make it easier for people and coding agents to share context through focused interfaces instead of flattening every interaction into chat. A surface can be a reviewer, an inspector, a planning board, a visual handoff tool, or any small local UI that gives Codex better structured context.

The first surface is **Codex UX File Browser**: a read-only workspace browser for precise, anchored notes on files.

## Quick Start

Codex UX is for **Codex app**. The easiest install path is to ask Codex directly:

```text
help me install https://github.com/anycap-ai/codex-ux
```

You can also install it from the Codex app UI: open **Plugins**, add the `anycap-ai/codex-ux` marketplace, then install **Codex UX**.

If you prefer the CLI:

```bash
codex plugin marketplace add anycap-ai/codex-ux --ref main
codex plugin add codex-ux --marketplace codex-ux
```

Start a new Codex thread, then run:

```text
$codex-ux-file-browser
```

Codex opens the current File Browser surface for your workspace. Add notes, click `Send`, and Codex will handle the notes in the conversation.

If Codex asks you to review the hook in `/hooks`, trust it before using the autostart flow. The hook only reacts when your prompt explicitly mentions `$codex-ux-file-browser` or `/codex-ux-file-browser`.

If your machine cannot run `git` reliably, install from a downloaded GitHub archive instead:

```bash
curl -L https://github.com/anycap-ai/codex-ux/archive/refs/heads/main.zip -o /tmp/codex-ux.zip
ditto -x -k /tmp/codex-ux.zip /tmp/codex-ux-install
codex plugin marketplace add /tmp/codex-ux-install/codex-ux-main
codex plugin add codex-ux --marketplace codex-ux
```

## Current Surface: File Browser

With the File Browser, you can:

- Browse files in the current workspace.
- Select exact ranges in code, Markdown, text, CSV, HTML, and PDFs.
- Mark image areas with boxes, pins, or freehand drawing.
- Attach a note to the selected range or region.
- Send all open notes back to Codex as structured AgentUX intents.
- Ask Codex to answer, explain, or make edits based on those notes.

The browser is intentionally read-only. It never modifies your repo. It gives Codex better context; Codex still performs any requested edits through normal workspace tools.

## How The File Browser Feels

Use it when chat is too vague:

- "This paragraph is confusing. Rewrite it."
- "This part of the screenshot is wrong."
- "Explain why this block exists."
- "Make this table row match the new behavior."
- "These three notes are all about the same bug. Fix them together."

You mark the place. Codex gets the anchor, nearby context, note text, and file metadata.

## Why Codex UX Exists

Codex is good at working across code, docs, terminal output, and tools, but some collaboration patterns need more than a text box. Human feedback is often visual, spatial, comparative, or stateful. You might want to point at an exact thing, organize a set of decisions, mark several related items, or hand off a structured view of what matters.

Codex UX is the layer for those interactions.

The broader vision is a family of small, local UX surfaces that help humans and coding agents share context cleanly. File Browser is first because anchored file feedback is an immediate, useful version of that idea.

## What Gets Installed Today

The plugin includes:

- `codex-ux-file-browser`: the skill Codex uses to launch and operate the File Browser.
- A local Python server for serving the read-only browser and snapshot API.
- Built frontend assets for the File Browser UI.
- A Codex hook that starts the browser automatically when you invoke the skill.

Everything runs locally. The browser serves files from the workspace you are reviewing and skips common large, generated, and secret-bearing paths.

## Status

Codex UX is early. The File Browser already works for local file browsing, anchored notes, and handoff back to Codex. The next step is to keep the first surface small and useful while expanding AgentUX based on workflows that genuinely need richer interaction.
