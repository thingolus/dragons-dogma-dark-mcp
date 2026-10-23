"""Typed MCP interface for Thingolus's DDDA development toolkit."""

import asyncio
import inspect
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, Field

from . import __version__
from .artifacts import Artifacts
from .binary import Binary
from .build import Builds
from .common import ToolFailure, utc_now
from .comparison import Comparisons
from .compatibility import Compatibility
from .config import Config
from .control import ACTIONS, Controls
from .death import decode_death
from .deployment import Deployment
from .diagnostics import Diagnostics
from .features import Features
from .harness import Harness
from .investigation import Investigations
from .jobs import Jobs
from .knowledge import Knowledge
from .memory import InvestigationMemory
from .patches import Patches
from .recipes import MOVEMENT, catalog
from .regression import Regressions
from .saves import Saves
from .scenarios import Diagnosis, Scenarios
from .session import Sessions
from .source import Source
from .timeline import Timelines
from .tracing import Tracing


class Envelope(BaseModel):
    schema_version: Literal[1] = 1
    request_id: str
    operation: str
    captured_at: str
    duration_ms: float
    success: bool
    provenance: dict[str, Any]
    data: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


Result = Annotated[CallToolResult, Envelope]
PageSize = Annotated[int, Field(ge=1, le=20)]
Offset = Annotated[int, Field(ge=0, le=10000)]
Read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
Write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
Replace = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)


class SourceEdit(BaseModel):
    path: str
    expected_sha256: str | None = None
    content: Annotated[str, Field(max_length=131072)]


