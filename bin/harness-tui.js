#!/usr/bin/env node
"use strict";

require("../scripts/launch").launch(
  "harness-tui",
  "tui/__main__.py",
  process.argv.slice(2)
);
