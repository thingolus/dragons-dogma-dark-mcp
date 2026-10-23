# Live development expansion

Creator: Thingolus. Work order: gameplay harness, broader copied diagnostics,
reviewed runtime tracing with code references, persistent investigation memory,
then regression isolation using those capabilities.

## Acceptance established 23 October 2026

Owned session `c6dc8f470f114b25909955ecd1c71844` loaded the existing inn save
through observed native menus. Stage 220/generation 1; both actors observed.
Neutral-input job `4d656341a36942fdb41609fae4c8a715` completed with eight samples,
zero faults/native errors, unchanged world, and confirmed input release.
Private artifact `2c906eba11d7437da2a5d198c61496b1`, SHA-256
`d16654c95982947e269219afe663b93ab5f2e7033f04fd001e8ca8239551d5bc`.
Death-refusal read returned an empty valid ring; performance read returned an
inactive collector. These do not establish combat or movement acceptance.

The physical controller mask was 1 and player pads were unassigned. Movement
must retain its existing admission checks. The game was stopped without saving,
the temporary developer-input deployment was rolled back to verified originals,
and the shared-life state was byte-identical. No Windows prompt needed action.

The harness must distinguish native world readiness from native-menu navigation:
an AI client can perform the latter through observed Computer Use. It must never
blindly confirm menus, claim a frozen copied snapshot is fresh, or call unknown
save-loading functions. A timeout or inconsistent trial is inconclusive evidence.

All five implementation stages are delivered in v0.7. See [the workflow guide](LIVE_DEVELOPMENT.md) and [current validation](VALIDATION.md) for the expanded native results, exact scope and remaining combat/controller acceptance.
