import { registerWebModule, NativeModule } from 'expo';

// Web build (development previews only): the page runs in an iframe of another site - nothing to clear here.
class WebDataModule extends NativeModule<{}> {
  async clearAsync(): Promise<boolean> {
    return false;
  }
}

export default registerWebModule(WebDataModule, 'WebDataModule');
