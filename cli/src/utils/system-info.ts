import os from 'os';

export interface SystemInfo {
  hostname: string;
  username: string;
  platform: string;
}

/**
 * Get system information for audit/notification purposes.
 * Used to identify the source machine in Slack notifications.
 */
export function getSystemInfo(): SystemInfo {
  return {
    hostname: os.hostname(),
    username: os.userInfo().username,
    platform: os.platform(),
  };
}

/**
 * Get metadata object with system info for API calls.
 * Merges system info with any existing metadata.
 */
export function withSystemMetadata(existingMetadata?: Record<string, unknown>): Record<string, unknown> {
  const sysInfo = getSystemInfo();
  return {
    ...existingMetadata,
    client_hostname: sysInfo.hostname,
    client_username: sysInfo.username,
    client_platform: sysInfo.platform,
  };
}
