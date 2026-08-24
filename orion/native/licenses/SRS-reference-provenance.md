# Production SRS Radio protocol and native dependency provenance

ORION's production implementation independently expresses wire facts audited
against DCS-SimpleRadioStandalone 2.4.0.0 at commit
`7694fa9b88889eb4494fd745d31f6f5249c03a0f`.

No GPL-licensed SRS source code or assemblies are copied into ORION. The audit
established numeric TCP message types, EAM response nesting, UDP GUID echo,
server multicast behavior, the 6-byte header plus dynamic segments plus
57-byte fixed tail, the 11-slot `PlayerRadioInfoBase`, and ExternalAudioClient
slot 1 behavior. Production tests independently express the 79-byte and
99-byte compatibility vectors.

## Bundled Opus binary

- Runtime: libopus 1.6.1, x64 Windows DLL
- Source: `https://downloads.xiph.org/releases/opus/opus-1.6.1.tar.gz`
- Source SHA-256: `6ffcb593207be92584df15b32466ed64bbec99109f007c82205f0194572411a1`
- Build: CMake 4.4.2 + Ninja 1.13.0 with Zig/Clang 0.15.2/20.1.2,
  Release shared library, programs/tests disabled
- Bundled DLL SHA-256:
  `82b454192834e0afce0d5ce3c46f2deba653ac437f369d847ab8043a93157808`
- License: BSD 3-Clause

## Resampler

- Python package: `samplerate==0.2.4`
- Its platform wheel statically bundles libsamplerate
- Wrapper license: MIT
- libsamplerate license: BSD 2-Clause
