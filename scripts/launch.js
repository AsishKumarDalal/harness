"use strict";

const path = require("path");
const { spawn } = require("child_process");
const { ensureRuntime, packageRoot } = require("./env");

const SIGNAL_EXIT_CODES = {
  SIGHUP: 1,
  SIGINT: 2,
  SIGQUIT: 3,
  SIGILL: 4,
  SIGTRAP: 5,
  SIGABRT: 6,
  SIGBUS: 7,
  SIGFPE: 8,
  SIGKILL: 9,
  SIGUSR1: 10,
  SIGSEGV: 11,
  SIGUSR2: 12,
  SIGPIPE: 13,
  SIGALRM: 14,
  SIGTERM: 15,
};

function launch(name, entry, argv) {
  let python;
  try {
    python = ensureRuntime();
  } catch (error) {
    console.error(`${name}: ${error.message}`);
    process.exit(1);
  }

  const child = spawn(python, [path.join(packageRoot, entry), ...argv], {
    cwd: process.cwd(),
    env: process.env,
    stdio: "inherit",
    windowsHide: true,
  });

  child.on("error", (error) => {
    console.error(`${name}: could not start Python: ${error.message}`);
    process.exit(1);
  });

  child.on("exit", (code, signal) => {
    if (signal) {
      process.exit(128 + (SIGNAL_EXIT_CODES[signal] || 1));
    }
    process.exit(code === null ? 1 : code);
  });
}

module.exports = { launch };
