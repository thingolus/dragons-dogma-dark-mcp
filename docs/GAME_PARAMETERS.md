# Named game parameters

Version 0.11.1. Created by **Thingolus**, MIT licensed.

`inspect_game_parameters`, `edit_game_parameters`, and `diff_game_parameters` operate on extracted private `asset_blob` artifacts. The editor identifies the serialized format from its bytes, returns named field paths, and exposes whether each field is editable. Every edit requires the expected old value. It preserves record sizes, opaque headers, unknown fields, references and bytes outside the selected fields; it reparses and checks the result before storing it.

| Format | Coverage | Editing boundary |
| --- | --- | --- |
| XFS 0x109 | Self-describing classes, names, arrays, numeric fields and supported vectors | Numeric fields use serialized types; strings, pointers, class structure and vector padding stay read-only. A serialized name/type does not establish safe gameplay ranges. |
| PRPZ + XFS | Enemy common parameters using a 12-byte wrapper | Preserves the complete wrapper and applies the same XFS rules. Original Japanese field names are retained. |
| SKL 0x200 | Normal/custom/ability skill tables | Skill costs and required job levels; IDs and relationship fields stay read-only. |
| LOT 16 | Reviewed enemy, placeable, light, NPC and target layouts | HP/attack/defense/magic ratios and their override flags, positions, angles, scale, selected distances/timers and experience. Unknown record/target classes refuse the whole edit. IDs, script paths, AI relationships and loot references stay read-only. |
| IST 0 | Fixed 40-byte loot records | Quantities and probability values; item references, record identity and table structure stay read-only. |
| ITL2 20121105 | Eleven allowlisted item fields | Separate `inspect_item_parameters` / `edit_item_parameters` tools; see [item parameters](ITEM_PARAMETERS.md). |

The global atlas finds parameter resources across archives. For example, search for `charparam/em`, `shl_param`, `itemSetTbl`, or a known stage path; select an occurrence, then inspect the returned entry. Names and archive placement differ by resource. Never assume a logical name is globally unique.

```text
build_asset_index() → job_status() → index artifact
search_assets(index_id, query="charparam/em") → selected asset ID
extract_indexed_asset(index_id, asset_id) → entry_id
inspect_game_parameters(entry_id, query="") → named fields and editability
edit_game_parameters(entry_id, edits=[{path, expected, value}]) → changed entry
diff_game_parameters(before_id, after_id) → named changes and unmodeled-byte count
repack_asset_archive(archive_id, replacements=...) → private archive
```

Use the exact fields returned by inspection, including array indices. Edits are cumulative and retain their original base hash. Mod profile composition merges disjoint named-field changes to the same resource and reports conflicting values instead of silently choosing a winner. Repack and inspect again before applying a journaled profile. A successful structural round trip does not prove that a gameplay change behaves as intended; use a restored fixture trial for that.

Limits include 32 MiB per entry, 100 edits per operation, 200,000 fields, 100,000 parsed XFS nodes, depth 64 and 10,000 LOT records. Unknown versions, overflowing extents, nonfinite values, unsupported structures, stale expected values and unsafe reference edits are rejected.

## Format research

These parsers are independent implementations based on observed local formats and primary format research in [Chris Purnell's dd-tools, pinned source](https://github.com/chrispurnell/dd-tools/tree/6e3e76107ae67bf5efef8a3206bea54848b0e694), particularly `xfs2txt.cc`, `xfs_types.h`, `skl2xml.c`, `lot2xml.c` and `ist2xml.c`. Those third-party source files and game tables are not redistributed. TEX research also consulted [ArisenTools at the pinned revision](https://github.com/mhvuze/ArisenTools/tree/8f2ffd71ee0a46f81e04090ff70342789fba9846); no source of uncertain license is included.
