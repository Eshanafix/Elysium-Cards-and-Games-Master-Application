# Atlas Backup Configuration

Per the LLD (section 27.4) and `docs/IMPLEMENTATION_PLAN.md`, this application deliberately has **no custom backup or restore functionality** — no export/import of raw collections, no scheduled dump job, nothing. All durability and recovery is delegated to **MongoDB Atlas's own automated backup system**. This document is the operational counterpart to that decision: how to actually turn it on and use it, since the app itself will never do it for you.

## 1. Check what your cluster tier supports

Atlas Cloud Backups (continuous, point-in-time-restorable snapshots) require a **dedicated cluster (M10 or higher)**. The free **M0 / M2 / M5 shared tiers do not support Cloud Backups** — there is no snapshot/restore feature available on them at all.

- If your cluster is M10+: continue to section 2.
- If your cluster is M0/M2/M5 (the common free-tier starting point): Atlas gives you no built-in backup mechanism. Your options are:
  1. **Upgrade the cluster to M10+** once the business relies on this data for real (recommended before go-live with real inventory/financial data) — this is a few minutes' operation in Atlas, no application changes needed, the app just keeps using the same connection string.
  2. In the meantime, take occasional manual exports via `mongodump` (a MongoDB Database Tools CLI, not part of this application) against the same connection string, stored somewhere safe. This is a stopgap, not a substitute for real automated backups.

## 2. Enable Cloud Backups (M10+ clusters)

1. In the [Atlas UI](https://cloud.mongodb.com), select the project containing this cluster.
2. Go to the cluster's **Backup** tab (left sidebar, or via **Database** → your cluster → **Backup**).
3. If not already enabled, click **Enable Backup** (this may already be on by default for M10+ clusters created recently).
4. Under **Backup Policy**, configure a snapshot schedule. A reasonable starting point for this app's usage pattern (streamed breaks happen in bursts, not continuously):
   - **Snapshot frequency:** every 6 hours (or Atlas's default).
   - **Retention:** keep daily snapshots for at least 7 days, weekly for 4-5 weeks, monthly for a few months. Adjust retention length based on how far back you'd realistically need to recover (e.g. "streamer disputes a break from 3 weeks ago").
5. Confirm **Continuous Cloud Backup / Point-in-Time Recovery** is enabled if you want to restore to an arbitrary moment (not just a snapshot boundary) — useful given this app's multi-document transactions (a stream settlement, a decommission approval) should be restored as a whole, not mid-transaction.

## 3. Restoring

Restores happen entirely inside the Atlas UI, never through this application:

1. **Backup** tab → find the snapshot (or point-in-time) you want.
2. Choose **Restore** → either:
   - Restore into a **new cluster** (safest — lets you inspect/verify the restored data before touching production), then repoint `MONGODB_URI` at it once verified, or
   - Restore **in place** onto the existing cluster (faster, but overwrites current data — only do this if you're certain).
3. After an in-place restore, no application changes are needed — connection string, databases, and collection names are unchanged. Just relaunch the app.

## 4. What this does NOT cover

- **Local card data** (`%LOCALAPPDATA%\ElysiumMasterApp\cards.sqlite`, image caches) is intentionally excluded — it's rebuildable per-machine from Scryfall's public bulk data via **Refresh Card Data**, and is not centrally important company data (LLD 27.4). No backup needed for it.
- **Credentials** (the admin's Atlas password, any streamer's app password) are never stored in a backup-relevant place inside the app — Atlas backups only ever contain what's already in the database (password hashes, not plaintext).
- This document does not, and should not, ever be replaced by in-app backup/export code. If a future business need calls for scheduled data exports, prefer configuring Atlas's own scheduled export-to-cloud-storage feature (also in the Backup tab, "Export Policy") over adding that logic to this app.
