#!/usr/bin/env node
import { Command } from 'commander';
import updateNotifier from 'update-notifier';
import { registerCommands } from './register-commands';
import { getCliVersion } from './version';

// Check for updates in background
const pkg = require('../package.json');
updateNotifier({ pkg }).notify();

const program = new Command();
program
  .name('saferun')
  .description('SafeRun CLI for guarding Git workflows')
  .version(getCliVersion(), '-v, --version', 'Show CLI version');

registerCommands(program);

program.parse(process.argv);
