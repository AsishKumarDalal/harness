"use strict";

// The Python side of the harness needs a venv and a handful of packages.
// npm lifecycle scripts are blocked by default on newer npm versions, so the
// launchers set this up lazily on the first run instead (and repair it whenever
// requirements.txt changes).

const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const packageRoot = path.resolve(__dirname, "..");
const requirementsPath = path.join(packageRoot, "requirements.txt");
const rootEnvFile = path.join(packageRoot, ".env");

function expandHome(value) {
  if (value === "~") return os.homedir();
  if (value.startsWith("~/") || value.startsWith("~\\")) {
    return path.join(os.homedir(), value.slice(2));
  }
  return value;
}

// config.py can take HARNESS_HOME from the repo's .env; the venv must live in
// the same place, so read that one setting here too.
function envFileValue(file, name) {
  let text;
  try {
    text = fs.readFileSync(file, "utf8");
  } catch {
    return null;
  }
  const pattern = new RegExp(`^(?:export\\s+)?${name}\\s*=\\s*(.*)$`);
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const match = line.match(pattern);
    if (!match) continue;
    let value = match[1].trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    return value;
  }
  return null;
}

const harnessHome = path.resolve(
  expandHome(
    process.env.HARNESS_HOME ||
      envFileValue(rootEnvFile, "HARNESS_HOME") ||
      path.join(os.homedir(), ".harness")
  )
);
const venvDir = path.join(harnessHome, "venv");
const venvPython =
  process.platform === "win32"
    ? path.join(venvDir, "Scripts", "python.exe")
    : path.join(venvDir, "bin", "python");
const requirementsStamp = path.join(venvDir, ".harness-requirements");
const homeEnvFile = path.join(harnessHome, ".env");

const PYTHON_CANDIDATES = [
  process.env.HARNESS_PYTHON,
  process.platform === "win32" ? "py" : null,
  "python3.15",
  "python3.14",
  "python3.13",
  "python3.12",
  "python3.11",
  "python3",
  "python",
].filter(Boolean);

function note(message) {
  console.error(`[harness] ${message}`);
}

function pythonIsUsable(command) {
  if (!command) return false;
  const result = spawnSync(
    command,
    ["-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"],
    { stdio: "ignore", windowsHide: true }
  );
  return !result.error && result.status === 0;
}

function findPython() {
  for (const candidate of PYTHON_CANDIDATES) {
    if (pythonIsUsable(candidate)) return candidate;
  }
  throw new Error(
    "Python 3.11+ was not found.\n" +
      "  Install Python 3.11 or newer, then run harness again.\n" +
      "  To choose a specific interpreter: HARNESS_PYTHON=/path/to/python3 harness"
  );
}

function requirementsHash() {
  return crypto
    .createHash("sha256")
    .update(fs.readFileSync(requirementsPath))
    .digest("hex");
}

function venvIsReady() {
  if (!fs.existsSync(venvPython)) return false;
  try {
    return fs.readFileSync(requirementsStamp, "utf8").trim() === requirementsHash();
  } catch {
    return false;
  }
}

function ensurePip(basePython) {
  const check = spawnSync(venvPython, ["-m", "pip", "--version"], {
    stdio: "ignore",
    windowsHide: true,
  });
  if (!check.error && check.status === 0) return;

  note("bootstrapping pip in the Python environment");
  const attempts = [
    [venvPython, ["-m", "ensurepip", "--upgrade"]],
    [basePython, ["-m", "pip", "--python", venvPython, "install", "pip"]],
  ];
  for (const [command, args] of attempts) {
    const result = spawnSync(command, args, {
      stdio: "ignore",
      windowsHide: true,
    });
    if (!result.error && result.status === 0) {
      const verify = spawnSync(venvPython, ["-m", "pip", "--version"], {
        stdio: "ignore",
        windowsHide: true,
      });
      if (!verify.error && verify.status === 0) return;
    }
  }

  throw new Error(
    `could not bootstrap pip in ${venvDir}.\n` +
      "  On Debian/Ubuntu install python3-venv:\n" +
      "    sudo apt install python3-venv\n" +
      `  Then delete ${venvDir} and run harness again.`
  );
}

