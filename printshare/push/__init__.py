"""Push notifications and Live Activities (0.51.0, docs/PUSH.md).

- `apns.py`     Apple Push Notification service client (HTTP/2, token auth with the .p8 key) - cloud only.
- `relay.py`    the push relay on api.pocketprint3d.com: phones register their APNs tokens there and get an opaque
                handle; every PocketPrint3D server (cloud, home server, Home Assistant …) sends through the handle.
                The .p8 key never leaves the cloud, the token never reaches a home server, alert texts are end-to-end
                encrypted with a key only the phone and its server know.
- `notify.py`   per server: registered phones, which events they want, texts, Live Activity updates.
"""
