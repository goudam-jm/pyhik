# Maintenance roadmap

## Implemented in this branch

- Lazy explicit native loading and import without the vendor SDK.
- Python 3 text/path conversion, typed errors, and safe fixed-array conversion.
- Context-managed SDK/device ownership and ordered, retryable shutdown.
- Correct Windows scalar/pointer and per-API callback types.
- Reported channel-slot models; no fixed sixteen-channel worker assumption.
- Packaging under a provisional distinct distribution/import, excluding DLLs.
- Offline regression/failure tests, CI, migration guide and vendor-header probe.

## Before a public maintenance release

- Decide the source license and confirm package-name availability/ownership.
- Review vendor usage and redistribution conditions; choose and pin an SDK bundle.
- Run the ABI probe against that bundle and complete the device checklist.
- Record a tested compatibility matrix and review downstream migration impact.
- Use build/install verification and an intentional version tag. There is no
  automatic publishing workflow in this branch.

## Read-only ISAPI follow-up

The optional `hikvision_isapi` module now covers device information, capability
XML, reported streaming channels, JPEG snapshots and credential-free RTSP URL
construction. Its design uses mezz64/pyHik as an attributed reference, with
independently implemented transport/parsing and synthetic protocol tests. It
uses explicit HTTP(S) origins, Digest authentication and verified TLS defaults.
The native backend remains separately available without HTTP dependencies.

## Later feature development

Validate the read-only ISAPI slice using model-specific vendor documentation
and actual devices before advertising support. Then evaluate recording
search/download and events, keeping native functionality where needed.
Do not promise endpoint parity, async wrappers, Linux support, PTZ or playback
without implementation and real-device evidence.
