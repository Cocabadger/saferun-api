#!/usr/bin/env node
import { Command } from 'commander';
import { registerCommands } from './register-commands';
import { getCliVersion } from './version';

const program = new Command();
program
  .name('saferun')
  .description('SafeRun CLI for guarding Git workflows')
  .version(getCliVersion(), '-v, --version', 'Show CLI version');

registerCommands(program);

program.parse(process.argv);
