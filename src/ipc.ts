// Typed Tauri v2 IPC bridge (N4, N6).
// Uses official @tauri-apps/api/core when running in Tauri v2 desktop shell,
// and falls back gracefully in browser / development modes.

import { convertFileSrc, invoke, isTauri } from "@tauri-apps/api/core";

export function isTauriRuntime(): boolean {
  return isTauri();
}

export function toAssetUrl(filePath: string): string {
  if (!filePath) return "";
  if (isTauri()) {
    try {
      return convertFileSrc(filePath);
    } catch {
      return filePath;
    }
  }
  return filePath;
}

export async function invokeCommand<T>(
  cmd: string,
  args: Record<string, unknown> = {}
): Promise<T | null> {
  if (isTauri()) {
    try {
      return await invoke<T>(cmd, args);
    } catch (err) {
      console.error(`[Tauri IPC Error] ${cmd}:`, err);
      return null;
    }
  }
  return null;
}

/** Like invokeCommand but propagates backend errors so callers can show the real message. */
export async function invokeCommandStrict<T>(
  cmd: string,
  args: Record<string, unknown> = {}
): Promise<T | null> {
  if (!isTauri()) return null;
  try {
    return await invoke<T>(cmd, args);
  } catch (err) {
    console.error(`[Tauri IPC Error] ${cmd}:`, err);
    throw new Error(typeof err === "string" ? err : (err as Error)?.message || String(err));
  }
}
