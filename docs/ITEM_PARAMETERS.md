# Structured item parameter editing

Version 0.10.0, created by **Thingolus**, MIT licensed. All edits, repacks and test packages remain private until an existing profile operation is explicitly used to apply them.

The editor supports one precise gameplay-data format: **ITL2, version 20121105**, with a 16-byte header and 128-byte records. The locally inspected `etc/item/itemList` entry in `nativePC/rom/bbs_rpg.arc` has 1,901 records. The parser validates the exact version, reserved header, full file extent, row/item identities, alternate-item references and finite weights. Other versions and layouts are refused.

The binary layout was cross-checked against local data and [Chris Purnell's original `itl2xml` format research at commit `6e3e761`](https://github.com/chrispurnell/dd-tools/blob/6e3e76107ae67bf5efef8a3206bea54848b0e694/itl2xml.c). This project's parser/editor is an independent implementation. No external source, game assets or item-name tables are bundled.

## Workflow

1. `open_asset_archive(relative_path="nativePC/rom/bbs_rpg.arc")` creates a private snapshot.
2. `inspect_asset(operation="entries", artifact_id=..., query="itemList")` locates the entry. Use its observed index with `operation="extract"`.
3. `item_parameter_catalog` describes the supported fields and numeric/reference bounds.
4. `inspect_item_parameters(entry_id=..., item_id=43)` reads the selected item. Omit `item_id` to page through the table.
5. `edit_item_parameters(entry_id=..., edits=[{"item_id":43,"field":"mAddHp","expected":120,"value":121}])` writes a private replacement. Use values returned by inspection rather than assuming this example matches a modified installation.
6. `diff_item_parameters(before_id=..., after_id=...)` reports named changes and any changed bytes outside the reviewed schema.
7. Use the existing `repack_asset_archive`, `register_mod`, and `compose_mod_profile` tools. These steps create private artifacts without installing the change. Existing profile application/recovery remains separate.

## Supported fields

| Fields | Storage / supported values |
| --- | --- |
| `mAttack`, `mMagicAttack` | Separate unsigned 11-bit fields, 0–2047 |
| `mElementAttack` | Unsigned 10-bit field, 0–1023 |
| `mDefense`, `mMagicDefense` | Separate unsigned 10-bit fields, 0–1023 |
| `mAlterItemNo` | Signed 13-bit reference; only -1 or an existing item ID is accepted |
| `mWeight` | Finite float32, 0–1,000,000 |
| `mBuy`, `mSell` | Nonnegative signed 32-bit values |
| `mAddHp`, `mAddAp` | Signed 16-bit amount fields |

The native field names are retained. Numeric bounds establish representability and this editor's limits, not gameplay balance or all engine constraints. In-game effects, units, exceptional item rules and derived UI totals still require native verification. The editor does not rename, insert, remove or reorder items, and does not change unknown flags or model fields.

## Integrity and merging

Every edit includes an expected original value. Integer fields require integers; float values are normalized to their stored float32 precision. A patch is limited to 100 unique item/field pairs. Replacement values are read back, and every unselected bit is compared against the original, including neighboring bit-packed fields, padding and header bytes.

Sequential edits retain their original base and a reproducible cumulative patch. Item edits merge by `(item_id, field)` through the existing archive/profile pipeline. Independent changes to different fields in the same item can merge, including fields sharing a 32-bit word. Different values for the same field conflict. Before merging, each patch's declared edits must reproduce its stored bytes from the recorded base. Unknown or opaque replacements remain conflicts.

Repacking uses the existing ARC path: expected original hash, preservation of unchanged compressed entries and verification by decompression. The original installed archive is untouched by inspection/editing/repacking/profile composition.

## Validation and limits

`scripts/offline_workbench_smoke.py` exercised the actual local table through real MCP stdio: parsed 1,901 items, changed item 43's `mAddHp` from 120 to 121 privately, reported exactly one named change and zero unmodeled changed bytes, reversed the change to byte-identical original data, repacked/re-extracted the entry, and composed an unapplied private profile. The installed archive hash was unchanged. No game launch, input or save operation occurred.

Synthetic tests cover corrupt layouts, bounds, dangling references, nonfinite values, expected-value conflicts, neighboring-bit preservation, float round trips, chained edits, metadata corruption, three-way independent field merges, conflicting mods and private packaging.

This is the first gameplay-data codec. General XFS, skill, enemy and loot-table editing remains unsupported until its own format and invariants are reviewed. No gameplay effect of an edited item is claimed from file round trips.
