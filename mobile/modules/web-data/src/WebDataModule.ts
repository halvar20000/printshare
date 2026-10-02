import { NativeModule, requireNativeModule } from 'expo';

declare class WebDataModule extends NativeModule<{}> {
  /** Delete all cookies and website data of the app's WebViews (logs out of Printables). */
  clearAsync(): Promise<boolean>;
}

export default requireNativeModule<WebDataModule>('WebData');
