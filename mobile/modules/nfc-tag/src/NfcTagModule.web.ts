import { registerWebModule, NativeModule } from 'expo';

import type { RawTag } from './NfcTagModule';

// Web build (development previews only): no NFC.
class NfcTagModule extends NativeModule<{}> {
  status(): 'on' | 'off' | 'none' {
    return 'none';
  }
  async readAsync(_timeoutMs: number): Promise<RawTag> {
    throw new Error('no NFC in the browser');
  }
  async cancelAsync(): Promise<void> {}
}

export default registerWebModule(NfcTagModule, 'NfcTagModule');
