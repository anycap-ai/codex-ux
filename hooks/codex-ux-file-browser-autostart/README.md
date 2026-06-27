# Codex UX File Browser Autostart

This is an isolated Codex hook that opens the Codex UX File Browser when a prompt explicitly mentions `$codex-ux-file-browser` or `/codex-ux-file-browser`.

Flow:

1. `UserPromptSubmit` runs `hook.py`.
2. `hook.py` exits unless the submitted prompt contains the trigger.
3. On trigger, it extracts the current Codex thread id from the hook environment or payload when available.
4. It runs the packaged launcher with `--reuse --detach --json`, passing `CODEX_THREAD_ID` to the launched service when available.
5. It uses macOS Accessibility to inspect the Codex in-app Browser. If the Browser is already open at the launcher URL, it does nothing. Otherwise it presses the Codex `Open Browser Tab` and `Focus Browser Address Bar` menu items as needed, verifies focus is on the Browser address field, sets that field's AX value to the launcher URL, and presses Return.
6. It injects `hookSpecificOutput.additionalContext` so the `$codex-ux-file-browser` skill knows the service and browser are already prepared and can skip duplicate startup/open steps.

The hook is fail-open. If service launch or macOS Accessibility automation fails, it logs to the temp directory and exits successfully so the normal Codex skill flow can continue.

To remove this module, delete this directory and remove its entry from `.codex/hooks.json`.

Set `CODEX_UX_FILE_BROWSER_AUTOSTART=0` before launching Codex to disable it without editing files.
