import { execFile } from "node:child_process";
import { access, readdir, stat } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const SKILL_DIR = resolve(SCRIPT_DIR, "..");

export async function launchAndOpenFileBrowser(options = {}) {
  const skillDir = options.skillDir ?? SKILL_DIR;
  const workspaceRoot = options.workspaceRoot ?? globalThis.nodeRepl?.cwd;
  if (!workspaceRoot) {
    throw new Error("workspaceRoot is required when nodeRepl.cwd is unavailable.");
  }

  const startup = await launchFileBrowser({ skillDir, workspaceRoot });
  if (startup.codexHost !== "codex-app") {
    return {
      startup,
      opened: false,
      reason: `Launcher reported ${startup.codexHost}; use the launcher url directly.`,
    };
  }

  const browserClientPath = options.browserClientPath ?? await findBrowserClient();
  const browser = await openInAppBrowser({
    browserClientPath,
    url: startup.url,
  });

  return {
    startup,
    opened: true,
    browser,
  };
}

export async function launchFileBrowser({ skillDir = SKILL_DIR, workspaceRoot } = {}) {
  const startScript = join(skillDir, "scripts", "start-file-browser.sh");
  await access(startScript);

  const result = await execFileJson(startScript, [workspaceRoot], {
    timeout: 30000,
  });

  if (!result || typeof result !== "object" || typeof result.url !== "string") {
    throw new Error("File Browser launcher returned invalid startup JSON.");
  }

  return result;
}

export async function openInAppBrowser({ browserClientPath, url }) {
  if (!browserClientPath) {
    throw new Error("browserClientPath is required.");
  }
  if (!url) {
    throw new Error("url is required.");
  }

  if (globalThis.agent?.browsers == null) {
    const { setupBrowserRuntime } = await import(asImportSpecifier(browserClientPath));
    await setupBrowserRuntime({ globals: globalThis });
  }

  const browser = await globalThis.agent.browsers.get("iab");
  await (await browser.capabilities.get("visibility")).set(true);

  let tab = await browser.tabs.selected();
  if (!tab) {
    tab = await browser.tabs.new();
  }

  const currentUrl = await tab.url();
  if (currentUrl !== url && currentUrl !== `${url}/`) {
    await tab.goto(url);
    await tab.playwright.waitForLoadState({
      state: "domcontentloaded",
      timeoutMs: 10000,
    });
  }

  return {
    title: await tab.title(),
    url: await tab.url(),
  };
}

export async function findBrowserClient() {
  const roots = browserClientSearchRoots();
  const candidates = [];
  for (const root of roots) {
    candidates.push(...await findFiles(root, "browser-client.mjs", 8));
  }

  const browserCandidates = candidates.filter((candidate) => (
    candidate.includes("/browser/") && candidate.endsWith("/scripts/browser-client.mjs")
  ));
  const usable = browserCandidates.length > 0 ? browserCandidates : candidates;
  if (usable.length === 0) {
    throw new Error("Could not find browser-client.mjs in Codex plugin cache.");
  }

  const withStats = await Promise.all(usable.map(async (path) => ({
    path,
    mtimeMs: (await stat(path)).mtimeMs,
  })));
  withStats.sort((left, right) => right.mtimeMs - left.mtimeMs || left.path.localeCompare(right.path));
  return withStats[0].path;
}

function browserClientSearchRoots() {
  const home = globalThis.nodeRepl?.homeDir ?? homedir();
  const codexHome = globalThis.process?.env?.CODEX_HOME ?? join(home, ".codex");
  return unique([
    join(codexHome, "plugins", "cache"),
    join(home, ".codex", "plugins", "cache"),
  ]);
}

async function findFiles(root, fileName, maxDepth) {
  const results = [];
  await walk(root, 0);
  return results;

  async function walk(directory, depth) {
    if (depth > maxDepth) {
      return;
    }

    let entries;
    try {
      entries = await readdir(directory, { withFileTypes: true });
    } catch (error) {
      if (error?.code === "ENOENT" || error?.code === "EACCES") {
        return;
      }
      throw error;
    }

    for (const entry of entries) {
      const path = join(directory, entry.name);
      if (entry.isFile() && entry.name === fileName) {
        results.push(path);
      } else if (entry.isDirectory()) {
        await walk(path, depth + 1);
      }
    }
  }
}

async function execFileJson(file, args, options) {
  const { stdout } = await execFileText(file, args, options);
  try {
    return JSON.parse(stdout);
  } catch (error) {
    throw new Error(`Command returned invalid JSON: ${file}`, { cause: error });
  }
}

function execFileText(file, args, options = {}) {
  return new Promise((resolvePromise, rejectPromise) => {
    execFile(file, args, {
      encoding: "utf8",
      maxBuffer: 1024 * 1024,
      timeout: options.timeout ?? 30000,
    }, (error, stdout, stderr) => {
      if (error) {
        error.stdout = stdout;
        error.stderr = stderr;
        rejectPromise(error);
        return;
      }
      resolvePromise({ stdout, stderr });
    });
  });
}

function asImportSpecifier(path) {
  return path.startsWith("file:") ? path : pathToFileURL(path).href;
}

function unique(values) {
  return [...new Set(values)];
}
