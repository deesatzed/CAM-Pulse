# Methodology Quota & Governance Tuning

**Audience**: CAM operators who want to understand and adjust the methodology quota.

---

## What the Quota Does

The methodology quota limits how many active methodologies your knowledge base can hold. When the quota is reached:

1. **Mining stops storing new methodologies** until space is freed
2. **Composition is blocked** (no new composite patterns created)
3. **Governance sweep culls** the lowest-fitness methodologies to make room

The lifecycle system handles cleanup automatically: methodologies that repeatedly fail in builds transition through `embryonic → declining → dormant → dead`, and dead methodologies are garbage collected.

---

## Default: 5,000

```toml
[governance]
max_methodologies = 5000
```

At 5,000 methodologies, a typical CAM database is ~150-200 MB. SQLite handles this without performance issues. Embedding search remains fast (top-K retrieval, not full scan).

---

## When to Increase

Check your current usage:

```bash
cam govern stats
```

If you see quota usage above 80%, consider increasing:

```toml
# In claw.toml
[governance]
max_methodologies = 10000  # Double it
```

**Before increasing, check your resources:**

```bash
# Database size
ls -lh data/claw.db

# Disk space available
df -h data/
```

**Rule of thumb**: Each 1,000 methodologies uses ~30-40 MB of database space.

| Quota | Approx DB Size | Recommended For |
|-------|---------------|-----------------|
| 5,000 | ~150-200 MB | Single domain specialist |
| 10,000 | ~300-400 MB | Multi-domain instance |
| 25,000 | ~750 MB - 1 GB | Heavy mining across many domains |
| 50,000 | ~1.5-2 GB | Research/archival use |

---

## Setting Unlimited (0)

```toml
[governance]
max_methodologies = 0  # 0 = unlimited
```

**Use with caution.** Without a quota, the only thing preventing unbounded growth is the lifecycle system. If you run the PULSE daemon continuously, methodology count can reach 100K+ in months, which degrades:

- **Embedding search latency** (more vectors to compare)
- **Fitness computation time** (more methodologies to evaluate)
- **Database size** (can exceed 2+ GB)

### Why unlimited is risky

A single PULSE scan can create up to **300 methodologies** (20 repos x 15 findings/repo). The daemon polls every 30 minutes. Without a quota:

- Daily growth: ~480 methodologies from mining alone
- Monthly: ~14,400
- Yearly: ~175,000

The lifecycle system prunes low-performers, but only after they've been tested in builds. Freshly mined (embryonic) methodologies haven't been tested yet, so they accumulate.

### If you set unlimited anyway

Compensate with tighter mining controls:

```toml
[governance]
max_methodologies = 0
max_db_size_mb = 1000  # Hard warning at 1 GB

[pulse]
max_repos_per_scan = 10    # Reduce from default 20
max_cost_per_day_usd = 5.0 # Reduce daily spend
```

And monitor regularly:

```bash
cam govern stats
```

---

## Governance Sweep

The governance sweep runs automatically every N cycles (default: 10) and on startup. It performs:

1. **Lifecycle transitions** — advance/demote methodologies based on fitness
2. **Garbage collection** — remove dead methodologies from all stores
3. **Quota enforcement** — cull lowest-fitness if over limit
4. **Episode pruning** — apply retention policy

You can trigger a manual sweep:

```bash
cam govern sweep
```

Or just enforce the quota:

```bash
cam govern quota
```

### Cull priority

When over quota, governance culls in this order:
1. **Dormant** (lowest fitness, haven't been used in a long time)
2. **Declining** (fitness trending down)
3. **Embryonic** (never used in a build)

**Never culled**: Thriving and Viable methodologies are always protected.

---

## Other Governance Settings

```toml
[governance]
max_methodologies = 5000        # Methodology cap (0 = unlimited)
quota_warning_pct = 0.80        # Warn at 80% usage
gc_dead_on_sweep = true         # Auto-remove dead methodologies
dedup_similarity_threshold = 0.88  # Block near-duplicate saves
dedup_enabled = true            # Enable deduplication
episodic_retention_days = 90    # Keep episodes for 90 days
sweep_interval_cycles = 10      # Sweep every 10 build cycles
sweep_on_startup = true         # Sweep when CAM starts
max_db_size_mb = 500            # DB size warning threshold
```

---

## Quick Reference

```bash
# Check quota usage
cam govern stats

# Run a full governance sweep
cam govern sweep

# Enforce quota only (cull if over)
cam govern quota

# Change quota (edit claw.toml, then verify)
# max_methodologies = 10000
cam govern stats
```
