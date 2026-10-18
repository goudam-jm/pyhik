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

## Later feature development

ISAPI is a candidate primary interface for modern devices, with the native
backend retained where needed. That is a separate project stage. Begin with
model-specific vendor documentation and device information, capability discovery,
channels and snapshots; then evaluate recording search/download and events.
Do not promise endpoint parity, async wrappers, Linux support, PTZ or playback
without implementation and real-device evidence.
