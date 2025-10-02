import { SafeRunClient } from '@saferun/sdk';
import { MetricsCollector } from '../utils/metrics';
import { SafeRunConfig, ModeSettings } from '../utils/config';
import { GitEnvironmentInfo } from '../utils/git';

export interface InterceptorContext {
  args: string[];
  config: SafeRunConfig;
  gitInfo: GitEnvironmentInfo;
  client: SafeRunClient;
  metrics: MetricsCollector;
  modeSettings?: ModeSettings;
}
