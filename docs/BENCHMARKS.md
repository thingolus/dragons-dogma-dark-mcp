# Paired development-tool workflows

Version 0.3.0 by **Thingolus**, measured 22 October 2026 at 11:59 UTC on this Windows machine. Run `.venv/Scripts/python.exe scripts/benchmark_workflows.py` to reproduce. Detailed samples stay in ignored `artifacts/validation/workflow-benchmark.json`.

The running MCP server reduced median tool latency in these four small workflows. It returned larger responses and did not reduce the number of calls. This experiment measures tool execution, not overall AI development speed or model-token savings.

| Workflow | Direct command median | MCP median | Direct response bytes | MCP response bytes |
| --- | ---: | ---: | ---: | ---: |
| Read copied runtime ABI | 32.809 ms | 2.152 ms | 579 | 1,940 |
| Locate `pawn_delete` RVA | 35.462 ms | 4.651 ms | 542 | 1,565 |
| Fingerprint executable | 117.463 ms | 44.214 ms | 153 | 919 |
| Find menu ownership evidence | 40.105 ms | 3.714 ms | 431 | 5,993 |

Each route used one operation per task, repeated five times in alternating order: 20 direct operations and 20 MCP calls. MCP startup plus tool discovery took 913.693 ms and is separate from the table. The server stays alive across tasks; direct Git/Python commands start a process each time. The first MCP request for a component includes its lazy initialization, and OS caches were already populated. These are medians from a small local sample, not cold-machine or statistical performance guarantees.

The direct route uses `git show` for the ABI header, targeted `git grep` for the symbol and research phrase, and a standalone Python/pefile SHA-256 inventory. It does not import the MCP package. The MCP route uses real stdio calls to `read_source`, `lookup_symbol`, `inspect_build`, and `search_knowledge` against the same inputs. Both routes have prewritten commands, so the experiment does not measure time an AI spends choosing commands or interpreting results.

Correctness checks require exact ABI lines, the same symbol RVA, and matching executable hash/size/architecture/image base. Research retrieval checks pinned provenance and nonempty relevant evidence; exact-phrase grep and ranked word search are deliberately not treated as identical result sets. MCP responses include provenance and structured metadata absent from the concise direct outputs. Byte counts cover one structured MCP envelope, not both SDK text and structured copies, and are not token counts.

The source pin is `61ed1bf830141b75981babe362cef42579eb98e3`; game SHA-256 is `19facc2642f79a09d14ce55eace5f228161f2f8bab60ec67eb3c6196cc6277b8`. No game was launched, and no build or Ghidra analysis ran during timing. A separate paired AI task-completion study would still be needed to measure reasoning time, actual model usage, solution quality, and end-to-end development gains.
