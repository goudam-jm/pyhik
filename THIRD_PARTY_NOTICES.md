# Reference project and attribution

The ISAPI feature selection, public method names and endpoint mapping were
informed by [John Mihalic's mezz64/pyHik](https://github.com/mezz64/pyHik), reviewed
at commit `bc2c0dff65295a70f0af6e7914219525d37023b4` (version 0.4.8), especially
`pyhik/isapi.py`, its README and its tests. That code is MIT licensed. This
repository's ISAPI transport, immutable XML models and synthetic test fixtures
were implemented here; the reference package is not vendored or imported.

For clarity about the historical relationship:

- `goudam-jm/pyhik` is the original 2014 native HCNetSDK wrapper.
- `mezz64/pyhik-1` is a GitHub fork of that repository, created June 6, 2018.
- `mezz64/pyHik` has its own history beginning December 2, 2016, and publishes the
  PyPI `pyHik` package. The later fork establishes a connection, but does not by
  itself establish that the current ISAPI implementation derives from the native
  wrapper. No claim of endorsement or collaboration is made.

The reference's MIT notice is reproduced below for attribution. It does not
choose a license for this repository's original or new source, or grant rights
to Hikvision's vendor binaries.

## mezz64/pyHik license notice

The MIT License (MIT)

Copyright (c) John Mihalic 2016

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Reference source headers additionally state:
Copyright (c) 2016-2026 John Mihalic <https://github.com/mezz64>
