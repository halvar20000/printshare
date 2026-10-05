import { NativeModule, requireNativeModule } from 'expo';

export type BambuCert = { serial: string; issuer: string; bambu: boolean };
export type BambuFound = { address: string; serial: string };
export type BambuEvents = {
  onMessage(e: { host: string; payload: string }): void;
  onState(e: { host: string; connected: boolean; error: string | null }): void;
};

declare class BambuLanModule extends NativeModule<BambuEvents> {
  /** The printer's TLS certificate (CN = serial, issuer "BBL CA"); null when nothing answers on port 8883. */
  certAsync(host: string): Promise<BambuCert | null>;
  /** Bambu printers among the hosts (port 8883 + certificate). */
  probeAsync(hosts: string[], timeoutMs: number): Promise<BambuFound[]>;
  /** MQTT connection (kept open; reports come as onMessage events). Rejects on a wrong access code. */
  connectAsync(host: string, serial: string, code: string): Promise<boolean>;
  publishAsync(host: string, json: string): Promise<void>;
  disconnectAsync(host: string): Promise<void>;
  /** G-code file → .gcode.3mf on the printer's SD card (FTPS). */
  uploadAsync(host: string, code: string, uri: string, remoteName: string): Promise<{ filaments: number; size: number }>;
}

export default requireNativeModule<BambuLanModule>('BambuLan');
