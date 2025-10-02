#!/usr/bin/env node

(async () => {
  const { HookRunner } = await import('./hooks/hook-runner');
  const runner = new HookRunner();
  await runner.run(process.argv[2] ?? '', process.argv.slice(3));
})();
