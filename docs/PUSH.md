# Push notifications and Live Activities (0.51.0)

Concept: project file `analysen/konzept-benachrichtigungen-live-activity.md`. API: `docs/API.md` "Push notifications".

## Pieces
| Where | File | What |
|---|---|---|
| cloud | `printshare/push/apns.py` | APNs HTTP/2 client, ES256 JWT from the .p8 key |
| cloud | `printshare/push/relay.py` | APNs token ↔ handle (`push-relay.db` next to the cloud DB), message checks, limits |
| every server | `printshare/push/notify.py` | phones per account (`push.db`), events → encrypted alerts, Live Activity updates |
| every server | `printshare/api.py` | events from job tracking, sending/waking, AI failure detection, bridge events; endpoints |

```
phone ──token──▶ relay (/push/register) ──handle──▶ phone ──handle + key──▶ its server (/api/push/devices)
server event ──encrypted alert / activity state──▶ relay (/push/send) ──.p8──▶ APNs ──▶ phone
```

## Events
- Home server: the job loop polls every printer every 30 s (`_track_jobs`) → finished / cancelled / paused / error,
  prints started elsewhere (+ push-to-start); `send()` → print not started, `needs_decision`; `failure_watch` → AI alert.
- Cloud: the same `_track_jobs` from the 60 s bridge loop and `/api/observe`; bridge events `watch.alert` and
  `job.decision` (bridge 0.51.0+).
- Bridges send no pushes themselves (nobody registers there) but forward the AI alert and the decision to the cloud.

## Setting up the cloud (once, Thomas/Dominique)
1. Apple developer portal → Keys → new key with "Apple Push Notifications service (APNs)" → download the .p8 (once!).
2. Put it on the cloud server as `/srv/pocketprint3d/config/apns.p8` (mode 0600; that folder is the container's
   `/config`) and add to `/opt/pocketprint3d/secrets.env`: `PRINTSHARE_APNS_KEY=/config/apns.p8`, `PRINTSHARE_APNS_KEY_ID=<key id>`,
   `PRINTSHARE_APNS_TEAM_ID=<team id>` (`PRINTSHARE_APNS_TOPIC` defaults to the iOS bundle id), then `docker compose up -d`.
   Create the key for "Sandbox & Production": Xcode builds register as sandbox, TestFlight as production.
3. App ID in the developer portal: enable "Push Notifications" (and "Time Sensitive Notifications" for the app).
Without a key the relay answers `503 push_unavailable` and nothing else changes.

## Not verified
Nothing has reached a real iPhone yet: APNs is only tested with a fake (payload shapes from Apple's docs), the iOS side
needs a TestFlight build with the push entitlement.
