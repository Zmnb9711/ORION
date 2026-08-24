# SRS Radio reference provenance

This experimental tester implements wire facts audited from
DCS-SimpleRadioStandalone 2.4.0.0 at commit
`7694fa9b88889eb4494fd745d31f6f5249c03a0f`.

No GPL-licensed SRS source code is copied into this application. The reference
was used to verify numeric TCP message types, EAM response nesting, the UDP GUID
echo readiness gate, and the current 6-byte header + dynamic segments + 57-byte
fixed-tail packet layout. The deterministic 79-byte and 99-byte packet tests are
independently expressed protocol compatibility vectors.

## Bundled Opus binary

- Runtime: libopus 1.6.1, x64 Windows DLL
- Official source: `https://downloads.xiph.org/releases/opus/opus-1.6.1.tar.gz`
- Official source SHA-256: `6ffcb593207be92584df15b32466ed64bbec99109f007c82205f0194572411a1`
- Build: CMake 4.4.2 + Ninja 1.13.0 using Zig/Clang 0.15.2/20.1.2,
  Release, shared library, programs/tests disabled
- Bundled `opus.dll` SHA-256:
  `82b454192834e0afce0d5ce3c46f2deba653ac437f369d847ab8043a93157808`
- License: BSD 3-Clause; see `opus-BSD-3-Clause.txt`

## Resampler

- Python package: `samplerate==0.2.4`
- The package statically bundles libsamplerate in its platform wheel.
- Wrapper license: MIT; see `python-samplerate-MIT.txt`
- libsamplerate license: BSD 2-Clause; see `libsamplerate-BSD-2-Clause.txt`
