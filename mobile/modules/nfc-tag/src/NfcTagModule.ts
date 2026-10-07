import { NativeModule, requireNativeModule } from 'expo';

/** kind "nfca": NTAG sticker or a Bambu spool's MIFARE tag - only the chip number (data empty) */
export type RawTag = { uid: string; data: string; blockSize: number; kind?: 'nfcv' | 'nfca' };

declare class NfcTagModule extends NativeModule<{}> {
  /** "on", "off" (switched off in the phone settings) or "none" (no NFC) */
  status(): 'on' | 'off' | 'none';
  /** Wait for an NFC-V tag (memory as base64) or an NFC-A tag (chip number only); rejects ERR_NFC_TIMEOUT / _OFF / _UNAVAILABLE / _CANCELLED / _READ. */
  readAsync(timeoutMs: number): Promise<RawTag>;
  cancelAsync(): Promise<void>;
}

export default requireNativeModule<NfcTagModule>('NfcTag');
