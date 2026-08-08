# Elysium Master Application — Implementation Plan (Pre-Coding Deliverable)

**Status:** Draft for review, Revision 3. No application code has been written yet. This document is the gate described in LLD §1 — implementation (Phase 1) starts only after this is reviewed and approved.

**Revision 3 changes:** Revision 2 incorporated the 8 architectural/schema corrections from `implementation_improvments.md`. Revision 3 resolves the four follow-up clarifying questions raised by that review: reason edits now use a dedicated `reason_notes` collection so `audit_events` is never mutated after insert, under any circumstance (a stricter model than Revision 2's in-place-update approach); the Disable-Account inventory threshold, hard break-locking rule, and baked-in-installer credential distribution are all confirmed exactly as designed. Full changelog at the end of this document.

**Inputs used:**
- `Elysium_Master_Application_Spec(1) (1).md` (LLD, 33 sections) — authoritative on all behavior.
- Existing reference project `Elysium Card LookUp` (`app.py`, `db.py`, `bulk_import.py`, `cache_images.py`, `ElysiumCardLookup.spec`) — reused where practical per LLD §26.
- Clarifications from product owner (2026-08-07): see §0.
- `implementation_improvments.md` (2026-08-07): 8 corrections applied in this revision — see §0.1 and the changelog.

---

## 0. Clarifications received (locks in the design below)

| Question | Decision |
|---|---|
| Per-buyer / per-color-slot bidding inside a break | **Not tracked.** Each break stores one `break_gross` number (total money that break brought in). At stream end, the streamer also enters one `final_stream_gross` for the whole stream. This matches LLD §14/§15 and §28's explicit exclusion of "per-slot break sale entry." Whatnot handles the actual slot bidding; Elysium only records totals per break and per stream. |
| Break size | **Flexible**, per LLD §14.2–14.3. No enforced "always 3 packs" rule; a break is whatever grouped pack quantities the streamer selects. |
| Atlas environment | **Not yet provisioned.** Config/connection code will be built against standard MongoDB Atlas conventions (connection string via env var / encrypted local settings, TLS required) with placeholder values. Real cluster/user/IP-allowlist details will be supplied later — nothing here is blocked on that except the *execution* of the bootstrap script and transaction tests (see §12). |
| Seed data / streamer roster | **Start empty.** No hardcoded admin or streamer accounts. The bootstrap script only creates database structure (collections, validators, indexes, singleton lock/settings docs). A separate one-time `create_admin.py` CLI creates the very first admin interactively; every other account is created afterward through the app itself. |
| **End-user distribution** (added this revision) | **Streamers are not developers.** The app must ship as a double-click Windows installer/executable. No streamer ever installs Python, PyCharm, or any dependency, and no streamer ever sees or enters a MongoDB connection string. See §13. |

### 0.1 Corrections applied this revision

Per `implementation_improvments.md`, received after initial review:

1. Merge `GLOBAL_STREAM` + `PRICE_REFRESH` into one atomically-checked `GLOBAL_OPERATIONS` lock document — the two-document design had a genuine start-stream/start-refresh race.
2. Redesign TCGCSV refresh around category/group batching instead of one request per product, and define exact `subTypeName` price-record resolution/ambiguity rules.
3. Shorten streamer database names to a generated short key instead of embedding the full UUID.
4. Correct the master-inventory invariant so a negative streamer discrepancy balance never implies negative *physical* company inventory.
5. Make `resolved_pack_price` nullable so `price_status: UNRESOLVED` is representable without a fake price value.
6. Store sealed-product images as a shared `image_url`, not a machine-local path, with a local cache layer per computer.
7. Require the Disable Account action to route through Decommissioning whenever a streamer holds any inventory.
8. Add an explicit `audit_service.edit_reason(...)` operation and define exactly how "append-only but editable reason" reconciles.

---

## 1. Proposed Repository Structure

```text
elysium/
  main.py                          # entrypoint: shows login screen first
  config.py                        # env/config loading, no secrets committed
  bootstrap/
    init_database.py               # idempotent: DBs, collections, validators, indexes, singleton docs
    create_admin.py                # interactive one-time first-admin CLI
    provision_streamer_db.py       # shared helper: creates a new streamer's Mongo DB + collections
  ui/
    login.py                       # username/password + Continue as Guest
    shell.py                       # main window, role-based nav, dashboard status bar
    dashboard.py
    card_lookup.py                 # refactored from app.py's card grid/filter UI
    inventory_master.py            # admin: master inventory screen
    inventory_streamer.py          # streamer: My Inventory / admin: view any streamer
    products.py                    # admin: product catalog CRUD
    prices.py                      # shared sealed prices view + refresh + manual entry
    streams.py                     # start stream, active stream workspace, end-stream review
    breaks.py                      # break tile grid, plus/minus controls (used inside streams.py)
    reports.py                     # report browser + CSV export triggers
    users.py                       # admin: account management
    decommissioning.py             # admin: decommission initiate/approve
    discrepancies.py               # admin: discrepancy list/resolve
    audit.py                       # admin: audit history browser, incl. reason-edit action
    account.py                     # change own password, view own profile
  services/
    mongo_client.py                # session/client management, transaction retry helper
    auth_service.py                # login, password hashing/verification, role checks, user_id + streamer_database_key generation
    product_service.py
    pricing_service.py             # TCGCSV group-batched fetch + price-priority resolution
    inventory_service.py           # claim/return/add/reduce, invariant checks
    lock_service.py                # single GLOBAL_OPERATIONS lock: stream + price-refresh sub-states
    stream_service.py              # start/end/cancel/force-cancel, snapshotting
    break_service.py               # create/edit/end/delete break, availability calc
    correction_service.py          # completed-stream admin corrections, shortage-split logic
    decommission_service.py
    discrepancy_service.py
    audit_service.py               # writes audit_events; owns edit_reason(...)
    report_service.py              # report queries
    scryfall_service.py            # local Scryfall bulk refresh orchestration
    sealed_image_cache_service.py  # downloads/caches product.image_url locally per computer
  repositories/
    master_repository.py           # elysium_master collections
    price_repository.py            # elysium_prices collections
    streamer_repository.py         # parametrized by streamer_database_name
  local_card/
    db.py                          # adapted from existing db.py (safe-swap rebuild)
    bulk_import.py                 # adapted from existing bulk_import.py
    image_cache.py                 # adapted from existing cache_images.py (card images)
    paths.py                       # resolves %LOCALAPPDATA%\ElysiumMasterApp\... locations
  local_assets/
    image_cache_core.py            # generic URL-download-and-cache helper shared by card images and sealed-product images
  models/
    users.py
    products.py
    inventory.py
    prices.py
    streams.py
    breaks.py
    audit.py
    reason_notes.py                # new this revision
    locks.py                       # models global_operations
    discrepancies.py
    decommission.py
  security/
    credential_store.py            # keyring-backed (Windows Credential Manager)
    password_hashing.py            # argon2id
  exports/
    csv_exporter.py                # background-thread CSV writer
    report_definitions.py          # one definition per report in LLD §20.4/§20.5
tests/
  unit/                            # pure logic, no DB
  integration/                     # against local replica-set Mongo (transactions)
  acceptance/                      # 1:1 mapped to LLD §29.1–29.20, plus extension tests in §11.1
  ui/                              # pytest-qt smoke tests
packaging/
  ElysiumMasterApplication.spec    # PyInstaller, replaces ElysiumCardLookup.spec
  installer.iss                    # Inno Setup script producing the Windows installer (see §13)
docs/
  IMPLEMENTATION_PLAN.md           # this document
requirements.txt
pyproject.toml
.env.example
```

**Reuse mapping** (existing → new) is detailed in §8.

---

## 2. MongoDB Databases and Collection Schemas

Three logical groups, matching LLD §5.3/§22:

```text
elysium_master                     — one deployment-wide database
elysium_prices                     — one deployment-wide database
elysium_s_<streamer_database_key>  — one database per streamer, created dynamically
```

`streamer_database_key` is a short, immutable, collision-resistant token generated once and stored on the user's record — see §2.4 for why this replaced the full-UUID naming from Revision 1.

### 2.1 `elysium_master`

#### `users`
| Field | Type | Notes |
|---|---|---|
| `_id` | string (UUID) | immutable user id, used everywhere as `streamer_id`/`performed_by` |
| `username` | string | unique, editable |
| `password_hash` | string | Argon2id hash, never plaintext |
| `roles` | array<string> | subset of `["admin","streamer"]` |
| `streamer_database_key` | string \| null | short immutable key, generated iff `"streamer"` in `roles` — **new this revision** |
| `streamer_database_name` | string \| null | derived: `elysium_s_<streamer_database_key>`, cached for convenience/display |
| `is_active` | bool | |
| `decommission_status` | string \| null | `NONE` \| `PENDING` \| `APPROVED` |
| `created_at`, `created_by` | datetime, string | |
| `updated_at` | datetime | |
| `password_reset_at` | datetime \| null | |
| `disabled_at` | datetime \| null | |

#### `products`
| Field | Type | Notes |
|---|---|---|
| `_id` | string | `product_id`, generated slug e.g. `dominaria-united-draft-booster` |
| `name` | string | |
| `set_name` | string | |
| `set_code` | string \| null | |
| `booster_type` | string | `DRAFT` \| `SET` \| `COLLECTOR` \| `PLAY` — `PLAY` added in Phase 3 for current/new sets, see §2.6 |
| `language` | string | default `"English"` |
| `english_confirmed` | bool | required true to save (§8.2) |
| `packs_per_box` | int | > 0 |
| `tcgcsv_category_id` | string | **new this revision** — `1` for Magic; needed to fetch the right TCGCSV group dataset |
| `tcgcsv_group_id` | string | **new this revision** — identifies the TCGCSV "group" (set) this product's prices live in |
| `loose_pack_tcgcsv_product_id` | string | unique — the `productId` to look up within the group dataset |
| `box_tcgcsv_product_id` | string | unique — same, for the box product |
| `image_url` | string | **changed this revision** (was `image_reference`, a local path) — shared source URL, see §2.5 |
| `release_date` | date \| null | |
| `is_active` | bool | catalog active/inactive |
| `created_at`, `created_by`, `updated_at`, `updated_by` | | |

#### `inventory_current` (master)
| Field | Type | Notes |
|---|---|---|
| `_id` | string | = `product_id` (1:1) |
| `product_id` | string | duplicate of `_id` for query convenience |
| `total_packs` | int | ≥ 0 always — **physical** company packs, see corrected invariant in §4.6 |
| `unassigned_packs` | int | ≥ 0 always — physical, unclaimed |
| `version` | int | optimistic concurrency |
| `updated_at` | datetime | |

#### `streamer_allocations`
| Field | Type | Notes |
|---|---|---|
| `_id` | ObjectId | |
| `streamer_id` | string | |
| `product_id` | string | |
| `current_packs` | int | may go negative — represents a ledger shortage, **not** physical negative stock; see §4.6 |
| `version` | int | |
| `updated_at` | datetime | |

Unique compound `(streamer_id, product_id)`.

#### `global_operations` — **replaces the two-document `global_locks` design from Revision 1**

One singleton document holding both lock states so acquisition of either is atomic against the other:

| Field | Type | Notes |
|---|---|---|
| `_id` | `"GLOBAL_OPERATIONS"` | fixed |
| `stream_active` | bool | |
| `stream_id` | string \| null | |
| `streamer_id` | string \| null | |
| `streamer_database_name` | string \| null | |
| `stream_started_at` | datetime \| null | |
| `last_heartbeat_at` | datetime \| null | used for crash/resume UI |
| `price_refresh_active` | bool | |
| `refresh_session_id` | string \| null | |
| `refresh_started_by` | string \| null | |
| `refresh_started_at` | datetime \| null | |
| `version` | int | optimistic concurrency / conflict detection |
| `updated_at` | datetime | |

See §4.2 for why one document instead of two fixes the race condition, and §4.4 for recovery.

#### `audit_events` (append-only, **truly immutable — never updated after insert, see §4.5**)
| Field | Type |
|---|---|
| `_id` | ObjectId |
| `event_id` | string UUID |
| `action_type` | string enum, see LLD §19.3 list, plus `REASON_EDITED` |
| `performed_by` | string (user_id) |
| `role` | string |
| `timestamp` | datetime |
| `product_id`, `streamer_id`, `stream_id`, `break_id` | string \| null |
| `quantity_change` | int \| null |
| `amount_change` | Decimal128 \| null |
| `before_values`, `after_values` | object |
| `reason` | string \| null — **immutable snapshot** of the reason text at the moment this event was created; never edited afterward |
| `reason_note_id` | string \| null — **new this revision** — if this action type supports reason editing, points at the live `reason_notes` document holding the current text (§2.1.1) |
| `related_transaction_id` | string (app-generated correlation id per operation) |
| `status` | `SUCCESS` \| `FAILURE` \| `REVERSED` \| `CORRECTED` |

#### `reason_notes` — **new this revision**

Holds the one place a "reason" is allowed to change, so `audit_events` itself never needs an `UpdateOne`. Created alongside the originating `audit_events` document for the two action types that have no other live document to hold an editable reason (`MASTER_INVENTORY_REMOVED`, `STREAMER_INVENTORY_RETURNED` — see §4.5 for why corrections/force-cancel/discrepancies don't need this collection).

| Field | Type | Notes |
|---|---|---|
| `_id` | string UUID | `reason_note_id`, referenced from the originating `audit_events` document |
| `action_type` | string | e.g. `MASTER_INVENTORY_REMOVED`, `STREAMER_INVENTORY_RETURNED` |
| `streamer_id` | string \| null | owner for permission checks; `null` for master-only actions (admin-only editable) |
| `product_id` | string \| null | |
| `current_text` | string | the text shown in the UI as "the reason" |
| `history` | array<{text, edited_by, edited_at}> | starts with one entry at creation; a new entry is appended on every edit, so the full history lives here, not on `audit_events` |
| `created_at`, `created_by` | | |
| `updated_at` | datetime | |

#### `inventory_discrepancies`
| Field | Type |
|---|---|
| `_id` | ObjectId |
| `discrepancy_id` | string UUID |
| `streamer_id`, `product_id` | string |
| `type` | `NEGATIVE_INVENTORY` (choice A: streamer ledger allowed negative) \| `UNDEDUCTED_SHORTAGE` (choice C: ledger clamped at 0, shortage tracked separately) — semantics fixed precisely in §4.6 |
| `quantity` | int (magnitude) |
| `source` | `STREAM_CORRECTION` \| `DECOMMISSION` \| `MANUAL` |
| `related_stream_id` | string \| null |
| `status` | `OPEN` \| `RESOLVED` |
| `created_at`, `created_by` | |
| `resolved_at`, `resolved_by`, `resolution_note` | nullable |

#### `decommission_requests`
| Field | Type |
|---|---|
| `_id` | ObjectId |
| `request_id` | string UUID |
| `streamer_id` | string |
| `initiated_by`, `initiated_at` | |
| `status` | `PENDING` \| `APPROVED` \| `CANCELED` |
| `snapshot_of_allocations_at_initiation` | array<{product_id, current_packs}> |
| `approved_by`, `approved_at` | nullable |
| `notes` | string \| null |

#### `app_settings`
| Field | Type |
|---|---|
| `_id` | `"GLOBAL"` |
| `schema_version` | int |
| `stale_card_data_hours` | int, default 24 |
| `currency` | `"USD"` |
| `created_at`, `updated_at` | |

### 2.2 `elysium_prices`

#### `current_prices`
| Field | Type |
|---|---|
| `_id` | string = `product_id` |
| `product_id` | string |
| `tcgcsv_category_id`, `tcgcsv_group_id` | string — copied from product for traceability |
| `loose_pack_tcgcsv_product_id`, `box_tcgcsv_product_id` | string |
| `packs_per_box` | int (copied validation value) |
| `raw_loose_pack_market_price` | Decimal128 \| null |
| `raw_box_market_price` | Decimal128 \| null |
| `resolved_pack_price` | **Decimal128 \| null** — **changed this revision**, was non-nullable |
| `resolved_price_source` | `LOOSE_PACK_MARKET` \| `DERIVED_FROM_BOX_MARKET` \| `MANUAL` \| `PREVIOUS_VALUE` \| `null` (when `UNRESOLVED`) |
| `price_status` | `OK` \| `STALE` \| `MANUAL` \| `UNRESOLVED` \| `AMBIGUOUS` — **`AMBIGUOUS` added this revision**, see §2.6 |
| `last_successful_refresh_at`, `last_attempted_refresh_at` | datetime \| null |
| `last_modified_by` | string \| null |
| `previous_resolved_price` | Decimal128 \| null |
| `manual_price_metadata` | `{entered_by, entered_at, note}` \| null |
| `version` | int |
| `updated_at` | datetime |

Rule (app-enforced, not expressible in `$jsonSchema` — see §3.1): `price_status == UNRESOLVED ⇒ resolved_pack_price may be null`; `price_status != UNRESOLVED ⇒ resolved_pack_price must be present and valid`.

#### `price_history` (append-only)
| Field | Type |
|---|---|
| `_id` | ObjectId |
| `product_id` | string |
| `previous_price`, `new_price` | Decimal128 \| null |
| `previous_source`, `new_source` | string |
| `initiated_by` | string |
| `manual_entry_by` | string \| null |
| `timestamp` | datetime |
| `refresh_session_id` | string |
| `tcgcsv_status` | string |

#### `refresh_sessions` — **fields expanded this revision for group-batched refresh reporting**
| Field | Type |
|---|---|
| `_id` | string UUID |
| `started_by`, `started_at` | |
| `completed_at` | datetime \| null |
| `status` | `RUNNING` \| `COMPLETED` \| `FAILED` \| `ABORTED` |
| `unique_groups_requested` | int — **new** |
| `products_checked` | int |
| `prices_updated` | int — **new (Phase 3)**, automatic resolution changed the numeric price |
| `prices_unchanged` | int — **new (Phase 3)**, automatic resolution matched the existing price |
| `loose_pack_prices_used` | int (renamed from `loose_used`) |
| `box_derived_prices_used` | int (renamed from `box_derived_used`) |
| `previous_retained` | int — **scoped narrowly (Phase 3):** `refresh_prices()` itself never sets this; "use previous price" is a separate, later, per-product admin action (`pricing_service.accept_previous_price`) that isn't tied back to a specific refresh session's counters. Always 0 on the session document itself. |
| `manual_entered` | int — **same scoping as above:** manual entry is a separate later action (`pricing_service.enter_manual_price`), not counted on the originating session. Always 0 on the session document itself. |
| `ambiguous_products` | int — **new**, count where a `productId` had multiple candidate price rows and none was uniquely selectable |
| `failed_products` | array<{product_id, error}> |
| `failed_groups` | array<{tcgcsv_group_id, error}> — **new** |
| `error_summary` | string \| null |

### 2.3 `elysium_s_<streamer_database_key>` (identical schema per streamer)

#### `inventory_current`
| Field | Type |
|---|---|
| `_id` | string = `product_id` |
| `product_id` | string |
| `current_packs` | int (negative only via discrepancy path — see §4.6) |
| `updated_at` | datetime |

#### `streams`
| Field | Type |
|---|---|
| `_id` | string UUID |
| `streamer_id` | string |
| `date`, `start_time`, `end_time` | |
| `status` | `ACTIVE` \| `COMPLETED` \| `CANCELED` (see §5 state machine) |
| `inventory_snapshot` | array<{product_id, packs_at_start}> |
| `price_snapshot` | array<{product_id, product_name_at_snapshot, resolved_pack_price, price_source, raw_loose_price, raw_box_price, packs_per_box, price_doc_version, snapshot_at}> |
| `final_stream_gross` | Decimal128 \| null |
| `sum_of_break_gross` | Decimal128 (cached, recomputed on break change) |
| `gross_difference` | Decimal128 \| null |
| `stream_pack_market_value` | Decimal128 (cached) |
| `stream_profit`, `stream_profit_margin` | Decimal128 \| null |
| `notes` | string |
| `force_canceled`, `force_cancel_reason`, `force_canceled_by`, `force_canceled_at` | nullable |
| `corrections` | array of correction records (shape below) |
| `created_at`, `updated_at` | |
| `lock_heartbeat_at` | datetime — mirrors `global_operations.last_heartbeat_at` for crash-resume UI |

Correction record shape (embedded in `corrections[]`):
```text
{ correction_id, admin_id, timestamp, reason,
  before: {...}, after: {...},
  inventory_effect, profit_effect,
  affected_break_ids, affected_product_ids,
  shortage_choice: "A_NEGATIVE" | "B_BLOCKED" | "C_PARTIAL" | "D_CANCELED" | null,
  shortage_quantity: int | null,           // = "unbacked" amount, see §4.6
  physically_deducted_quantity: int | null } // new: amount actually removed from master total
```

#### `breaks`
| Field | Type |
|---|---|
| `_id` | string UUID |
| `stream_id` | string |
| `sequence_number` | int |
| `name` | string \| null |
| `status` | `ACTIVE` \| `ENDED_EDITABLE` \| `DELETED` |
| `start_time`, `end_time` | datetime \| null |
| `pack_lines` | array<{product_id, quantity, locked_unit_price, price_source, line_market_value}> |
| `total_pack_market_value` | Decimal128 |
| `break_gross` | Decimal128 \| null |
| `break_profit`, `break_profit_margin` | Decimal128 \| null |
| `notes` | string |
| `deleted_at`, `deleted_by` | nullable — soft delete |
| `created_at`, `updated_at` | |

#### `streamer_history` (optional, streamer-facing; not the audit system)
| Field | Type |
|---|---|
| `_id` | ObjectId |
| `event_type` | string |
| `timestamp` | datetime |
| `product_id`, `stream_id`, `break_id` | string \| null |
| `quantity` | int \| null |
| `description` | string |

### 2.4 Why the streamer database name changed

Revision 1 used `elysium_streamer_<full UUID>` (e.g. `elysium_streamer_550e8400-e29b-41d4-a716-446655440000`, 53+ characters). Combined with collection names like `streamer_history`, that pushes close to the kind of length limits Atlas/MongoDB namespaces are sensitive to, and there's no reason to accept that risk.

Fix: `streamer_database_key` is generated once at streamer-account-creation time (e.g. `secrets.token_hex(6)` → 12 hex chars), checked against a unique index, regenerated on the rare collision (retry loop, not a pre-check-then-insert race — see §10 item 11), and stored permanently on the `users` document. `user_id` (the full UUID) remains the identity used everywhere as `streamer_id` in `audit_events`, `streamer_allocations`, etc. — only the *database name* uses the short key. The key is independent of `username`, so renaming a streamer's login never requires renaming their database.

### 2.5 Why product images changed to `image_url`

`products` is a shared collection read by every admin/streamer desktop, each with its own filesystem. A field called `image_reference` holding a local path (Revision 1's design) would point to a file that only exists on whichever computer created/edited that product. Fixed: `products.image_url` holds one canonical source URL (TCGCSV-provided or admin-uploaded-and-hosted); each computer downloads and caches it locally under `%LOCALAPPDATA%\ElysiumMasterApp\sealed_product_images\` via the new `sealed_image_cache_service.py`, reusing the same generic downloader (`local_assets/image_cache_core.py`) as the existing card-image cache. No shared document ever contains a machine-local path.

### 2.6 TCGCSV price-record resolution and ambiguity

A TCGCSV group's price dataset can contain multiple rows for the same `productId` (different `subTypeName` values — e.g. `"Normal"`, `"Foil"`, `"1st Edition"`). Sealed product (loose pack / booster box) pricing is expected to have exactly one usable row per `productId`, but the app must not silently guess if that assumption breaks.

Resolution algorithm per `productId` within a downloaded group dataset:
1. Filter rows to that `productId`.
2. If zero rows → raw price is absent (falls through to the LLD §9.3 fallback chain: box-derived → previous/manual).
3. If exactly one row → use its `marketPrice`.
4. If multiple rows → look for a row whose `subTypeName` case-insensitively matches `"Normal"`, then `"Unopened"`, in that priority order. If exactly one candidate matches at the first priority level that has any match, use it.
5. If multiple rows remain with no single preferred match (or the preferred candidate itself appears more than once) → **do not guess**. Mark that product `price_status: AMBIGUOUS` for this refresh, record it in `refresh_sessions.ambiguous_products` and `failed_products` with an explanatory error, and require an admin to resolve it via **Enter Manual Price** (same UI path as an unresolved price). `AMBIGUOUS` behaves like `UNRESOLVED` for the "must be resolved before a stream can start" rule (§4.3 Start Stream), it's just labeled distinctly so the report explains *why* it wasn't automatic.

**Verified live against tcgcsv.com during Phase 3 implementation (2026-08-07):** `GET /tcgplayer/categories` confirms Magic is `categoryId: 1`; `GET /tcgplayer/{categoryId}/groups` and `GET /tcgplayer/{categoryId}/{groupId}/products|prices` match the shape assumed above exactly, including `marketPrice` and `subTypeName`. One correction: real `subTypeName` values observed are only `"Normal"` and `"Foil"` — `"Unopened"` (originally listed as a second-priority fallback) does not appear in practice and is dropped from the priority list, which is now just `["Normal"]`. Sealed booster/box products consistently return exactly one `"Normal"` row per `productId` in every group sampled.

**Also discovered live:** Wizards discontinued separate Draft and Set Boosters for new sets, replacing both with a single "Play Booster" product (e.g. TCGCSV's "Foundations" group has no Set Booster at all, only "Play Booster" and "Collector Booster"). The LLD's `booster_type` enum (`DRAFT`/`SET`/`COLLECTOR`) predates this. Per your instruction, `booster_type` gains a fourth value: `PLAY`, used for current/new sets while `DRAFT`/`SET` remain available for older catalog products. Updated in §2.1 and §3.1.

---

## 3. Validators and Indexes

### 3.1 Validator strategy

Each collection gets a MongoDB `$jsonSchema` validator applied via `create_collection(..., validator=...)` (or `collMod` if the collection already exists), with `validationLevel: "strict"` and `validationAction: "error"`. Validators enforce **shape and type**, not cross-document invariants or cross-field conditionals — MongoDB's `$jsonSchema` support does not include `if`/`then` conditional keywords, so rules like "`UNRESOLVED` ⇒ `resolved_pack_price` may be null, otherwise it must be present" are enforced in the **service layer** (`pricing_service.py`), with the validator only constraining the field to `["decimal", "null"]`.

Representative validators (full set lives in `bootstrap/init_database.py`):

```js
// elysium_master.inventory_current
{
  $jsonSchema: {
    bsonType: "object",
    required: ["_id", "product_id", "total_packs", "unassigned_packs", "version", "updated_at"],
    properties: {
      total_packs: { bsonType: "int", minimum: 0 },
      unassigned_packs: { bsonType: "int", minimum: 0 },
      version: { bsonType: "int", minimum: 0 }
    }
  }
}

// elysium_master.streamer_allocations
{
  $jsonSchema: {
    bsonType: "object",
    required: ["streamer_id", "product_id", "current_packs", "version", "updated_at"],
    properties: {
      current_packs: { bsonType: "int" }   // no minimum — discrepancy path allows negative, see §4.6
    }
  }
}

// elysium_master.global_operations — replaces the old two-document global_locks validator
{
  $jsonSchema: {
    bsonType: "object",
    required: ["_id", "stream_active", "price_refresh_active", "version", "updated_at"],
    properties: {
      _id: { enum: ["GLOBAL_OPERATIONS"] },
      stream_active: { bsonType: "bool" },
      price_refresh_active: { bsonType: "bool" }
    }
  }
}

// elysium_master.reason_notes — new this revision
{
  $jsonSchema: {
    bsonType: "object",
    required: ["_id", "action_type", "current_text", "history", "created_at", "created_by"],
    properties: {
      current_text: { bsonType: "string", minLength: 1 },
      history: { bsonType: "array", minItems: 1 }
    }
  }
}

// elysium_master.products
{
  $jsonSchema: {
    bsonType: "object",
    required: [
      "_id", "name", "name_normalized", "booster_type", "language", "english_confirmed",
      "packs_per_box", "tcgcsv_category_id", "tcgcsv_group_id",
      "loose_pack_tcgcsv_product_id", "box_tcgcsv_product_id",
      "image_url", "is_active"
    ],
    properties: {
      booster_type: { enum: ["DRAFT", "SET", "COLLECTOR", "PLAY"] },
      packs_per_box: { bsonType: "int", minimum: 1 },
      english_confirmed: { bsonType: "bool" }
    }
  }
}

// elysium_prices.current_prices
{
  $jsonSchema: {
    bsonType: "object",
    required: ["_id", "product_id", "price_status", "version"],
    properties: {
      resolved_pack_price: { bsonType: ["decimal", "null"] },  // nullable — fixed this revision
      resolved_price_source: { enum: ["LOOSE_PACK_MARKET", "DERIVED_FROM_BOX_MARKET", "MANUAL", "PREVIOUS_VALUE", null] },
      price_status: { enum: ["OK", "STALE", "MANUAL", "UNRESOLVED", "AMBIGUOUS"] }
    }
  }
}

// elysium_streamer_<key>.streams
{
  $jsonSchema: {
    bsonType: "object",
    required: ["_id", "streamer_id", "status", "start_time"],
    properties: {
      status: { enum: ["ACTIVE", "COMPLETED", "CANCELED"] }
    }
  }
}

// elysium_streamer_<key>.breaks
{
  $jsonSchema: {
    bsonType: "object",
    required: ["_id", "stream_id", "sequence_number", "status", "pack_lines"],
    properties: {
      status: { enum: ["ACTIVE", "ENDED_EDITABLE", "DELETED"] },
      sequence_number: { bsonType: "int", minimum: 1 }
    }
  }
}
```

Money fields (`total_packs`/`unassigned_packs` excluded — those are integer pack counts) use **Decimal128** end-to-end: `resolved_pack_price`, `break_gross`, `final_stream_gross`, `stream_profit`, etc. No binary floats for currency, per LLD §23.1.

### 3.2 Required indexes

| Collection | Index | Type |
|---|---|---|
| `elysium_master.users` | `username` | unique |
| `elysium_master.users` | `streamer_database_key` | unique, sparse — **new this revision** |
| `elysium_master.users` | `streamer_database_name` | unique, sparse |
| `elysium_master.products` | `_id` (product_id) | unique (default) |
| `elysium_master.products` | `loose_pack_tcgcsv_product_id` | unique |
| `elysium_master.products` | `box_tcgcsv_product_id` | unique |
| `elysium_master.products` | `(name_normalized, booster_type)` | unique (dup prevention, §8.4) — `name_normalized` is a stored, computed lowercased/whitespace-collapsed field, not the literal `name` |
| `elysium_master.products` | `is_active` | non-unique |
| `elysium_master.products` | `(tcgcsv_category_id, tcgcsv_group_id)` | non-unique — **new this revision**, supports the refresh's group-batch query |
| `elysium_master.inventory_current` | `_id` (product_id) | unique (default) |
| `elysium_master.streamer_allocations` | `(streamer_id, product_id)` | unique compound |
| `elysium_master.audit_events` | `(timestamp desc)` | non-unique |
| `elysium_master.audit_events` | `(action_type, timestamp)` | compound |
| `elysium_master.audit_events` | `(streamer_id, timestamp)` | compound |
| `elysium_master.audit_events` | `(product_id, timestamp)` | compound |
| `elysium_master.audit_events` | `(stream_id)` | non-unique |
| `elysium_master.reason_notes` | `streamer_id` | non-unique — **new this revision** |
| `elysium_master.reason_notes` | `action_type` | non-unique — **new this revision** |
| `elysium_master.inventory_discrepancies` | `status` | non-unique |
| `elysium_master.decommission_requests` | `status` | non-unique |
| `elysium_prices.current_prices` | `_id` (product_id) | unique (default) |
| `elysium_prices.price_history` | `(product_id, timestamp desc)` | compound |
| `elysium_prices.refresh_sessions` | `(started_at desc)` | non-unique |
| `elysium_s_<key>.inventory_current` | `_id` (product_id) | unique (default) |
| `elysium_s_<key>.streams` | `(status, start_time desc)` | compound |
| `elysium_s_<key>.breaks` | `(stream_id, sequence_number)` | unique compound |
| `elysium_s_<key>.breaks` | `(stream_id, status)` | compound |
| `elysium_s_<key>.streamer_history` | `(timestamp desc)` | non-unique |

All indexes are created idempotently (`createIndex` is a no-op if an equivalent index exists) by `bootstrap/init_database.py` and by `provision_streamer_db.py` for each new streamer database.

---

## 4. Transaction and Locking Design

### 4.1 Principles

- Every operation that touches **more than one document or more than one database** runs inside a single MongoDB **client session with a multi-document transaction** (`session.with_transaction(...)`), per LLD §12.5.
- MongoDB supports distributed (cross-database) ACID transactions within one cluster/replica set (4.2+); all three logical databases live in the same Atlas deployment (LLD §5.3), so this is a single transaction spanning `elysium_master` and `elysium_s_<key>` collections when needed.
- **Risk flagged in §10**: transaction support must be confirmed against the actual Atlas tier before UI work begins — this is the first thing to test once a cluster exists (§12).
- Optimistic `version` fields are kept on mutable current-state documents (`inventory_current`, `streamer_allocations`, `current_prices`, `global_operations`) as defense-in-depth and for UI conflict messaging, even though the transaction itself is what guarantees correctness (see §10).
- Standard retry pattern: catch `TransientTransactionError` / `UnknownTransactionCommitResult`, retry the whole transaction body with backoff (pymongo's `with_transaction` helper does this).
- Every transaction that changes state also writes one or more `audit_events` documents **inside the same transaction**, so an audit record can never exist without the change it describes (or vice versa).

### 4.2 Locking model — single atomic `GLOBAL_OPERATIONS` document

**Revision 1 used two separate lock documents (`GLOBAL_STREAM`, `PRICE_REFRESH`).** That allowed a real race: Client A reads `PRICE_REFRESH.is_active == false`, Client B reads `GLOBAL_STREAM.is_active == false`, and both then acquire their respective lock — a stream and a refresh end up active simultaneously, which the business rules (LLD §4.3/§4.4) explicitly forbid.

**Fix:** both states live on the one `global_operations` document (§2.1), and acquisition of *either* lock is a single atomic `find_one_and_update` that requires *both* flags to be false:

```text
acquire_stream_lock(streamer_id, stream_id, streamer_database_name):
  result = global_operations.find_one_and_update(
    filter = { _id: "GLOBAL_OPERATIONS", stream_active: false, price_refresh_active: false },
    update = { $set: { stream_active: true, stream_id, streamer_id, streamer_database_name,
                        stream_started_at: now, last_heartbeat_at: now, updated_at: now },
               $inc: { version: 1 } },
    return_document = AFTER
  )
  if result is None: reject — either a stream or a refresh is already active

acquire_price_refresh_lock(started_by, refresh_session_id):
  result = global_operations.find_one_and_update(
    filter = { _id: "GLOBAL_OPERATIONS", stream_active: false, price_refresh_active: false },
    update = { $set: { price_refresh_active: true, refresh_session_id, refresh_started_by: started_by,
                        refresh_started_at: now, updated_at: now },
               $inc: { version: 1 } },
    return_document = AFTER
  )
  if result is None: reject — either a stream or a refresh is already active
```

Because both conditions are checked and both flags are set in one atomic single-document operation, it is now structurally impossible for a stream and a refresh to become active at the same time — there is no window between "check" and "set" for a second client to slip through. This holds even without wrapping the call in a multi-document transaction (single-document writes are always atomic in MongoDB); a transaction is still used when lock acquisition needs to happen together with a write in another database (e.g. stream start also inserts the `streams` document).

Release is symmetric and only clears its own sub-state (`$set: {stream_active: false, stream_id: null, ...}` or the refresh equivalent), never touching the other flag.

| Lock sub-state | Acquired by | Blocks |
|---|---|---|
| `stream_active` | `stream_service.start_stream` | Any other `start_stream`; `pricing_service.refresh_prices`; edits to the active streamer's inventory/allocation |
| `price_refresh_active` | `pricing_service.refresh_prices` | `stream_service.start_stream`; concurrent refreshes |

### 4.3 Per-operation transaction design

**Claim inventory** (`inventory_service.claim`) — cross-DB (master + streamer)
1. Read `global_operations`; reject if `stream_active` and `streamer_id == this streamer`.
2. Start transaction.
3. `find_one_and_update(master.inventory_current, {product_id, unassigned_packs: {$gte: qty}}, {$inc: {unassigned_packs: -qty}, $inc: {version:1}})` — fails (returns null) if insufficient, transaction aborts, clean rejection (LLD §29.4).
4. Upsert `master.streamer_allocations` `{streamer_id, product_id}` with `$inc: {current_packs: qty, version:1}`.
5. Upsert streamer DB `inventory_current/{product_id}` with `$inc: {current_packs: qty}`.
6. Insert `audit_events` (`STREAMER_INVENTORY_CLAIMED`).
7. Commit. On any failure, whole transaction rolls back — no partial state (LLD §11.2 step 10).

**Return inventory** — mirror of claim, decrement streamer/allocation, increment unassigned; reason required; blocked if this streamer is the active streamer.

**Master add inventory** — single-DB (`elysium_master` only), still transactional across `inventory_current` + `audit_events` for consistency; box→pack conversion happens before the transaction (pure function, unit tested — §11).

**Master reduce inventory** — single-DB; filter requires `unassigned_packs >= qty`; reason required; allowed during an active stream (LLD §12.3).

**Start stream** — cross-DB
1. Atomically acquire `stream_active` per §4.2 (this alone also guarantees no refresh is running).
2. Read streamer's full `inventory_current` and required price snapshot (`elysium_prices.current_prices`) for every positive-quantity product; if any has `price_status` in `{UNRESOLVED, AMBIGUOUS}`, abort before any write and surface the "Use Previous / Enter Manual" prompt (LLD §13.2, §2.6).
3. Transaction: insert new `streams` doc (`status: ACTIVE`, snapshots embedded); the lock acquisition from step 1 is included in the same transaction if it hasn't already committed standalone.
4. Insert `audit_events` (`STREAM_STARTED`).

**Break create/end/edit/delete** — single-DB (streamer database only)
- No cross-DB write, but still wrapped in a transaction when a `breaks` write and the parent `streams` cached-totals update (`sum_of_break_gross`, `stream_pack_market_value`) happen together, so the cache can never drift from the underlying breaks.
- Availability check (§14.4) is computed at write time from a fresh read of all non-deleted breaks in the active stream, inside the same transaction, to avoid a race between two rapid pack-quantity edits.

**End Stream (final submission)** — cross-DB, the highest-stakes transaction
1. Verify `global_operations.stream_id` still equals this stream (guards against a stale/resumed client).
2. Recompute totals from current `breaks` (source of truth), not client-cached numbers.
3. Verify streamer's current inventory covers every grouped pack total.
4. `$inc` streamer `inventory_current` down by used packs; `$inc` master `streamer_allocations` down by same; `$inc` master `inventory_current.total_packs` down by same (unassigned untouched).
5. Write final stream fields, `status: COMPLETED`, `completed_at`.
6. Insert `audit_events` (`STREAM_COMPLETED`, plus per-product inventory deltas).
7. Release `stream_active` on `global_operations`.
8. Any failure → full rollback, stream stays `ACTIVE` for correction (LLD §15.5).

**Cancel / force-cancel stream** — cross-DB: set `status: CANCELED` (+ `force_canceled` fields if admin-initiated), release `stream_active`. No inventory movement. Force-cancel requires a reason and writes an admin-only `STREAM_FORCE_CANCELED` audit event.

**Price refresh** — single-DB (`elysium_prices`), long-running, not one giant transaction (it calls TCGCSV over network time) — **rewritten this revision for group batching**
1. Acquire `price_refresh_active` per §4.2 (also guarantees no stream is active).
2. Load every product needing refresh (LLD §9.6 step 3: all products, including zero-stock).
3. Group them by `(tcgcsv_category_id, tcgcsv_group_id)`.
4. For each unique group: download that group's TCGCSV price dataset **once**, build an in-memory `productId → [price rows]` map.
5. For every Elysium product in that group, resolve loose-pack and box prices using the algorithm in §2.6 (single match / ambiguous / absent), then apply the LLD §9.3 priority chain (loose → box-derived → previous/manual) to get `resolved_pack_price`.
6. Write/update that product's `current_prices` doc + append a `price_history` row, inside a short per-product transaction (so one product's price+history update is atomic without holding a single transaction open for the whole multi-minute refresh).
7. Update the running `refresh_sessions` document throughout (§2.2 fields), including `unique_groups_requested`, `ambiguous_products`, `failed_groups`.
8. Release `price_refresh_active` in a `finally`-equivalent path so a mid-refresh crash doesn't strand the lock (recoverable via admin action, §4.4).

**Admin correction of a completed stream** — cross-DB, delta-based, **shortage-split logic corrected this revision** — see §4.6 for the full A/B/C/D redesign.

**Decommission approval** — cross-DB: for every product with a positive streamer allocation, zero the streamer's `inventory_current` and `master.streamer_allocations`, add the same amount to `master.inventory_current.unassigned_packs` (total unchanged), disable the user's login, write `DECOMMISSION_APPROVED` audit. Blocked if that streamer currently owns the active stream lock. **Also blocked from being bypassed via direct account disabling** — see §4.8.

### 4.4 Abandoned-lock recovery

If the process holding `global_operations` disappears (crash, killed app), the relevant sub-state simply persists as `true`. Recovery is always an **explicit admin action**, never automatic/timed, and only ever clears the specific sub-state that's stuck — never both:
- `stream_active` stuck → admin "Force Cancel" (§16.4), a transaction that flips the stream to `CANCELED` **and** clears `stream_active` (+ related stream fields) on `global_operations`, leaving `price_refresh_active` untouched.
- `price_refresh_active` stuck → dedicated admin "Recover Refresh Lock" action that clears only `price_refresh_active` (+ its fields) and writes an audit entry, used only when a refresh session is clearly dead (no heartbeat / crashed session). Does not touch `stream_active`.

Both recovery actions use a version-guarded update (`{_id: "GLOBAL_OPERATIONS", version: expected_version}`) so a recovery action can't clobber a legitimate concurrent lock change.

### 4.5 Reason-editing workflow — `audit_events` is never mutated, ever

Confirmed this revision: `audit_events` documents receive exactly one write (the insert) and are never touched again by anything, including reason edits. That means the "current reason" for an editable action has to live somewhere other than the `audit_events` document itself.

**Where each reason-requiring action's editable text actually lives:**

| Action (LLD §19.5) | Where the editable "current reason" lives | Why |
|---|---|---|
| Master inventory reduction | `reason_notes` document (new collection, §2.1) | No other live document represents "this specific reduction" — it's a one-off ledger adjustment. |
| Streamer inventory return | `reason_notes` document | Same — one-off ledger adjustment, no other persistent record. |
| Admin stream correction | `streams.corrections[i].reason` (already a field on the live `streams` document, unchanged from Revision 2) | `streams` is a regular mutable current-state document, not `audit_events` — editing a field on it was never in tension with "audit_events is append-only." |
| Admin force-cancel | `streams.force_cancel_reason` (already a field on the live `streams` document) | Same reasoning. |
| Discrepancy create/resolve | `inventory_discrepancies.resolution_note` / its creation reason (already a field on the live `inventory_discrepancies` document) | Same reasoning. |

So `reason_notes` (§2.1) is only needed for the two action types that had no other document to hold an editable reason. The other three already had a natural, already-mutable home that was never actually part of the append-only collection — Revision 2's design happened to be correct for those three without realizing it; only the master-reduction and streamer-return cases needed a new place to live.

**In practice, permission-wise:** because master inventory reductions, stream corrections, force-cancels, and discrepancy actions are all admin-only operations (LLD §7.1), the only reason type a *streamer* ever personally owns and can edit is their own return reasons (a `reason_notes` document with `streamer_id` set to themselves). Admins can edit any of the five.

```text
edit_reason(related_record_type, related_record_id, new_text, edited_by):
  1. Load the target:
       - related_record_type == "reason_note"     → reason_notes/{related_record_id}
       - related_record_type == "stream_correction" → streams/{stream_id}.corrections[i]
       - related_record_type == "force_cancel"       → streams/{stream_id}.force_cancel_reason
       - related_record_type == "discrepancy"        → inventory_discrepancies/{related_record_id}
  2. Permission check:
       - reason_note with streamer_id set → edited_by must equal that streamer_id, or be an admin.
       - every other type → admin only (matches who can perform the underlying action at all).
  3. Transaction:
       a. old_text = current value.
       b. Update the target in place to new_text (reason_notes.current_text + $push history;
          or the specific field on streams / inventory_discrepancies).
       c. INSERT (never update) a new audit_events document: action_type = "REASON_EDITED",
          old_reason, new_reason, edited_by, edited_at, related_record_type, related_record_id.
          This is a brand-new document — the audit_events document for the *original* action
          (the reduction, the return, the correction, etc.) is never touched.
  4. Commit.
```

### 4.6 Why this satisfies "append-only, never mutated"

No `audit_events` document is ever the target of an `UpdateOne` for any reason, under any circumstance — insert-only, permanently. The *display* of "the current reason" for an action comes from wherever that action's reason actually lives (`reason_notes.current_text`, or the relevant field on `streams`/`inventory_discrepancies`), each of which independently preserves its own edit history (`reason_notes.history[]`, or a fresh `REASON_EDITED` audit event referencing that record) — so nothing is ever lost, and the append-only guarantee on `audit_events` is now unconditional rather than resting on an interpretation.

### 4.7 Corrected master-inventory invariant and negative-discrepancy model

**Problem in Revision 1:** a streamer allocation was allowed to go negative (admin correction, "allow negative inventory"), while the master invariant was stated as `total_packs = unassigned_packs + Σ streamer_allocations`. Applied literally, a negative allocation would pull `total_packs` down by an amount that was never physically backed by real inventory — the company doesn't actually lose packs it never had. `total_packs` must always represent **real, physical, non-negative** company inventory.

**Fix — separate "physical" from "ledger":**

- `master.inventory_current.total_packs` / `unassigned_packs` — always non-negative, always physical.
- `streamer_allocations.current_packs` (and the mirrored streamer-DB `inventory_current.current_packs`) — a **ledger** value that may go negative; a negative value means "this streamer is short N packs relative to what our records say they should be accountable for," not "N physical packs exist in negative quantity."

**Corrected invariant:**
```text
total_packs = unassigned_packs + Σ_streamers max(streamer_allocations.current_packs, 0)
```
**Discrepancy consistency invariant** (checked in acceptance tests, §11.1):
```text
Σ_streamers max(-streamer_allocations.current_packs, 0)
=
Σ open inventory_discrepancies where type == NEGATIVE_INVENTORY  (grouped by streamer/product)
```

**Correction transaction — shortage handling, rewritten:**

Let `shortage = new_corrected_packs_used - old_packs_used` (only relevant when positive — a correction that *increases* historical usage). Let `current_balance` be the streamer's live `streamer_allocations.current_packs` immediately before this correction.

```text
physically_deductible = max(0, min(shortage, current_balance))
unbacked              = shortage - physically_deductible
```

- **Choice A — Allow negative inventory:**
  `streamer_allocations.current_packs -= shortage` (and the mirrored streamer-DB value) — ledger may go negative.
  `master.total_packs -= physically_deductible` (physical, provably stays ≥ 0 because `physically_deductible ≤ current_balance`, and `current_balance` was already counted inside `total_packs` under the invariant before this operation). `unassigned_packs` unchanged.
  If `unbacked > 0`: open/increment an `inventory_discrepancies` doc, `type: NEGATIVE_INVENTORY`, `quantity: unbacked` — this is the "prominent unresolved discrepancy" LLD §17.6.A requires, and it now exactly matches the negative ledger amount it created (satisfying the consistency invariant above).

- **Choice B — Block correction:** unchanged from Revision 1 — no writes, require inventory to be added/returned first.

- **Choice C — Deduct available, record discrepancy:**
  `streamer_allocations.current_packs = max(0, current_balance - shortage)` — ledger **never** goes negative under this choice.
  `master.total_packs -= physically_deductible` — identical physical-safety math to choice A.
  If `unbacked > 0`: open/increment an `inventory_discrepancies` doc, `type: UNDEDUCTED_SHORTAGE`, `quantity: unbacked` — this one is **not** mirrored by a negative ledger balance (the ledger was clamped at 0); it's a pure bookkeeping record that an admin resolves manually (e.g. once the packs are physically located/returned).

- **Choice D — Cancel:** unchanged — no writes.

**Important nuance:** regardless of which choice is taken, the stream/break's stored historical figures (pack usage, market value, profit) always reflect the **full corrected quantity** (`new_corrected_packs_used`) — profit accounting is about packs actually opened for sale, not about how the inventory ledger happened to absorb the shortfall. Only the inventory-side deduction is split/capped by the logic above.

Acceptance test for the example in `implementation_improvments.md` (streamer has 2, correction adds 5 more used, admin chooses "allow negative"): `physically_deductible = min(5, 2) = 2`, `unbacked = 3`. Streamer ledger becomes `2 - 5 = -3`. `master.total_packs` decreases by exactly `2` (never goes negative), a `NEGATIVE_INVENTORY` discrepancy of quantity `3` is opened. See §11.1.

### 4.8 Account disabling must not bypass decommissioning

**Rule:** the Users screen's **Disable Account** action is only a *direct* action for a user who is not a streamer, or is a streamer with zero current inventory across all products (all `streamer_allocations.current_packs == 0`, including no open negative-discrepancy balance). If the target user is a streamer holding any nonzero allocation (positive **or** negative), **Disable Account** redirects into the Decommissioning flow instead of disabling anything:

```text
1. Decommissioning is initiated (LLD §18.1).
2. A pending inventory return snapshot is created.
3. Admin reviews it.
4. Admin approves it (§4.3 Decommission approval).
5. Inventory returns to master unassigned stock (only the positive portion — a residual
   negative/discrepancy balance is not silently erased by decommissioning; it stays open
   in inventory_discrepancies for manual resolution).
6. Only then is login disabled.
```

Both **Decommissioning** and **direct Disable Account** are blocked outright (with a clear error, not a silent no-op) while that streamer currently owns the active stream lock (`global_operations.streamer_id == this streamer`), consistent with LLD §18.2.

An admin account with no streamer role, or a streamer role with zero net inventory, can still be disabled directly with no extra steps.

---

## 5. Stream State Machine

```text
                    start_stream()
     (no lock) ───────────────────────► ACTIVE ─────────────► COMPLETED
        ▲                                 │  │   end_stream()      │
        │                                 │  │  (final submit)     │ admin correction
        │            cancel()             │  │                     │ (stays COMPLETED,
        │       ┌─────────────────────────┘  │                     │  in-place overwrite
        │       │                            │ force_cancel()      │  + audit trail)
        │       ▼                            │ (admin only)        ▼
        └─── CANCELED ◄───────────────────────┘               COMPLETED
             (terminal, force_canceled flag                   (terminal)
              set if admin-initiated)

  ACTIVE also survives app close/crash — the stream document is the
  persisted source of truth, not in-memory state, so reopening the
  app just re-reads the doc and offers Resume / Cancel (LLD §16.1).
  The stream/refresh lock state itself lives on the single
  global_operations document (§4.2), not on the stream document.
```

- `ACTIVE`, `COMPLETED`, `CANCELED` are the only three `streams.status` values.
- `COMPLETED` and `CANCELED` are terminal for streamers; only an admin correction can further modify a `COMPLETED` stream, and it never changes status — it overwrites the visible record while preserving the original in `corrections[]` + `audit_events` (LLD §17.2).
- `global_operations.stream_active` tracks `ACTIVE`: acquired on `start_stream`, released on the `ACTIVE → COMPLETED` and `ACTIVE → CANCELED` transitions, never touched otherwise.

**Break sub-state machine** (scoped to one stream, independent per break):

```text
(created) ── start_new_break() ──► ACTIVE ── end_break(gross) ──► ENDED_EDITABLE
                                                                        │
                                                          delete_break()│  edit_break()
                                                                        ▼        │
                                                                    DELETED   (loops on
                                                               (soft, excluded  ENDED_EDITABLE)
                                                                from totals)
```

Only one break per stream may be `ACTIVE` at a time (service-enforced default — see §10). `ENDED_EDITABLE` breaks remain editable until the *stream* transitions to `COMPLETED`, at which point all its breaks become implicitly immutable (no separate break-level lock needed — enforced by "stream must be ACTIVE" guard in `break_service`).

---

## 6. UI Screen Plan

Shell is role-aware; nav items match LLD §24 exactly. Each screen below: purpose, key elements, primary actions.

### 6.1 Login / Guest (all users)
- Username + password fields, **Login** button, **Continue as Guest** link.
- MongoDB connection status indicator (checked on load); if unreachable, shows inline notice and still allows Guest.
- On success: routes to shell with role-appropriate nav.
- The Mongo connection itself is baked into the install (§13.3) — this screen never asks about it; the connection-status indicator reflects whether that pre-baked connection is currently reachable, nothing more.

### 6.2 Shell (all logged-in + guest)
- Left/top nav per §24.1–24.3.
- Persistent status bar (§24.4): Mongo connection dot, active stream banner (streamer+time if any), price-refresh-blocked indicator, last refresh time, pending manual-price/ambiguous-price count, pending decommission count, open discrepancy count, current role.

### 6.3 Dashboard (streamer/admin, role-scoped content)
- Cards for: my/company inventory summary, active stream status, quick links to "Start Stream" / "Resume Stream" if one exists for this user, recent audit/history feed (streamer: own; admin: company-wide).

### 6.4 Card Lookup (all, including guest)
- Reuses existing grid/tile layout, search box, **Apply Filter** (sets + collector numbers), **Refresh Card Data** button, zoom shortcuts.
- Persistent stale-data banner when `>24h` since last local refresh (LLD §21.5); refresh runs on a background worker with the safe-swap rebuild (§8) so a failed refresh never destroys the working DB.

### 6.5 My Inventory (streamer)
- Product tiles: image (from local sealed-product image cache, §2.5), name, booster type, current packs, "available" (accounts for active-stream reservation), locked price if in a stream.
- If `current_packs < 0` for a product (open `NEGATIVE_INVENTORY` discrepancy), the tile shows a prominent warning per LLD §11.5.
- **Claim Received Inventory**: pick product → box/pack input → converted total shown → confirm.
- **Return Inventory**: pick product → quantity → required reason → confirm.
- Locked banner if this streamer currently owns the active stream.

### 6.6 Master Inventory (admin)
- Table per LLD §10.5: image, name, booster type, total, unassigned, assigned total, per-streamer breakdown (expandable row), active-stream reserved qty, current price, total market value, price source/last update. Positive-stock sorted first, zero-stock at bottom (§8.5).
- **Add Inventory** and **Reduce Inventory** (unassigned only, reason required) actions.

### 6.7 Streamer Inventory — admin view
- Same tile/table layout as 6.5 but read-only, filterable by streamer, for admin oversight (§7.1 "view all streamer allocations").

### 6.8 Product Catalog (admin)
- List with search/filter by active/inactive, booster type.
- **New Product** form enforcing all mandatory fields (§8.2) before Save is enabled, **now including `tcgcsv_category_id` and `tcgcsv_group_id`** alongside the loose/box product IDs; duplicate-prevention check runs on blur of the TCGCSV ID fields and name+type.
- Image field accepts a URL (`image_url`) rather than a file path; the form shows a live thumbnail preview fetched through the same local cache used at runtime.

### 6.9 Shared Sealed Prices (streamer + admin)
- Table: product, raw loose price, raw box price, resolved price, source, status (`OK`/`STALE`/`MANUAL`/`UNRESOLVED`/`AMBIGUOUS`), last refresh.
- **Refresh Sealed Prices** button (disabled + explained when a stream is active, LLD §25.4).
- Post-refresh summary panel: groups requested, products checked, loose-pack used, box-derived used, previous retained, manual entered, **ambiguous count**, failed products, failed groups, start/completion times.
- Inline **Use Previous Price** / **Enter Manual Price** prompt for any `UNRESOLVED` or `AMBIGUOUS` product — same resolution path for both, since both block stream start identically.

### 6.10 Streams — Start / Active Workspace / End Review (streamer)
- **Start Stream**: precondition checklist (locks clear, prices accepted — no `UNRESOLVED`/`AMBIGUOUS` products in inventory), prominent "Refresh Sealed Prices first" recommendation, **Start Stream** button.
- **Active workspace**: break tile grid (product image, name, type, assigned/selected/available, locked price+source, current break qty, line value); plus/minus controls; **Start New Break** / **End Break** (requires gross) / notes field.
- **End Stream**: final gross entry, full break-by-break summary table, per-break open/edit/delete, live recalculation of sum-of-break-gross, gross difference, market value, profit; **Confirm Final Submission** (irreversible by non-admins).
- **Resume/Cancel prompt** on login if an unfinished stream is found for this streamer (LLD §16.1), showing date/start time, ended/active breaks, totals so far.

### 6.11 Streams and Breaks — admin view
- Read-only browse of all streams/breaks company-wide; entry point into **Correct Stream** flow (before/after diff view, required reason, shortage-choice dialog A/B/C/D — now showing the physical-vs-ledger split described in §4.6 so the admin can see exactly how much will actually leave master inventory vs. become a discrepancy).
- **Force Cancel** action for a stuck active stream (reason required).

### 6.12 Reports and Exports (streamer: own; admin: all)
- Report picker (list matches §20.4), filters (date range, streamer, product), preview table, **Export CSV** (background thread, respects current filters and role scope).

### 6.13 Users (admin)
- List with role/active/decommission-status columns.
- **Create User** (admin or streamer role; streamer creation triggers `provision_streamer_db` and generates `streamer_database_key`). **Reset Password.**
- **Disable Account**: if the target is a streamer with nonzero inventory (positive or negative), this button now opens the Decommissioning flow instead of disabling directly (§4.8) — the UI makes this redirect explicit rather than silently blocking the click.

### 6.14 Decommissioning (admin)
- Pending list with streamer's current allocation snapshot. **Approve** (revalidates inventory, runs the transaction in §4.3, disables login only after success). **Initiate** from a streamer's detail view, or automatically entered via the Users screen redirect (§4.8/§6.13).

### 6.15 Discrepancies (admin)
- Open/resolved list, filter by streamer/product/type (`NEGATIVE_INVENTORY` vs `UNDEDUCTED_SHORTAGE`, semantics per §4.6), **Resolve** action with required note.

### 6.16 Audit History (admin)
- Filterable/sortable table over `audit_events`, CSV export (audit-only, admin-only per §20.5).
- **Edit Reason** inline action on any record with an editable reason field, subject to the ownership rule in §4.5 (streamers see it only on their own records when browsing their own history, not the full admin audit view).

### 6.17 Account (all logged-in)
- Change own password; view own role/profile.

---

## 7. Stream/Break Workflow — Sequence Summary

```text
Streamer                 App                          MongoDB (master)         MongoDB (streamer db)
   │  Start Stream          │                                │                          │
   ├───────────────────────►│ atomically acquire stream_active on global_operations      │
   │                        │ (also proves no refresh is active — single doc, §4.2)      │
   │                        ├───────────────────────────────►│ update global_operations  │
   │                        ├────────────────────────────────────────────────────────────►│ insert stream(ACTIVE)
   │  Start New Break       │                                │                          │
   ├───────────────────────►│                                │                          │
   │  +/- packs, End Break  │  txn: write break + refresh stream cached totals           │
   ├───────────────────────►│────────────────────────────────────────────────────────────►│ upsert break, update stream
   │  (repeat per break)    │                                │                          │
   │  End Stream (final $)  │  review screen, recompute from breaks                      │
   ├───────────────────────►│                                │                          │
   │  Confirm Submission    │  txn: verify lock, verify inventory, deduct, finalize,      │
   ├───────────────────────►│  release stream_active                                     │
   │                        ├───────────────────────────────►│ update allocation/total,  │
   │                        │                                │ clear stream_active       │
   │                        ├────────────────────────────────────────────────────────────►│ deduct inventory, status=COMPLETED
```

---

## 8. Migration Plan for the Existing Card Lookup Code

| Existing file | Destination | Change required |
|---|---|---|
| `app.py` (monolithic) | `ui/card_lookup.py` (grid/tiles/filters/zoom) + `services/scryfall_service.py` (refresh worker logic) + `local_card/image_cache.py` (download logic) | Split into layers; `InitialSetupWindow`'s "first run" concept moves inside the Card Lookup tab as an empty/prompt-to-refresh state, since the *application's* first screen is now Login (LLD §6.1), not card-data setup. |
| `db.py` | `local_card/db.py` | Keep schema concepts, `insert_cards` logic, price/finish handling as-is. **Add**: safe-swap rebuild — write to a temp file (`cards_new.sqlite`) and `os.replace()` into place only after a successful import (LLD §26.3), instead of `os.remove(DB_NAME)` then rebuild. **Add**: a small `refresh_meta` table (or key-value row) storing `last_successful_refresh_at`, used for the 24h stale banner (currently doesn't exist). |
| `bulk_import.py` | `local_card/bulk_import.py` | Reuse bulk-data discovery/download almost unchanged; wire into the new safe-swap rebuild instead of delete-then-create. |
| `cache_images.py` | `local_card/image_cache.py` | Reuse concurrent `ThreadPoolExecutor` download pattern and `row_id` filename-sanitization as-is; its core download loop is factored out into `local_assets/image_cache_core.py` so `sealed_image_cache_service.py` can reuse it for product images (§2.5). |
| `main.py` | replaced | Current file is an unused PyCharm stub; new `elysium/main.py` becomes the real entrypoint (shows Login, or first-time Connect then Login, per §6.1/§13.3). |
| `ElysiumCardLookup.spec` | `packaging/ElysiumMasterApplication.spec` | New entry point, add `pymongo`, `keyring`, `argon2-cffi` to hidden imports; bundle local-card default assets; feeds into the Inno Setup installer (§13). |
| `cards.sqlite`, `data/`, `cache/` | relocated | Currently resolved relative to CWD, which only works running from source. Move to `%LOCALAPPDATA%\ElysiumMasterApp\{cards.sqlite, data\, cache\}` via `local_card/paths.py`, so the packaged/installed app works regardless of launch directory. Required for a non-technical, installed-app audience (§13). |
| Guest mode / login gating | new | Card Lookup becomes reachable from Guest mode and from the logged-in shell identically; no Mongo dependency in this tab at all (LLD §21.1). |

Everything else — search/filter SQL, price-tier color thresholds, printing-details derivation, collector-number filter parsing — is reused unchanged.

---

## 9. Bootstrap

### 9.1 `bootstrap/init_database.py` (idempotent, safe to re-run)
1. Connect using `MONGODB_URI` env var (placeholder in `.env.example`; real value supplied later, never committed).
2. For `elysium_master` and `elysium_prices`: create each collection listed in §2 if missing (with its `$jsonSchema` validator from §3.1); if it already exists, `collMod` its validator to the current definition.
3. Create all indexes from §3.2 for those two databases (idempotent `create_index` calls — safe no-ops if equivalent index exists).
4. Upsert the single `global_operations` singleton doc with `stream_active: false, price_refresh_active: false` **only if it doesn't already exist** (never resets an existing lock state).
5. Upsert `app_settings/GLOBAL` with defaults (`schema_version: 1`, `stale_card_data_hours: 24`, `currency: "USD"`) if missing.
6. **Creates no users, no products, no streamer databases.** Prints a summary of what was created vs. already-present.

### 9.2 `bootstrap/provision_streamer_db.py`
- Exposed as a function (`provision_streamer_database(streamer_database_key)`) called by `services/auth_service.create_user` whenever an admin creates a streamer account (or promotes an admin to also be a streamer). `auth_service.create_user` generates `user_id` (full UUID4, the permanent identity) and, separately, `streamer_database_key` (short token, retried against the unique index on collision) at that moment — not lazily on first claim, since the roster starts empty and grows dynamically per your instruction.
- Creates `elysium_s_<streamer_database_key>` with `inventory_current`, `streams`, `breaks`, `streamer_history` collections, their validators (§3.1), and indexes (§3.2). Idempotent — safe if called on an already-provisioned database.

### 9.3 `bootstrap/create_admin.py` (interactive, run once, by hand)
- The one deliberate "break glass" step: with an empty `users` collection, no one can create the first admin through the app (creating users requires an existing admin). This script prompts for username/password on the command line, hashes it (Argon2id), and inserts the first `users` document directly with `roles: ["admin"]`.
- Refuses to run if any admin user already exists (prevents accidental duplicate bootstrapping); from that point on, all account management happens through the Users screen (§6.13).
- This script is a developer/admin tool distributed alongside the source repo — **not** part of the installed streamer-facing app (§13).

---

## 10. Contradictions / Remaining Decisions

1. **Roles as a single enum vs. array.** LLD §7 headers imply `role` is admin-XOR-streamer, but §7.1's last line allows an admin to also hold a streamer profile. Resolved by using `roles: ["admin"|"streamer", ...]` as an array on `users` instead of a single `role` field.
2. **Streamer DB provisioning timing.** Chosen: at the moment an admin creates the streamer account (§9.2), not lazily on first claim.
3. **Break delete semantics.** Chosen: soft delete (`status: DELETED`, excluded from totals/availability) so a `BREAK_DELETED` audit event can retain full "before values" per §19.4.
4. **Local app-data location.** Moved to `%LOCALAPPDATA%\ElysiumMasterApp\...` (§8) — required for an installed, non-technical-user app (§13), not a style choice.
5. **"Only one break actively edited at a time" (§14.1). RESOLVED — confirmed hard rule.** Worded as "should" in the LLD; you confirmed the service layer should enforce it as a hard rule (refuses to open a second `ACTIVE` break in the same stream) rather than treat it as an advisory UI nudge.
6. **Atlas tier and cross-database transactions — highest-risk open item, still unresolved.** The whole locking/transaction design (§4) assumes the eventual Atlas cluster supports multi-document ACID transactions spanning multiple databases in one deployment. Standard on modern Atlas replica-set-backed tiers, but must be verified against the *specific* cluster once it's provisioned, before any UI work starts (§12, item 1).
7. **Password hashing algorithm.** Defaulting to Argon2id via `argon2-cffi`.
8. **Credential storage mechanism.** Defaulting to the `keyring` package (Windows Credential Manager backend) — now doing double duty for both the app-level Mongo connection (§13) and any locally-cached secrets.
9. **Version fields alongside transactions.** Kept mainly for UI-level conflict messaging and defense-in-depth, not as the primary correctness mechanism.
10. **Break-level color-slot bidding — closed, not open.** Each break stores one `break_gross` only, per your instruction; matches LLD §28's exclusion.
11. **`streamer_database_key` collision handling — new this revision.** Using generate-then-insert-and-catch-duplicate-key-error, retried a small bounded number of times, rather than a pre-check-then-insert (which would itself race). Flag if you'd prefer a deterministic derivation (e.g. hash of `user_id`) instead of a random token — random was chosen so the key reveals nothing about the user_id/username.
12. **"Any assigned inventory" threshold for the Disable-Account redirect (§4.8). RESOLVED — confirmed as designed.** *Any* nonzero `current_packs` across any product for that streamer, positive or negative, routes Disable Account through Decommissioning instead (an open discrepancy still counts as "assigned").
13. **Reason-edit mutation model (§4.5). RESOLVED — stricter model chosen.** You confirmed `audit_events` must never be mutated under any circumstance. The design now uses a separate `reason_notes` collection (for the two action types with no other live document to hold a reason) plus the existing mutable fields on `streams`/`inventory_discrepancies` (for the other three) — `audit_events` is insert-only, permanently. See §4.5–§4.6.
14. **TCGCSV live response shape — new this revision.** §2.6's field names (`marketPrice`, `subTypeName`, category/group endpoint paths) reflect TCGCSV's publicly documented structure but haven't been confirmed against a live response. Verify before `pricing_service.py` is implemented (§12).

---

## 11. Test Strategy

| Layer | Tooling | Scope |
|---|---|---|
| Unit | `pytest` | Pure logic with no DB: box→pack conversion, price-priority resolution (incl. TCGCSV ambiguity, §2.6), break-availability math, profit/margin formulas, state-machine transition guards, CSV row shaping, shortage-split math (§4.6). |
| Repository/integration | `pytest` + local single-node Mongo **replica set** (Docker), Atlas dev cluster for pre-release validation | Every transactional operation in §4.3, including deliberately racing two concurrent claims/returns to prove no overselling (LLD §29.4/§29.9), **and racing a stream-start against a price-refresh-start to prove the fixed §4.2 lock design admits only one (§11.1)**. Transactions require a replica set — a bare standalone `mongod` cannot run them, so local dev/test tooling needs `--replSet` even for a single node. |
| Acceptance | `pytest`, one test per LLD item | `tests/acceptance/test_29_*.py`, one function per §29.1–§29.20, plus the extension tests in §11.1 — this is the actual go/no-go gate per phase. |
| UI smoke | `pytest-qt` | Critical flows only: login, start stream, add/edit/end break, end stream, claim/return inventory, price refresh happy-path — driven against a real test Mongo instance. |
| Migration/regression | `pytest` | Safe-swap rebuild leaves the prior DB intact if the new import is interrupted/fails; search/filter/sort behavior matches the existing app for a fixed sample dataset. |
| Manual/perf checklist | n/a | Search responsiveness, large CSV export not freezing the UI thread, plus/minus controls feeling instant — checked by hand each phase, automated later if it becomes a real pain point. |

### 11.1 Extension tests added this revision (beyond LLD §29)

| Test | Scenario |
|---|---|
| Global locking race | Two clients simultaneously attempt `start_stream` and `refresh_prices`. Exactly one succeeds; the other gets a clean rejection referencing the other's active operation. |
| TCGCSV batching | Several Elysium products configured with the same `(tcgcsv_category_id, tcgcsv_group_id)` cause exactly one group-dataset download during one refresh session (mocked TCGCSV client asserts call count). |
| TCGCSV ambiguity | A group dataset with two non-"Normal" `subTypeName` rows for one `productId` results in `price_status: AMBIGUOUS`, is listed in `ambiguous_products`, and blocks stream start until resolved. |
| Streamer DB naming | Generated `streamer_database_key` values are short, unique (collision retried), and stable across a subsequent username change. |
| Negative correction — physical safety | Streamer at 2 packs; correction adds 5 more used; admin chooses "allow negative": ledger becomes -3, `master.total_packs` decreases by exactly 2 (never negative), a `NEGATIVE_INVENTORY` discrepancy of 3 is opened, and the invariant checks in §4.6 hold. |
| Negative correction — choice C | Same starting scenario, admin chooses "deduct available": ledger clamps at 0 (never negative), `master.total_packs` still decreases by exactly 2, an `UNDEDUCTED_SHORTAGE` discrepancy of 3 is opened. |
| Unresolved price blocks start | Product with no loose price, no box price, and no previous/manual value remains `UNRESOLVED` (nullable `resolved_pack_price`) and blocks stream start; same assertion for `AMBIGUOUS`. |
| Account deactivation redirect | Streamer with nonzero (positive or negative) inventory cannot be disabled directly — the action routes through Decommissioning instead; a streamer with all-zero inventory, or an admin with no streamer role, disables directly. |
| Reason editing | Streamer may edit their own return reason (`reason_notes`) but not another streamer's; admin may edit any of the five reason-bearing action types; the prior text is recoverable afterward via `reason_notes.history[]` or the fresh `REASON_EDITED` audit event; **and the original `audit_events` document for the underlying action is byte-for-byte unchanged** (asserted by comparing the full document before/after the edit). |

CI note: service/repository/unit tests are OS-agnostic and can run in any CI runner against a Dockerized Mongo replica set; `pytest-qt` UI tests may need a Windows runner (or stay manual-only through early phases) — worth deciding once Phase 1 is underway, not now.

---

## 12. Suggested Next Steps (after you approve this document)

1. Once an Atlas cluster/user/IP-allowlist exist, run `bootstrap/init_database.py` against it and a small standalone script that opens a transaction spanning `elysium_master` and a throwaway `elysium_s_test` database — this resolves the biggest open risk in §10 item 6 before anything else is built. At the same time, make one live TCGCSV category/group/prices request and confirm the response shape assumed in §2.6 (item 14).
2. Run `bootstrap/create_admin.py` once to create the first admin.
3. Build Phase 1 (Card Lookup refactor) per LLD §30, since it has no Mongo dependency and can proceed in parallel with step 1.
4. Build Phase 2 (Mongo foundation/accounts) once step 1 is confirmed.
5. Build the installer/packaging pipeline (§13) early enough to test a real "streamer double-clicks an installer on a clean machine" pass before Phase 5 (streams/breaks) needs real streamer testers.
6. Continue through LLD §30's phases 3–8 in order, with the acceptance tests in §11 as the sign-off gate for each phase touching shared data.

No implementation code will be written until you've reviewed this document and told me to proceed.

---

## 13. Packaging and Distribution for Non-Technical Streamers

The LLD already specifies a Windows desktop app with no continuously-running backend (§5.1) and PyInstaller packaging (§26.1/§27) — this section makes explicit what that means for someone who has never used a terminal.

### 13.1 What a streamer actually experiences

1. You (or an admin) send them one file: an installer, e.g. `ElysiumMasterApplication-Setup-1.0.0.exe`.
2. They double-click it. A standard Windows installer wizard runs (Next → Next → Install), creates a Start Menu / Desktop shortcut, and finishes.
3. They open **Elysium Master Application** from the shortcut like any other program.
4. The **first time only**, if this machine has never connected before, a simple **Connect** screen appears (§13.3) — not a config file, not a terminal.
5. After that, every future launch goes straight to the normal Login screen (username/password, or Continue as Guest).

No Python, no PyCharm, no `pip install`, no environment variables, no `.env` file editing, no command line — ever, for a streamer. Those are all developer-side concerns.

### 13.2 Build pipeline (developer-side, not streamer-facing)

- `PyInstaller` with `packaging/ElysiumMasterApplication.spec` builds a self-contained app folder (`--onedir`, preferred over `--onefile` for faster startup and easier debugging of issues in the field).
- `packaging/installer.iss` (Inno Setup) wraps that folder into a single signed-if-possible `.exe` installer: Start Menu shortcut, optional Desktop shortcut, standard uninstaller registered with Windows.
- This is run by you as part of each release; the output installer is what gets sent to streamers/admins. Not part of Phase 1/2 — targeted for §12 step 5, once there's a real app to package, but the `.spec`/`.iss` skeletons can be scaffolded early.

### 13.3 First-run flow — no Mongo knowledge required, credential baked into the installer

**Confirmed this revision:** the connection string is embedded in the installer at build time — there is no first-run "Connect"/"Setup Code" screen at all. On first launch, the bundled connection is silently stored via `keyring`/Windows Credential Manager and the app goes straight to the normal Login screen (username + password against the `users` collection, §6.1). A streamer never sees, types, or is asked about a MongoDB connection string, ever. `ui/first_connect.py` (§1, §6.1) is removed from the plan.

The tradeoff this accepts: rotating the Atlas connection (e.g. a credential change) requires rebuilding and re-sending an installer rather than just telling someone to paste a new value. Given a small, trusted team and infrequent credential rotation, that's an acceptable simplification — revisit if rotation turns out to be frequent.

The **application login** (username + password) remains the only credential a streamer personally manages day to day.

### 13.4 Updates

Not addressed by the LLD and not designed in detail here — flagged as a decision for later, not blocking Phase 1/2. Simplest viable default for a small trusted team: re-send a new installer when a release ships; running it again over the existing install upgrades in place (standard Inno Setup behavior). Automatic in-app update checking is out of scope unless you want it added later.

---

## Changelog (Revision 1 → Revision 2)

| # | Section(s) touched | Change |
|---|---|---|
| 1 | §2.1, §3.1, §3.2, §4.2, §4.4, §5, §7, §9.1 | Replaced two-document `GLOBAL_STREAM`/`PRICE_REFRESH` locking with one atomically-checked `global_operations` document, closing the start-stream/start-refresh race. Recovery logic now clears each sub-state independently. |
| 2 | §2.1 (`products`), §2.2, §2.6, §3.1, §3.2, §4.3 (Price refresh), §11, §11.1 | Added `tcgcsv_category_id`/`tcgcsv_group_id`; refresh now batches one download per unique group instead of per product; defined exact `subTypeName` resolution priority and the new `AMBIGUOUS` price status for unresolvable multi-row cases; expanded `refresh_sessions` stats. |
| 3 | §2.1 (`users`), §2.3 header, §2.4, §3.2, §9.2, §10 item 11 | Streamer database naming changed from `elysium_streamer_<full UUID>` to `elysium_s_<short streamer_database_key>`; key generated once, immutable, independent of username, unique-indexed with collision retry. |
| 4 | §2.1 (`inventory_discrepancies`), §2.3 (`streams.corrections[]`), §4.6, §11.1, §10 item 12 | Rewrote the master-inventory invariant to separate physical (non-negative) totals from ledger (possibly negative) streamer balances; redefined correction choices A and C with an explicit physical-vs-unbacked split; added the discrepancy-consistency invariant and matching acceptance tests. |
| 5 | §2.2 (`current_prices`), §3.1 | `resolved_pack_price` changed to `Decimal128 \| null`; documented that the `UNRESOLVED`/`AMBIGUOUS` ⇒ nullable rule is service-layer-enforced since `$jsonSchema` can't express the cross-field conditional. |
| 6 | §2.1 (`products`), §2.5, §1 (repo tree), §6.8, §8 | `image_reference` (local path) replaced with `image_url` (shared source URL); added `sealed_image_cache_service.py` and shared `local_assets/image_cache_core.py`. |
| 7 | §4.8, §6.13, §6.14, §10 item 12, §11.1 | Disable Account now redirects into Decommissioning whenever the target streamer holds any nonzero (positive or negative) inventory; both actions blocked while that streamer owns the active stream. |
| 8 | §2.1 (`audit_events`), §4.5, §4.6 (reason-edit reconciliation), §6.16, §10 item 13, §11.1 | Added explicit `audit_service.edit_reason(...)` operation and documented exactly how in-place reason display + a permanent `REASON_EDITED` companion event reconciles with "audit collection is append-only." |
| 9 | §13 (new), §1 (repo tree), §6.1, §8, §10 item 4, §12 | Added packaging/distribution section: Inno Setup installer, no Python/terminal ever touched by a streamer, first-run Connect flow so no one manually configures a Mongo connection string, update strategy flagged as a later decision. |

Everything else — Card Lookup migration plan, test-layer structure, phase ordering, the color-slot-bidding decision, break-flexibility decision — is unchanged from Revision 1, per instruction #9 in `implementation_improvments.md`.

## Changelog (Revision 2 → Revision 3)

| # | Section(s) touched | Change |
|---|---|---|
| 1 | §2.1 (`audit_events`, new `reason_notes`), §3.1, §3.2, §4.5, §4.6, §6.16, §10 item 13, §11.1 | Reason editing redesigned so `audit_events` is never mutated under any circumstance (stricter than Revision 2's in-place-update model, per your answer). Added `reason_notes` collection for the two action types with no other live document to hold a reason (master reduction, streamer return); the other three (corrections, force-cancel, discrepancies) already used mutable fields on `streams`/`inventory_discrepancies`, which was fine all along. |
| 2 | §10 item 12 | Disable-Account inventory threshold confirmed as designed (any nonzero balance, positive or negative) — no change, marked resolved. |
| 3 | §10 item 5 | One-active-break-at-a-time confirmed as a hard rule — no change, marked resolved. |
| 4 | §13.3, §1 (repo tree), §6.1, §11 | Credential distribution confirmed as baked-into-the-installer; removed the first-run "Connect"/"Setup Code" screen and `ui/first_connect.py` from the plan entirely, since it's no longer needed. |
