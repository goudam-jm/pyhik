# Changelog

## 0.1.0.dev0 — unreleased maintenance branch

### Read-only ISAPI follow-up

Adds optional `hikvision_isapi` device information, capability XML, stream
listing, JPEG retrieval and credential-free RTSP URLs. Uses Digest auth,
explicit HTTP(S) origins, verified TLS, typed errors and hardened XML parsing.
Adds synthetic HTTP/authentication tests and documents mezz64/pyHik as a pinned,
attributed reference, including the historical fork relationship. Native SDK
behavior remains unchanged; neither backend claims real-device validation.

### Native maintenance baseline

Modernizes the original 2014 Windows native prototype with Python 3 packaging,
lazy explicit SDK loading, context-managed sessions, typed native errors, safe
text/path conversion, corrected Windows ABI/callback definitions, and ordered
resource cleanup. Adds offline regression tests, CI, ABI verification tools,
examples, migration notes and an explicit hardware-unverified status.

The provisional distribution is pyhik-hcnetsdk; the installed module is
hikvision_native. DLLs and the source-checkout pyhik shim are not distributed.
This is not a PyPI release or a claim of device compatibility.
