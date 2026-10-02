import { NativeModule, requireNativeModule } from 'expo';

export type WifiAddress = { address: string; prefix: number };
export type UdpAnswer = { address: string; data: string };

declare class LanDiscoveryModule extends NativeModule<{}> {
  /** The phone's IPv4 address on the Wi-Fi, null when it isn't on one. */
  wifiAddressAsync(): Promise<WifiAddress | null>;
  /** Send `message` to the targets (3×) and collect the answers for `timeoutMs`. */
  udpProbeAsync(message: string, port: number, targets: string[], timeoutMs: number): Promise<UdpAnswer[]>;
}

export default requireNativeModule<LanDiscoveryModule>('LanDiscovery');