class Application:
    def __init__(self, config: Config, config_path: Path | None = None):
        self.config = config
        self.source = Source(config)
        self.knowledge = Knowledge(self.source)
        self.binary = Binary(config)
        self.artifacts = Artifacts(config)
        self.diagnostics = Diagnostics(self.artifacts)
        self.timelines = Timelines(self.artifacts)
        self.features = Features(self.source, self.knowledge, self.artifacts)
        self.jobs = Jobs(config)
        self.sessions = Sessions(config, self.artifacts, config_path)
        self.builds = Builds(config, self.source, self.artifacts)
        self.deployment = Deployment(config)
        self.saves = Saves(config)
        self.harness = Harness(config, self.artifacts, self.sessions, self.saves)
        self.tracing = Tracing(self.source, self.sessions, self.builds, self.artifacts)
        self.memory = InvestigationMemory(config, self.source, self.artifacts)
        self.regressions = Regressions(
            config, self.source, self.artifacts, self.builds, self.deployment, self.harness
        )
        self.controls = Controls(self.sessions, self.artifacts)
        self.scenarios = Scenarios(self.harness, self.controls, self.artifacts)
        self.diagnosis = Diagnosis(self.source, self.artifacts)
        self.patches = Patches(self.source, self.artifacts)
        self.regressions.scenarios = self.scenarios
        self.regressions.diagnosis = self.diagnosis
        self.regressions.memory = self.memory
        self.comparisons = Comparisons(config, self.source, self.artifacts)
        self.compatibility = Compatibility(config, self.source, self.artifacts)
        self.investigations = Investigations(
            config, self.source, self.knowledge, self.binary, self.builds, self.artifacts
        )
        from .assets import Assets
        from .behavior import Behaviors
        from .mods import Mods
        from .sdk import SDK
        from .suites import Suites

        self.assets = Assets(config, self.artifacts)
        self.mods = Mods(config, self.artifacts, self.assets)
        self.sdk = SDK(config, self.source, self.artifacts, self.builds)
        self.behaviors = Behaviors(self)
        self.suites = Suites(self)

    def project_status(self) -> dict:
        verified = self.source.verify()
        status = self.source.git("status", "--porcelain", "--untracked-files=no").decode()
        return {
            "name": "Dragons Dogma Dark MCP",
            "version": __version__,
            "creator": "Thingolus",
            "license": "MIT",
            "profile": self.config.settings.profile,
            "upstream": verified,
            "upstream_worktree_dirty": bool(status),
            "dirty_worktree_used": False,
            "upstream_compatibility": self.compatibility.status(),
            "knowledge_documents": len(self.source.knowledge_paths()),
            "capabilities": [
                "pinned_source",
                "knowledge_search",
                "symbol_lookup",
                "pe_analysis",
                "investigation_bundles",
                "source_revision_comparison",
                "named_build_comparison",
                "death_refusal_diagnostics",
                "diagnostic_adapter_catalog",
                "offline_regression_replay",
                "event_timelines",
                "feature_investigations",
                "upstream_compatibility_gate",
                "jobs",
                "artifacts",
                "owned_native_sessions",
                "bounded_traces",
                "isolated_builds",
                "ghidra_export",
                "deployment_receipts",
                "save_backups",
                "save_recovery",
                "scenario_catalog",
                "reviewed_movement_recipes",
                "gameplay_checkpoints",
                "expiring_gameplay_control",
                "callback_world_inspection",
                "scenario_predicates",
                "failure_diagnosis",
                "isolated_patch_verification",
                "verified_build_cache",
                "copied_gameplay_diagnostics",
                "reviewed_function_tracing",
                "persistent_investigation_memory",
                "repeated_regression_campaigns",
                "behavior_differentials",
                "versioned_cpp_sdk",
                "standalone_offline_observation",
                "private_arc_gmd_editing",
                "fixture_profile_matrices",
                "journaled_mod_profiles",
            ],
            "live_requirements": "development profile, Frida extra, exact game, no existing DDDA process; co-op requires a manifest-owned runtime, standalone a verified bridge and disabled competing loaders",
            "limits": self.config.settings.limits.model_dump(),
            "native_acceptance": "Not inferred from static or simulated checks.",
        }

    async def invoke(self, operation: str, function, *args, **kwargs) -> CallToolResult:
        started = time.monotonic()
        fields = {
            "request_id": uuid.uuid4().hex,
            "operation": operation,
            "captured_at": utc_now(),
            "provenance": {"source_commit": self.source.commit, "adapter_version": __version__},
        }
        try:
            if inspect.iscoroutinefunction(function):
                data = await function(*args, **kwargs)
            else:
                data = await asyncio.to_thread(function, *args, **kwargs)
            envelope = Envelope(
                **fields, duration_ms=round((time.monotonic() - started) * 1000, 3), success=True, data=data
            )
        except ToolFailure as exc:
            envelope = Envelope(
                **fields,
                duration_ms=round((time.monotonic() - started) * 1000, 3),
                success=False,
                error={"code": exc.code, "message": str(exc), **getattr(exc, "details", {})},
            )
        except (OSError, ValueError, KeyError) as exc:
            envelope = Envelope(
                **fields,
                duration_ms=round((time.monotonic() - started) * 1000, 3),
                success=False,
                error={"code": "local_data_error", "message": str(exc)[:1000]},
            )
        except Exception:
            logging.exception("Unhandled operation failure: %s", operation)
            envelope = Envelope(
                **fields,
                duration_ms=round((time.monotonic() - started) * 1000, 3),
                success=False,
                error={"code": "internal_error", "message": "Operation failed; inspect server stderr."},
            )
        document = envelope.model_dump(exclude_none=True)
        encoded = json.dumps(document, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode()) > self.config.settings.limits.max_inline_result_bytes:
            try:
                artifact = self.artifacts.put(
                    "tool_result",
                    {"summary": {"operation": operation}, "result": document},
                    fields["provenance"],
                )
            except (ToolFailure, OSError) as exc:
                document = Envelope(
                    **fields,
                    duration_ms=envelope.duration_ms,
                    success=False,
                    error={"code": getattr(exc, "code", "artifact_write_failed"), "message": str(exc)[:1000]},
                ).model_dump(exclude_none=True)
                return CallToolResult(
                    content=[TextContent(type="text", text=json.dumps(document, ensure_ascii=False))],
                    structuredContent=document,
                    isError=True,
                )
            document = Envelope(
                **fields,
                duration_ms=envelope.duration_ms,
                success=envelope.success,
                data={
                    "inline_truncated": True,
                    **artifact,
                    "message": "Full result available through read_artifact.",
                },
                error=envelope.error,
            ).model_dump(exclude_none=True)
            encoded = json.dumps(document, ensure_ascii=False)
        return CallToolResult(
            content=[TextContent(type="text", text=encoded)],
            structuredContent=document,
            isError=not document["success"],
        )

    async def close(self):
        await self.jobs.close()
        await self.sessions.close()


