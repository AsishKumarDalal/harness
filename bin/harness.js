#!/usr/bin/env node
"use strict";

require("../scripts/launch").launch("harness", "cli.py", process.argv.slice(2));
