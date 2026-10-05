import { registerWebModule, NativeModule } from 'expo';

import type { BambuCert, BambuEvents, BambuFound } from './BambuLanModule';

// Web build (browser app, previews): a browser can't open MQTT/FTPS connections - Bambu printers go through a bridge.
const unsupported = () => Promise.reject(new Error('Bambu printers are reached through a bridge in the browser'));

class BambuLanModule extends NativeModule<BambuEvents> {
  async certAsync(_host: string): Promise<BambuCert | null> { return null; }
  async probeAsync(_hosts: string[], _timeoutMs: number): Promise<BambuFound[]> { return []; }
  connectAsync(_h: string, _s: string, _c: string): Promise<boolean> { return unsupported(); }
  publishAsync(_h: string, _j: string): Promise<void> { return unsupported(); }
  async disconnectAsync(_h: string): Promise<void> {}
  uploadAsync(_h: string, _c: string, _u: string, _n: string): Promise<{ filaments: number; size: number }> { return unsupported(); }
}

export default registerWebModule(BambuLanModule, 'BambuLanModule');
