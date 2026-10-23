# Third-party and upstream notices

## DDDA Local Coop

The executable inventory, static inspection and runtime status/guard adapters
and gameplay control/world adapters are adapted from work in
[thingolus/ddda-local-coop](https://github.com/thingolus/ddda-local-coop),
originally at `61ed1bf830141b75981babe362cef42579eb98e3` and now reviewed against
`e6a64c28d24bf4abda26887b0edeccc8bfd9b2a4`.
The source inventory is in `reuse-manifest.json`.

MIT License

Copyright (c) 2026 Thingolus and project contributors

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

## Installed dependencies

Dependencies are installed separately from the package lock. Their license
files remain in their distributions. No game files, external dinput8 project
implementation, Ghidra installation, Frida binary, or co-op DLL is vendored here.

## Asset format research

The ARC v7 reader/writer is an independent Python implementation informed by local DDDA archives and the public [Gibbed.MT ArchiveFile format implementation](https://github.com/gibbed/Gibbed.MT/blob/master/projects/Gibbed.MT.FileFormats/ArchiveFile.cs), copyright Rick (gibbed), distributed under its zlib license. No Gibbed source is copied or vendored. The supported unlabelled GMD schema was checked against local item-name data. Game assets and their rights remain with their owners; generated local test packages are excluded from Git and software releases.

Generated standalone SDK workspaces retain the pinned upstream MIT notice. The bridge builds MinHook from the upstream pinned dependency archive, including its original license files; these generated private sources and binaries are not shipped in this MCP package.
