"""Feature-level research and lexical change-impact candidates. MIT, Thingolus."""

import posixpath
import re
from pathlib import PurePosixPath

from .common import ToolFailure

STOP_WORDS = {"the", "a", "an", "and", "or", "to", "for", "of", "with", "implement", "add", "support"}
SOURCE_EXTENSIONS = {".cpp", ".hpp", ".h", ".c", ".py", ".js"}
MAX_FILES = 1000
MAX_BYTES = 16 * 1024 * 1024


class Features:
    def __init__(self, source, knowledge, artifacts):
        self.source, self.knowledge, self.artifacts = source, knowledge, artifacts

    def investigate(self, feature, terms=None):
        if not isinstance(feature, str) or not feature.strip() or len(feature) > 256:
            raise ToolFailure("invalid_query", "Describe the feature in 1–256 characters.")
        if terms is None:
            terms = list(
                dict.fromkeys(
                    w.lower() for w in re.findall(r"[A-Za-z0-9_]+", feature) if w.lower() not in STOP_WORDS
                )
            )[:8]
        if (
            not isinstance(terms, list)
            or not 1 <= len(terms) <= 8
            or any(
                not isinstance(t, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_ -]{0,47}", t)
                for t in terms
            )
        ):
            raise ToolFailure(
                "invalid_query",
                "Use 1–8 explicit search terms of up to 48 letters, digits, spaces, underscores or hyphens.",
            )
        terms = list(dict.fromkeys(t.lower() for t in terms))
        self.source.verify()
        tree = self.source.tree()
        patterns = [(term, re.compile(re.escape(term).replace(r"\ ", r"[ _-]+"), re.I)) for term in terms]
        symbols = []
        for symbol in self.source.symbols():
            text = symbol["name"] + " " + " ".join(str(v) for v in symbol.get("research", {}).values())
            matched = [term for term, pattern in patterns if pattern.search(text)]
            if matched:
                symbols.append(
                    {
                        "name": symbol["name"],
                        "matched_terms": matched,
                        "sources": symbol["sources"],
                        "next_tool": {
                            "name": "investigate_symbol",
                            "arguments": {"symbol_name": symbol["name"]},
                        },
                    }
                )
        symbols.sort(key=lambda row: (-len(row["matched_terms"]), row["name"]))
        research, research_more, research_seen = [], False, set()
        for term in terms:
            found = self.knowledge.search(term, limit=4)
            research_more |= found["next_offset"] is not None
            for row in found["results"]:
                key = row["source"]["path"], row["source"]["line"]
                if key not in research_seen:
                    research_seen.add(key)
                    research.append(row)
        eligible = sorted(
            path
            for path in tree
            if PurePosixPath(path).suffix in SOURCE_EXTENSIONS or path == "CMakeLists.txt"
        )
        paths, total_bytes = [], 0
        skipped_large = []
        for path in eligible:
            size = tree[path][1]
            if size > 2 * 1024 * 1024:
                skipped_large.append(path)
                continue
            if len(paths) >= MAX_FILES or total_bytes + size > MAX_BYTES:
                continue
            paths.append(path)
            total_bytes += size
        blobs = self.source.read_many(paths)
        candidates, includes = [], []
        for path in paths:
            lines = blobs[path].decode("utf-8-sig", errors="replace").splitlines()
            hits, matched_terms, total_hits = [], set(), 0
            for index, line in enumerate(lines):
                matched = [term for term, pattern in patterns if pattern.search(line)]
                if matched:
                    total_hits += 1
                    matched_terms.update(matched)
                    if len(hits) < 3:
                        hits.append(
                            {
                                "source": self.source.reference(path, index + 1),
                                "excerpt": line[:350],
                                "excerpt_truncated": len(line) > 350,
                                "matched_terms": matched,
                            }
                        )
                match = re.match(r'\s*#\s*include\s*"([^"\n]+)"', line)
                if match:
                    target = match[1]
                    possibilities = {
                        posixpath.normpath(posixpath.join(posixpath.dirname(path), target)),
                        posixpath.normpath("include/" + target),
                        posixpath.normpath(target),
                    }
                    resolved = sorted(p for p in possibilities if p in tree)
                    includes.append(
                        {
                            "from": path,
                            "include": target,
                            "resolved_candidates": resolved,
                            "source": self.source.reference(path, index + 1),
                        }
                    )
            if hits:
                candidates.append(
                    {
                        "path": path,
                        "matched_terms": sorted(matched_terms),
                        "hits": hits,
                        "matching_lines": total_hits,
                        "omitted_matching_lines": total_hits - len(hits),
                        "role": "test_candidate"
                        if path.startswith("tests/") or "test" in PurePosixPath(path).stem
                        else "implementation_candidate",
                    }
                )
        candidates.sort(key=lambda row: (-len(row["matched_terms"]), -row["matching_lines"], row["path"]))
        selected = candidates[:60]
        selected_paths = {row["path"] for row in selected}
        edges = [
            edge
            for edge in includes
            if edge["from"] in selected_paths or selected_paths.intersection(edge["resolved_candidates"])
        ]
        test_candidates = [row["path"] for row in candidates if row["role"] == "test_candidate"]
        gaps = [
            "Feature feasibility and gameplay behavior require targeted investigation and native acceptance.",
            "Lexical matches and quoted includes do not prove call relationships, ownership or test coverage.",
        ]
        if not symbols:
            gaps.append("No matching known symbol; begin with source/research candidates or refine terms.")
        if not research:
            gaps.append("No indexed research passage matched these terms.")
        if not test_candidates:
            gaps.append("No lexical test candidate found; define regression tests for the intended behavior.")
        if len(paths) < len(eligible):
            gaps.append("Source scan budget omitted files; absence of a match is inconclusive.")
        summary = {
            "feature": feature,
            "source_commit": self.source.commit,
            "terms": terms,
            "symbol_candidates": len(symbols),
            "source_candidates": len(candidates),
            "test_candidates": len(test_candidates),
            "research_passages": len(research),
            "scanned_files": len(paths),
            "scanned_bytes": total_bytes,
            "omitted_files": len(eligible) - len(paths),
            "evidence_class": "static",
            "native_acceptance": "unverified",
        }
        data = {
            "summary": summary,
            "symbols": symbols[:20],
            "research": research[:20],
            "source_candidates": selected,
            "dependency_candidates": edges[:100],
            "test_candidates": test_candidates[:30],
            "evidence_gaps": gaps,
            "truncation": {
                "symbols": max(0, len(symbols) - 20),
                "source_candidates": max(0, len(candidates) - 60),
                "dependency_candidates": max(0, len(edges) - 100),
                "test_candidates": max(0, len(test_candidates) - 30),
                "research": max(0, len(research) - 20),
                "research_search_has_more": research_more,
                "oversized_files": skipped_large,
            },
            "suggested_validation": [
                {
                    "stage": "static",
                    "action": "Inspect candidate source passages and exact symbol bundles; verify proposed dependencies.",
                },
                {
                    "stage": "offline",
                    "action": "Add schema/decoder fixtures and boundary/error cases for new copied diagnostics; replay existing evidence.",
                },
                {
                    "stage": "build",
                    "action": "Run affected upstream tests and compare ABI/signatures against the reviewed contract.",
                },
                {
                    "stage": "native",
                    "action": "Validate behavior in an owned ready game using a reviewed scenario; keep this gate unverified until observed.",
                },
            ],
        }
        receipt = self.artifacts.put(
            "feature_investigation",
            data,
            {
                "source_commit": self.source.commit,
                "evidence_class": "static",
                "recipe": "investigate_feature",
            },
        )
        return {
            **receipt,
            "summary": summary,
            "evidence_gaps": gaps,
            "leading_symbols": [row["name"] for row in symbols[:5]],
            "leading_source_paths": [row["path"] for row in selected[:5]],
        }