def create_server(config: Config, config_path: Path | None = None) -> tuple[MCPServer, Application]:
    app = Application(config, config_path)

    @asynccontextmanager
    async def lifespan(server):
        try:
            yield app
        finally:
            await app.close()

    mcp = MCPServer(
        "Dragons Dogma Dark MCP",
        version=__version__,
        lifespan=lifespan,
        instructions="Local DDDA development toolkit by Thingolus. Start with project_status. Source results use the pinned commit; historical claims retain their original scope. Live operations require an explicitly configured development profile. Never treat synthetic results as physical-controller acceptance.",
    )

    @mcp.tool(annotations=Read)
    async def project_status() -> Result:
        """Inspect project credits, immutable source identity, available adapters and operating limits."""
        return await app.invoke("project_status", app.project_status)

    @mcp.tool(annotations=Read)
    async def verify_upstream() -> Result:
        """Verify all 42 reviewed source blob identities without changing the co-op checkout."""
        return await app.invoke("verify_upstream", app.source.verify)

    @mcp.tool(annotations=Read)
    async def inspect_build() -> Result:
        """Hash and inspect configured DDDA.exe without launching, attaching, or patching it."""
        return await app.invoke("inspect_build", app.binary.inventory)

    @mcp.tool(annotations=Read)
    async def search_knowledge(
        query: str, topic: str = "", offset: Offset = 0, limit: PageSize = 10
    ) -> Result:
        """Search pinned research/documents. topic filters source paths; offsets paginate results."""
        return await app.invoke("search_knowledge", app.knowledge.search, query, topic, offset, limit)

    @mcp.tool(annotations=Read)
    async def lookup_symbol(
        name_or_rva: str, offset: Offset = 0, limit: Annotated[int, Field(ge=1, le=10)] = 5
    ) -> Result:
        """Look up named symbols or hexadecimal RVAs with signature bytes and research evidence."""
        return await app.invoke("lookup_symbol", app.knowledge.lookup, name_or_rva, offset, limit)

    @mcp.tool(annotations=Read)
    async def read_source(
        path: str,
        start_line: Annotated[int, Field(ge=1)] = 1,
        limit: Annotated[int, Field(ge=1, le=100)] = 60,
    ) -> Result:
        """Read a bounded passage from a tracked text file at the immutable upstream commit."""
        return await app.invoke("read_source", app.source.read_lines, path, start_line, limit)

    @mcp.tool(annotations=Read)
    async def inspect_binary(
        mode: Literal["bytes", "disassembly", "strings", "references"],
        value: str,
        size: Annotated[int, Field(ge=1, le=1024)] = 128,
        offset: Offset = 0,
        limit: Annotated[int, Field(ge=1, le=100)] = 25,
    ) -> Result:
        """Inspect file-backed x86 PE data. value is an RVA or literal string; references are candidates."""
        return await app.invoke("inspect_binary", app.binary.inspect, mode, value, size, offset, limit)

    @mcp.tool(annotations=Read)
    async def session_status() -> Result:
        """Report owned/external game sessions without attaching or writing research mailboxes."""
        return await app.invoke("session_status", app.sessions.status)

    @mcp.tool(annotations=Write)
    async def start_session(
        backend: Literal["coop", "standalone"] = "coop", bridge_id: str | None = None
    ) -> Result:
        """Start an owned offline game; standalone requires a passed research bridge build and disabled competing proxy loaders."""

        async def submit():
            config.require_development()
            return app.jobs.submit("start_session", lambda: app.sessions.start(backend, bridge_id))

        return await app.invoke("start_session", submit)

    @mcp.tool(annotations=Replace)
    async def stop_session() -> Result:
        """Stop only this server's owned game without saving; cancel an active trace job first."""
        return await app.invoke("stop_session", app.sessions.stop)

    @mcp.tool(annotations=Read)
    async def runtime_snapshot(
        group: Literal[
            "runtime",
            "performance",
            "death_refusals",
            "pawn_resources",
            "pawn_vocation",
            "pawn_actions",
            "inventory_menu",
            "shared_life",
            "target_hud",
        ] = "runtime",
    ) -> Result:
        """Read copied, ABI-checked state from this server's owned guarded game. Never supplies input."""
        return await app.invoke("runtime_snapshot", app.sessions.snapshot, group)

    @mcp.tool(annotations=Read)
    async def decode_death_diagnostic(
        words: Annotated[
            list[Annotated[int, Field(strict=True, ge=0, le=4294967295)]],
            Field(min_length=520, max_length=520),
        ],
    ) -> Result:
        """Replay one copied down-refusal ring offline. Returns evaluated predicates, reasons and chronology without pointers; no game access or gameplay proof."""
        return await app.invoke("decode_death_diagnostic", decode_death, words)

    @mcp.tool(annotations=Read)
    async def list_diagnostic_adapters() -> Result:
        """List reviewed diagnostic schemas, ABI versions and live requirements. No game access."""
        return await app.invoke("list_diagnostic_adapters", app.diagnostics.catalog)

    @mcp.tool(annotations=Write)
    async def decode_diagnostic(
        adapter: Literal[
            "runtime",
            "performance",
            "death_refusals",
            "pawn_resources",
            "pawn_vocation",
            "pawn_actions",
            "inventory_menu",
            "shared_life",
            "target_hud",
        ],
        payload: dict[str, Any],
    ) -> Result:
        """Validate/redact supplied copied fields and save a private replay fixture. Death payload is {words: [...]}; runtime/performance use catalog schemas. Evidence is offline_supplied, never live proof."""
        return await app.invoke("decode_diagnostic", app.diagnostics.save, adapter, payload)

    @mcp.tool(annotations=Write)
    async def replay_diagnostic(artifact_id: str) -> Result:
        """Run the current decoder on a stored diagnostic and compare the recorded result without game access."""
        return await app.invoke("replay_diagnostic", app.diagnostics.replay, artifact_id)

    @mcp.tool(annotations=Write)
    async def build_event_timeline(
        artifact_ids: Annotated[list[str], Field(min_length=1, max_length=16)],
    ) -> Result:
        """Normalize existing runtime/scenario/diagnostic artifacts into bounded event streams and rule findings. Incompatible clocks and sessions remain separate."""
        return await app.invoke("build_event_timeline", app.timelines.build, artifact_ids)

    @mcp.tool(annotations=Read)
    async def query_event_timeline(
        artifact_id: str,
        kind: str = "",
        actor: str = "",
        text: str = "",
        offset: Offset = 0,
        limit: Annotated[int, Field(ge=1, le=100)] = 25,
    ) -> Result:
        """Filter and paginate timeline events and their findings by kind, actor or literal text."""
        return await app.invoke(
            "query_event_timeline", app.timelines.query, artifact_id, kind, actor, text, offset, limit
        )

    @mcp.tool(annotations=Write)
    async def replay_event_timeline(artifact_id: str) -> Result:
        """Rebuild a timeline with current decoders/rules, verify source hashes and compare recorded events/findings."""
        return await app.invoke("replay_event_timeline", app.timelines.replay, artifact_id)

    @mcp.tool(annotations=Write)
    async def investigate_feature(
        feature: Annotated[str, Field(min_length=1, max_length=256)],
        terms: Annotated[list[str], Field(min_length=1, max_length=8)] | None = None,
    ) -> Result:
        """Gather pinned research, symbol/source/test candidates, quoted-include dependencies, evidence gaps and validation steps for a future feature. Lexical candidates are not verified call graphs."""
        return await app.invoke("investigate_feature", app.features.investigate, feature, terms)

    @mcp.tool(annotations=Write)
    async def capture_trace(
        seconds: Annotated[float, Field(ge=0.1, le=120)] = 5,
        interval_ms: Annotated[int, Field(ge=100, le=2000)] = 250,
    ) -> Result:
        """Record a bounded runtime trace as an asynchronous job, with no controller input."""

        async def submit():
            config.require_development()
            return app.jobs.submit("capture_trace", lambda: app.sessions.capture(seconds, interval_ms))

        return await app.invoke("capture_trace", submit)

    @mcp.tool(annotations=Write)
    async def run_scenario(
        recipe: Literal[
            "observe_idle",
            "neutral_input",
            "dismiss_title",
            "p1_step_forward",
            "p1_step_right",
            "p2_step_forward",
        ],
        seconds: Annotated[float, Field(ge=0.1, le=120)] = 5,
    ) -> Result:
        """Run a reviewed recipe with cleanup. Movement uses a fixed 300ms pulse once/session; seconds only controls observe/neutral. See list_scenarios for gates and evidence."""

        async def submit():
            config.require_development()
            if recipe == "dismiss_title":
                return app.jobs.submit("run_scenario", app.sessions.dismiss_title)
            if recipe in MOVEMENT:
                return app.jobs.submit("run_scenario", lambda: app.sessions.movement(recipe))
            return app.jobs.submit(
                "run_scenario", lambda: app.sessions.capture(seconds, 250, recipe == "neutral_input")
            )

        return await app.invoke("run_scenario", submit)

    @mcp.tool(annotations=Read)
    async def list_scenarios() -> Result:
        """List reviewed recipes, fixed input/duration limits and native acceptance status."""
        return await app.invoke("list_scenarios", catalog)

    @mcp.tool(annotations=Read)
    async def job_status(job_id: str) -> Result:
        """Read a durable job receipt. A previous server's unfinished job is outcome_unknown."""
        return await app.invoke("job_status", app.jobs.status, job_id)

    @mcp.tool(annotations=Write)
    async def investigate_symbol(
        symbol_name: Annotated[str, Field(min_length=1, max_length=128)],
        query: Annotated[str, Field(max_length=256)] = "",
        include_decompilation: bool = False,
    ) -> Result:
        """Bundle exact-symbol research, source, disassembly and candidate callers in a static job. Optional Ghidra export requires development profile; no game launch."""

        async def submit():
            if include_decompilation:
                config.require_development()
            return app.jobs.submit(
                "investigate_symbol",
                lambda: app.investigations.bundle(symbol_name, query, include_decompilation),
            )

        return await app.invoke("investigate_symbol", submit)

    @mcp.tool(annotations=Read)
    async def check_upstream_compatibility(candidate_commit: str | None = None) -> Result:
        """Compare local HEAD or a full upstream SHA against the reviewed adapter contract: signatures, exports, layouts, defaults and build inputs. Never fetches, repins or deploys."""
        return await app.invoke("check_upstream_compatibility", app.compatibility.check, candidate_commit)

    @mcp.tool(annotations=Read)
    async def compare_source_revisions(
        before_commit: str,
        after_commit: str,
        offset: Offset = 0,
        limit: Annotated[int, Field(ge=1, le=50)] = 50,
    ) -> Result:
        """Compare full committed SHAs in the configured source repo: file hashes, bounded diffs, lexical function contexts and signatures. Never reads dirty files."""
        return await app.invoke(
            "compare_source_revisions",
            app.comparisons.compare_source,
            before_commit,
            after_commit,
            offset,
            limit,
        )

    @mcp.tool(annotations=Read)
    async def compare_builds(before_name: str, after_name: str) -> Result:
        """Compare installed/named build manifests, DLL exports/imports/sections and settings. Report compatibility risks without deployment or gameplay claims."""
        return await app.invoke("compare_builds", app.comparisons.compare_builds, before_name, after_name)

    @mcp.tool(annotations=Write)
    async def cancel_job(job_id: str) -> Result:
        """Cancel a job owned by this server and wait for its cleanup receipt."""
        return await app.invoke("cancel_job", app.jobs.cancel, job_id)

    @mcp.tool(annotations=Read)
    async def read_artifact(
        artifact_id: str,
        start_line: Annotated[int, Field(ge=1)] = 1,
        limit: Annotated[int, Field(ge=1, le=100)] = 40,
    ) -> Result:
        """Read a paginated evidence artifact by ID; arbitrary filesystem paths are not accepted."""
        return await app.invoke("read_artifact", app.artifacts.read_page, artifact_id, start_line, limit)

    @mcp.tool(annotations=Read)
    async def compare_runs(before_id: str, after_id: str) -> Result:
        """Compare compatible recorded metrics, showing changed inputs without asserting causation."""
        return await app.invoke("compare_runs", app.artifacts.compare, before_id, after_id)

    @mcp.tool(annotations=Write)
    async def build_and_test(
        configuration: Literal["Debug", "Release"] = "Debug",
        test_group: Literal["all", "core"] = "all",
        patch_id: str | None = None,
    ) -> Result:
        """Build pinned Win32 co-op source in an isolated directory and parse CTest JUnit results."""

        async def submit():
            config.require_development()
            return app.jobs.submit(
                "build_and_test", lambda: app.builds.build(configuration, test_group, patch_id=patch_id)
            )

        return await app.invoke("build_and_test", submit)

    @mcp.tool(annotations=Write)
    async def decompile_symbol(symbol_name: str) -> Result:
        """Export one signature-pinned function from an existing hash-matched Ghidra database."""

        async def submit():
            config.require_development()
            return app.jobs.submit("decompile_symbol", lambda: app.builds.decompile(symbol_name))

        return await app.invoke("decompile_symbol", submit)

    @mcp.tool(annotations=Write)
    async def prepare_deployment(candidate_name: str) -> Result:
        """Prepare a concrete hash/ownership receipt for a candidate named in trusted local config."""
        return await app.invoke("prepare_deployment", app.deployment.prepare, candidate_name)

    @mcp.tool(annotations=Replace)
    async def apply_deployment(receipt_id: str) -> Result:
        """Apply a prepared candidate with the game closed, verified backups and a durable journal."""
        return await app.invoke("apply_deployment", app.deployment.apply, receipt_id)

    @mcp.tool(annotations=Replace)
    async def rollback_deployment(receipt_id: str) -> Result:
        """Restore original owned files from an applied/interrupted receipt; refuse changed files."""
        return await app.invoke("rollback_deployment", app.deployment.rollback, receipt_id)

    @mcp.tool(annotations=Write)
    async def backup_saves() -> Result:
        """Back up and hash .sav files in explicitly configured save roots, with DDDA closed."""
        return await app.invoke("backup_saves", app.saves.backup)

    @mcp.tool(annotations=Replace)
    async def restore_saves(backup_id: str) -> Result:
        """Journal a verified restore with DDDA closed; retain undo copies and block launch until complete."""
        return await app.invoke("restore_saves", app.saves.restore, backup_id)

    @mcp.tool(annotations=Read)
    async def save_restore_status() -> Result:
        """Find unfinished save transactions, including a game-wide recovery blocker."""
        return await app.invoke("save_restore_status", app.saves.status)

    @mcp.tool(annotations=Replace)
    async def recover_save_restore(
        receipt_id: str, action: Literal["resume", "rollback"] = "rollback"
    ) -> Result:
        """Resume or roll back an interrupted save restore; refuse unrelated save changes."""
        return await app.invoke("recover_save_restore", app.saves.recover, receipt_id, action)

    @mcp.tool(annotations=Write)
    async def record_investigation_note(
        title: str,
        body: str,
        kind: Literal["hypothesis", "finding", "failed_attempt", "open_question"] = "hypothesis",
        status: Literal["open", "supported", "refuted", "resolved", "superseded"] = "open",
        evidence_ids: list[str] | None = None,
        source_paths: list[str] | None = None,
        note_id: str | None = None,
        expected_revision: Annotated[int, Field(ge=0)] = 0,
    ) -> Result:
        """Append a private investigation revision with exact evidence hashes; never overwrite prior claims."""
        return await app.invoke(
            "record_investigation_note",
            app.memory.record,
            title,
            body,
            kind,
            status,
            evidence_ids,
            source_paths,
            note_id,
            expected_revision,
        )

    @mcp.tool(annotations=Read)
    async def read_investigation_note(
        note_id: str, revision: Annotated[int, Field(ge=1)] | None = None
    ) -> Result:
        """Read a current or historical claim and check whether its referenced evidence changed."""
        return await app.invoke("read_investigation_note", app.memory.read, note_id, revision)

    @mcp.tool(annotations=Read)
    async def search_investigations(
        query: str = "",
        kind: str | None = None,
        status: str | None = None,
        offset: Offset = 0,
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
    ) -> Result:
        """Search latest private hypotheses, findings, failed attempts and open questions."""
        return await app.invoke(
            "search_investigations", app.memory.search, query, kind, status, offset, limit
        )

    @mcp.tool(annotations=Write)
    async def create_regression_campaign(
        checkpoint_id: str,
        revisions: Annotated[list[str], Field(min_length=2, max_length=16)],
        repeats: Literal[2, 3] = 2,
        recipe: str = "observe_idle",
    ) -> Result:
        """Plan repeated endpoint/midpoint gameplay trials over exact ordered commits; inconsistent results stay inconclusive."""
        return await app.invoke(
            "create_regression_campaign", app.regressions.create, checkpoint_id, revisions, repeats, recipe
        )

    @mcp.tool(annotations=Replace)
    async def advance_regression_campaign(
        campaign_id: str, action: Literal["prepare", "evaluate", "abort"] = "prepare"
    ) -> Result:
        """Prepare builds/deployment/known save; evaluate runs readiness/tests/rollback. Client loads observed native menus between phases. Abort recovers originals."""

        async def submit():
            config.require_development()
            return app.jobs.submit(
                "regression_campaign", lambda: app.regressions.advance(campaign_id, action)
            )

        return await app.invoke("advance_regression_campaign", submit)

    @mcp.tool(annotations=Read)
    async def regression_campaign_status(campaign_id: str) -> Result:
        """Read durable campaign state, trial evidence and recovery receipts."""
        return await app.invoke("regression_campaign_status", app.regressions.status, campaign_id)

    @mcp.tool(annotations=Read)
    async def list_function_traces() -> Result:
        """List reviewed function-entry observers and immutable research provenance."""
        return await app.invoke("list_function_traces", app.tracing.catalog)

    @mcp.tool(annotations=Write)
    async def trace_function(
        symbol: Literal["native_stamina_apply", "goblin_health_subtract"],
        seconds: Annotated[float, Field(ge=0.1, le=30)] = 2,
        decompile: bool = False,
    ) -> Result:
        """Capture reviewed read-only native events and optional Ghidra export; verify hook removal and retain partial evidence."""

        async def submit():
            config.require_development()
            return app.jobs.submit("trace_function", lambda: app.tracing.capture(symbol, seconds, decompile))

        return await app.invoke("trace_function", submit)

    @mcp.tool(annotations=Write)
    async def create_gameplay_checkpoint(backup_id: str, trace_id: str, label: str) -> Result:
        """Register a hash-checked save and advancing native world trace while the game is closed."""
        return await app.invoke(
            "create_gameplay_checkpoint", app.harness.checkpoint, backup_id, trace_id, label
        )

    @mcp.tool(annotations=Replace)
    async def launch_gameplay_checkpoint(checkpoint_id: str) -> Result:
        """Restore a registered save with an undo backup and launch an owned game. Client navigates observed Load Game menus."""

        async def submit():
            config.require_development()
            return app.jobs.submit("launch_gameplay_checkpoint", lambda: app.harness.launch(checkpoint_id))

        return await app.invoke("launch_gameplay_checkpoint", submit)

    @mcp.tool(annotations=Write)
    async def run_gameplay_harness(
        checkpoint_id: str,
        recipe: Literal[
            "observe_idle",
            "neutral_input",
            "movement_pair",
            "attack_pair",
            "jump_pair",
            "menu_roundtrip",
            "interaction_menu",
        ] = "observe_idle",
        seconds: Annotated[float, Field(ge=0.5, le=30)] = 2,
        readiness_timeout: Annotated[int, Field(ge=1, le=120)] = 30,
        stop_after: bool = True,
    ) -> Result:
        """Wait for advancing checkpoint callbacks, capture a bounded scenario, retain verdict/evidence and clean up."""

        async def submit():
            config.require_development()
            return app.jobs.submit(
                "gameplay_harness",
                lambda: app.scenarios.run(checkpoint_id, recipe, seconds, readiness_timeout, stop_after),
            )

        return await app.invoke("run_gameplay_harness", submit)

    @mcp.tool(annotations=Read)
    async def gameplay_catalog() -> Result:
        """List fixed input actions, reusable scenarios and their exact evidence limits."""
        return await app.invoke(
            "gameplay_catalog",
            lambda: {**app.scenarios.catalog(), "actions": sorted(ACTIONS), "control_modes": ["pair", "solo"]},
        )

    @mcp.tool(annotations=Write)
    async def control_gameplay(
        operation: Literal["claim", "release", "status"], mode: Literal["pair", "solo"] = "pair"
    ) -> Result:
        """Claim expiring pair control or solo P1 control with pawn AI; mode applies to claim. Release verifies callbacks or stops the owned process."""

        async def perform():
            config.require_development()
            if operation == "status":
                return await app.sessions._request("control_status")
            return await (app.controls.claim(mode) if operation == "claim" else app.controls.release())

        return await app.invoke("control_gameplay", perform)

    @mcp.tool(annotations=Write)
    async def gameplay_action(
        action: str, role: Literal[0, 1] = 0, duration_ms: Annotated[int, Field(ge=50, le=1000)] = 250
    ) -> Result:
        """Execute one fixed action under an acquired lease; report observed movement/action/menu changes separately from input delivery."""
        return await app.invoke("gameplay_action", app.controls.action, action, role, duration_ms)

    @mcp.tool(annotations=Write)
    async def inspect_world(seconds: Annotated[float, Field(ge=0.2, le=10)] = 2) -> Result:
        """Capture callback-only party vitals, inventories and bounded nearby enemy identities; quests explicitly unavailable."""
        return await app.invoke("inspect_world", app.controls.world, seconds)

    @mcp.tool(annotations=Write)
    async def diagnose_scenario(
        artifact_id: str, related_ids: Annotated[list[str] | None, Field(max_length=8)] = None
    ) -> Result:
        """Locate the first observed predicate divergence and link logs, source and optional trace/Ghidra artifacts without asserting causality."""
        return await app.invoke("diagnose_scenario", app.diagnosis.analyze, artifact_id, related_ids)

    @mcp.tool(annotations=Write)
    async def create_source_patch(
        label: str, edits: Annotated[list[SourceEdit], Field(min_length=1, max_length=16)]
    ) -> Result:
        """Create hash-checked C/C++ replacements applied only to isolated build sources. Never changes the co-op working tree."""
        return await app.invoke(
            "create_source_patch", app.patches.create, label, [edit.model_dump() for edit in edits]
        )

    @mcp.tool(annotations=Write)
    async def create_patch_verification(
        checkpoint_id: str, patch_id: str, recipe: str = "observe_idle", repeats: Literal[1, 2, 3] = 1
    ) -> Result:
        """Create baseline/candidate trials with isolated builds, selected scenario, diagnosis, rollback and investigation memory. Advance through the campaign tools."""
        return await app.invoke(
            "create_patch_verification",
            app.regressions.create_verification,
            checkpoint_id,
            patch_id,
            recipe,
            repeats,
        )

    @mcp.resource("ddda://project/status")
    async def project_resource() -> str:
        result = await app.invoke("project_status", app.project_status)
        return result.content[0].text

    @mcp.resource("ddda://build/current")
    async def build_resource() -> str:
        result = await app.invoke("inspect_build", app.binary.inventory)
        return result.content[0].text

    @mcp.resource("ddda://symbols/{name}")
    async def symbol_resource(name: str) -> str:
        result = await app.invoke("lookup_symbol", app.knowledge.lookup, name)
        return result.content[0].text

    @mcp.resource("ddda://runs/{run_id}/summary")
    async def run_resource(run_id: str) -> str:
        result = await app.invoke("artifact_summary", app.artifacts.summary, run_id)
        return result.content[0].text

    from .workbench import register_tools

    register_tools(mcp, app)
    return mcp, app
