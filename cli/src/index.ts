#!/usr/bin/env node
import { Command } from 'commander';
import { registerCommands } from './register-commands';

const program = new Command();
program.name('saferun').description('SafeRun CLI for guarding Git workflows');

registerCommands(program);

program.parse(process.argv);
