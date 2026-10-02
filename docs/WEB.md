# PocketPrint3D in the browser (2026-10-02)

The same app as on the phone, for desktop browsers, with the same cloud account: **https://app.pocketprint3d.com**.

## How it is built
- **One code base:** the Expo app in `mobile/`, exported for the web (`expo export --platform web`) with
  `EXPO_PUBLIC_WEB_SAME_ORIGIN=1`. The server image builds it in its first stage (`Dockerfile`, stage `webapp`) and
  keeps it in `/opt/webapp`.
- **Same address as the API:** the cloud server serves the web app at `/` (and its routes `/printers`, `/job/…` →
  `index.html`; `_expo/static/…` cached for a year, `index.html` never). Caddy answers for `api.` and `app.pocketprint3d.com`
  with the same container, so the browser never makes cross-site requests (no CORS).
- Home servers keep their classic web page (`printshare/web`) for now; the plan is to serve this web app there too.

## Login and security
- **Session in an HttpOnly cookie** (`pp3d_session`, `Secure`, `SameSite=Strict`, 180 days): `POST /api/auth/login` with
  `cookie: true` sets it and answers `token: null`. Page scripts can't read the session, so an injected script can't
  steal it. The app keeps `token: ""` and sends no Authorization header (`lib/api.ts` `authHeaders`, `WEB_APP`).
- **Changes need `X-Requested-With: pocketprint3d`** when the session comes from the cookie (403 otherwise): a form or
  link on another site can't send it, and SameSite=Strict keeps the cookie off cross-site requests anyway.
- Logout / account deletion clear the cookie.
- **Headers on the web app:** Content-Security-Policy (`default-src 'self'`, no plugins, `frame-ancestors 'none'`,
  `form-action 'self'`; images from any https address for model pictures), `X-Frame-Options: DENY`, `nosniff`,
  `Referrer-Policy`, `Permissions-Policy` (no camera/microphone/location). Known compromise: `script-src` allows
  `'unsafe-inline'` and `cdn.jsdelivr.net`, because the 3D viewers run as srcdoc iframes that load three.js from there.
  Next step: bundle three.js and serve the viewer pages from our own address, then drop both.

## What works in the browser
| | Browser |
|---|---|
| Login, search (Printables, Thingiverse), MakerWorld pages, prepare, slice, 2D/3D preview, jobs, cloud spools, own profiles | ✅ |
| Printers behind a **bridge**: status, camera pictures, controls, printing | ✅ |
| Printers only the phone reaches on the Wi-Fi | "Nur Handy" + hint; review screen offers **G-code download** and the bridge instead of "Drucken" |
| Dragging a model file onto the page | ✅ (home screen; STL, 3MF, OBJ, STEP) |
| Wi-Fi printer search, NFC spools, Printables login inside the app, own server | hidden / phone only |

## Next (docs/BRIDGE.md, product plan)
1. Spool bookings in the account instead of on the phone (bridge books when a print finishes).
2. "Send from OrcaSlicer": an OctoPrint-compatible upload per printer, so desktop-sliced prints go through PocketPrint3D too.
3. The same web app on home servers instead of the classic page.
