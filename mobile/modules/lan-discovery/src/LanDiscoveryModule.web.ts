import { registerWebModule, NativeModule } from 'expo';

import type { UdpAnswer, WifiAddress } from './LanDiscoveryModule';

// Web build (development previews only): browsers can't send UDP. Tests may set globalThis.__lanDiscovery.
type Mock = { wifi?: WifiAddress | null; udp?: UdpAnswer[] };
const mock = () => (globalThis as { __lanDiscovery?: Mock }).__lanDiscovery;

class LanDiscoveryModule extends NativeModule<{}> {
  async wifiAddressAsync(): Promise<WifiAddress | null> {
    return mock()?.wifi ?? null;
  }
  async udpProbeAsync(_message: string, _port: number, _targets: string[], timeoutMs: number): Promise<UdpAnswer[]> {
    const m = mock();
    if (!m) return [];
    await new Promise(r => setTimeout(r, Math.min(timeoutMs, 300)));
    return m.udp ?? [];
  }
}

export default registerWebModule(LanDiscoveryModule, 'LanDiscoveryModule');
