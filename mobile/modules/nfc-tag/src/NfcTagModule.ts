import { NativeModule, requireNativeModule } from 'expo';

export type RawTag = { uid: string; data: string; blockSize: number };

declare class NfcTagModule extends NativeModule<{}> {
  /** "on", "off" (switched off in the phone settings) or "none" (no NFC) */
  status(): 'on' | 'off' | 'none';
  /** Wait for an NFC-V tag and read its memory (base64); rejects ERR_NFC_TIMEOUT / _OFF / _UNAVAILABLE / _CANCELLED / _READ. */
  readAsync(timeoutMs: number): Promise<RawTag>;
  cancelAsync(): Promise<void>;
}

export default requireNativeModule<NfcTagModule>('NfcTag');