function createVenv(basePython) {
  fs.mkdirSync(harnessHome, { recursive: true });
  fs.rmSync(venvDir, { recursive: true, force: true });
  note(`first run: creating the Python environment in ${venvDir}`);

  let result = spawnSync(basePython, ["-m", "venv", venvDir], {
    stdio: ["ignore", "ignore", "pipe"],
    encoding: "utf8",
    windowsHide: true,
  });

  if (result.error || result.status !== 0 || !fs.existsSync(venvPython)) {
    // Debian/Ubuntu often ships Python without ensurepip.
    fs.rmSync(venvDir, { recursive: true, force: true });
    result = spawnSync(basePython, ["-m", "venv", "--without-pip", venvDir], {
      stdio: ["ignore", "ignore", "pipe"],
      encoding: "utf8",
      windowsHide: true,
    });
    if (result.error || result.status !== 0 || !fs.existsSync(venvPython)) {
      const detail = (result.stderr || "").trim();
      throw new Error(
        `could not create a Python virtualenv in ${venvDir}.` +
          (detail ? `\n${detail}` : "") +
          "\n  On Debian/Ubuntu install python3-venv:\n" +
          "    sudo apt install python3-venv"
      );
    }
  }

  ensurePip(basePython);
}

function installRequirements() {
  note("installing Python dependencies (first run only)");
  const result = spawnSync(
    venvPython,
    [
      "-m",
      "pip",
      "install",
      "--disable-pip-version-check",
      "-r",
      requirementsPath,
    ],
    { stdio: "inherit", windowsHide: true }
  );
  if (result.error) {
    throw new Error(`could not run pip: ${result.error.message}`);
  }
  if (result.status !== 0) {
    throw new Error(
      `pip could not install ${requirementsPath} (exit ${result.status}).\n` +
        "  Check your internet connection and run harness again."
    );
  }
  fs.writeFileSync(requirementsStamp, `${requirementsHash()}\n`, "utf8");
}

function systemHasDependencies(python) {
  const result = spawnSync(
    python,
    ["-c", "import openai, dotenv, textual, rich, ddgs"],
    { stdio: "ignore", windowsHide: true }
  );
  return !result.error && result.status === 0;
}

function useSystemPython(basePython, cause) {
  if (systemHasDependencies(basePython)) {
    note("using the system Python (dependencies already installed)");
    ensureEnvFile();
    return basePython;
  }

  note(`could not create ${venvDir}: ${cause.message.split("\n")[0]}`);
  note("trying the system Python with pip --user instead");
  spawnSync(
    basePython,
    [
      "-m",
      "pip",
      "install",
      "--user",
      "--disable-pip-version-check",
      "-r",
      requirementsPath,
    ],
    { stdio: "inherit", windowsHide: true }
  );

  if (systemHasDependencies(basePython)) {
    ensureEnvFile();
    return basePython;
  }
  throw cause;
}

function ensureEnvFile() {
  if (fs.existsSync(homeEnvFile) || fs.existsSync(rootEnvFile)) return;
  try {
    fs.mkdirSync(harnessHome, { recursive: true });
    fs.copyFileSync(path.join(packageRoot, ".env.example"), homeEnvFile);
    note(`created ${homeEnvFile}`);
    note("edit it to set OPENAI_API_KEY, BASE_URL and MODEL");
  } catch (error) {
    note(`could not create ${homeEnvFile}: ${error.message}`);
  }
}

function ensureRuntime() {
  if (venvIsReady()) {
    ensureEnvFile();
    return venvPython;
  }

  const basePython = findPython();

  if (!fs.existsSync(venvPython)) {
    try {
      createVenv(basePython);
    } catch (error) {
      return useSystemPython(basePython, error);
    }
  } else {
    ensurePip(basePython);
  }

  installRequirements();
  ensureEnvFile();
  return venvPython;
}

module.exports = {
  ensureRuntime,
  packageRoot,
  harnessHome,
  venvDir,
  venvPython,
};
