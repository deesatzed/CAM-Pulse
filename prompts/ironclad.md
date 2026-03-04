# Ironclad — Architecture Review

Analyze the repository and evaluate the system design for structural integrity, maintainability, and resilience. Assess against established design principles and identify concrete improvements.

## Instructions

Examine the full architecture: module boundaries, dependency direction, data flow, error propagation, and extension points. Evaluate the design as built, not as documented. The code is the source of truth.

## Required Output Sections

### 1. SOLID Principles Assessment

For each principle, evaluate compliance and provide evidence:

#### Single Responsibility
| Component | Responsibilities Found | Violation? | Evidence |
|-----------|----------------------|------------|----------|
| `src/api.py` | Request handling, validation, DB queries, email sending | YES | Lines 45-200 mix concerns |
| `src/models/user.py` | User data model only | NO | Clean data class |

#### Open/Closed
- Which components can be extended without modification?
- Which require editing source code to add new behavior?
- Are there plugin points, strategy patterns, or dependency injection?

#### Liskov Substitution
- Are there base classes or interfaces? Do all implementations honor the contract?
- Are there `isinstance` checks that break polymorphism?

#### Interface Segregation
- Are interfaces (abstract classes, protocols) focused or bloated?
- Are consumers forced to depend on methods they do not use?

#### Dependency Inversion
- Do high-level modules depend on low-level modules directly?
- Are abstractions used at module boundaries?
- Is dependency injection used or are dependencies hard-wired?

### 2. Coupling Analysis

| Module A | Module B | Coupling Type | Severity | Fix |
|----------|----------|--------------|----------|-----|
| `api` | `database` | Direct import of DB connection | HIGH | Inject via interface |
| `worker` | `config` | Reads global config dict | MEDIUM | Pass config explicitly |

Types: direct import, shared global state, shared database, shared file system, temporal coupling, content coupling

### 3. Cohesion Assessment

| Module | Cohesion Level | Evidence |
|--------|---------------|----------|
| `src/utils.py` | LOW — grab bag of unrelated functions | String utils, date utils, file utils, crypto utils all in one file |
| `src/auth/` | HIGH — all authentication-related | Login, logout, token management, password hashing |

### 4. Data Flow Security Review

Trace data from external input to storage and output:

| Data Path | Input Source | Validation | Sanitization | Storage | Output Encoding | Risk |
|-----------|-------------|------------|-------------|---------|-----------------|------|
| User registration | HTTP POST body | Partial (email only) | None | Raw to DB | None on API response | HIGH — SQL injection possible |
| File upload | Multipart form | Size check only | No content validation | Written to disk | Served directly | CRITICAL — arbitrary file execution |

Check for:
- SQL injection vectors
- XSS vectors
- Path traversal
- Deserialization attacks
- SSRF opportunities
- Authentication bypass paths
- Authorization gaps (horizontal/vertical privilege escalation)

### 5. Scalability Assessment

| Bottleneck | Location | Current Limit | Scaling Strategy |
|------------|----------|--------------|-----------------|
| Single SQLite DB | `db.py` | ~100 concurrent writes | Migrate to PostgreSQL or add write queue |
| Synchronous processing | `worker.py` | 1 task at a time | Add async or worker pool |
| In-memory cache | `cache.py` | Single process | Move to Redis |

### 6. Resilience Review

| Failure Mode | Handled? | Location | Recovery Strategy |
|-------------|----------|----------|-------------------|
| Database unavailable | NO | `db.py` — no retry logic | Add retry with backoff |
| External API timeout | PARTIAL | `client.py:45` — 30s timeout, no retry | Add retry + circuit breaker |
| Disk full | NO | `storage.py` — no space check | Add pre-write check + alert |
| Out of memory | NO | No memory limits | Add resource limits |

### 7. Architectural Improvements

| Priority | Improvement | Current State | Target State | Effort |
|----------|------------|--------------|-------------|--------|
| HIGH | Extract validation layer | Validation scattered in handlers | Centralized validation middleware | Moderate |
| HIGH | Add dependency injection | Hard-wired dependencies | Constructor injection | Significant |
| MEDIUM | Separate read/write models | Single model for all operations | CQRS pattern for complex queries | Significant |

## Output Format

Use the exact section headers and tables above. Every finding must reference specific file paths and line numbers. Distinguish between "nice to have" architectural improvements and "must fix" structural problems.

Focus on actionable findings with file path evidence.
