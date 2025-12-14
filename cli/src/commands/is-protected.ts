/**
 * Command: saferun is-protected
 * Check if current directory is a protected repository
 * Used by shell wrapper for fast protection checking
 */

import { isRepoProtectedSync, getProtectedRepoSync } from '../utils/protected-repos';
import { getRepositoryRoot } from '../utils/git';

export class IsProtectedCommand {
  async run(options: { quiet?: boolean }): Promise<number> {
    // Get current repo root
    const repoRoot = await getRepositoryRoot(process.cwd());
    
    if (!repoRoot) {
      // Not in a git repo
      if (!options.quiet) {
        console.log('Not in a git repository');
      }
      return 1;
    }
    
    // Check global registry
    const isProtected = isRepoProtectedSync(repoRoot);
    
    if (isProtected) {
      if (!options.quiet) {
        const repo = getProtectedRepoSync(repoRoot);
        console.log(`Protected: ${repo?.github || repo?.name || repoRoot}`);
      }
      return 0; // Exit 0 = protected
    } else {
      if (!options.quiet) {
        console.log('Not protected');
      }
      return 1; // Exit 1 = not protected
    }
  }
}
