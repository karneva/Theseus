import type * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as http from 'http';
import * as https from 'https';
import type { JsonObject } from '../shared/protocol';

function fileMtimeIso(filePath: string): string {
  try {
    return fs.statSync(filePath).mtime.toISOString();
  } catch {
    return '';
  }
}

export function getExtensionBuildInfo(context: vscode.ExtensionContext): JsonObject {
  const packageJson = context.extension.packageJSON as Record<string, unknown> | undefined;
  const extensionRoot = context.extensionUri.fsPath;
  return {
    version: typeof packageJson?.version === 'string' ? packageJson.version : '',
    extensionPath: extensionRoot,
    builtAt: fileMtimeIso(path.join(extensionRoot, 'out', 'extension.js')),
    mediaBuiltAt: fileMtimeIso(path.join(extensionRoot, 'media', 'main.js')),
    sourceMarker: 'ui-regression-fixes-2026-05-19',
  };
}

function requestWithTimeout(
  url: URL,
  timeoutMs: number,
): Promise<{ statusCode: number; statusMessage: string }> {
  return new Promise((resolve, reject) => {
    const client = url.protocol === 'https:' ? https : http;
    const request = client.request(url, { method: 'GET', timeout: timeoutMs }, (response) => {
      response.resume();
      response.on('end', () =>
        resolve({
          statusCode: response.statusCode || 0,
          statusMessage: response.statusMessage || '',
        }),
      );
    });
    request.on('timeout', () => {
      request.destroy(new Error(`timeout after ${timeoutMs}ms`));
    });
    request.on('error', reject);
    request.end();
  });
}

export async function probeExternalServer(serverUrl: string): Promise<JsonObject> {
  const raw = String(serverUrl || '').trim();
  if (!raw) {
    return {
      status: 'standalone',
      url: '',
      detail: 'Standalone mode; no external Theseus server URL configured.',
    };
  }
  let healthUrl: URL;
  try {
    const base = new URL(raw.endsWith('/') ? raw : `${raw}/`);
    healthUrl = new URL('health', base);
  } catch (err) {
    return {
      status: 'unreachable',
      url: raw,
      detail: `Invalid serverUrl: ${err instanceof Error ? err.message : String(err)}`,
    };
  }
  try {
    const response = await requestWithTimeout(healthUrl, 1500);
    const ok = response.statusCode >= 200 && response.statusCode < 500;
    return {
      status: ok ? 'connected' : 'unreachable',
      url: raw,
      healthUrl: healthUrl.toString(),
      detail: `GET /health -> ${response.statusCode}${response.statusMessage ? ` ${response.statusMessage}` : ''}`,
    };
  } catch (err) {
    return {
      status: 'unreachable',
      url: raw,
      healthUrl: healthUrl.toString(),
      detail: err instanceof Error ? err.message : String(err),
    };
  }
}
