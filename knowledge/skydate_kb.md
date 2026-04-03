# SkyDate Domain Knowledge Base

## Purpose
Domain knowledge for SkyDate -- a historical date exploration app with cascading temporal lenses.
This KB helps code generation agents understand calendar conversion rules, database patterns,
API contracts, and confidence scoring when building SkyDate features.

## Core Concept: Cascading Temporal Lenses
SkyDate presents historical events through four temporal lenses, each matching by a different date axis:

| Lens key             | Label              | Match logic                                                        |
|----------------------|--------------------|--------------------------------------------------------------------|
| `original_date`      | Recorded then      | Matches the date as it was originally recorded (e.g. Julian)       |
| `modern_equivalent`  | Converted now      | Matches the modern Gregorian equivalent after calendar conversion  |
| `same_time_of_year`  | Same time of year  | Matches the same solar-position bucket (1..366)                    |
| `hebrew_equivalent`  | Hebrew equivalent  | Matches the same Hebrew month and day                              |

A fifth lens, `same_sky`, is reserved for future implementation (approximate sky-state matching).

Primary lens selection priority (from `choosePrimaryLens`):
1. If an exact match exists and its recorded month/day matches input but its modern month/day differs, use `original_date` (highlights the calendar shift).
2. Else if `modern_equivalent` has events, use it.
3. Else if `original_date` has events, use it.
4. Else if `same_time_of_year` has events, use it.
5. Fallback to `hebrew_equivalent`.

## Calendar Conversion Rules

### Julian/Gregorian Reform Dates by Jurisdiction
The `jurisdictions` table stores per-jurisdiction reform metadata:
- `reform_start_date DATE` -- the date the jurisdiction switched from Julian to Gregorian.
- `default_calendar_system_id` -- links to `calendar_systems` (gregorian, julian, proleptic_gregorian, proleptic_julian, hebrew, unknown).
- `default_dating_convention_id` -- links to `dating_conventions` (jan1_year_start, lady_day_year_start, sunset_day_boundary, unknown).

Key reform examples:
- Catholic states adopted Gregorian in October 1582 (skipped Oct 5-14).
- England and colonies adopted in September 1752 (skipped Sep 3-13).
- Russia adopted in February 1918.
- Greece adopted in 1923.

For dates before a jurisdiction's reform, the calendar system is Julian. After, it is Gregorian. Pre-46 BCE dates use proleptic Julian or proleptic Gregorian extension.

### Old Style Year Boundary
The `dating_conventions` table tracks whether a jurisdiction used January 1 or March 25 (Lady Day) as the start of the year. England used Lady Day until 1752. This means a date recorded as "February 10, 1664" in an English source is actually February 10, 1665 in modern reckoning. The calendar engine must adjust the year when `lady_day_year_start` convention applies and the original month is January, February, or March 1-24.

### Proleptic Extension
Dates before the reform are converted using proleptic Gregorian rules for normalization. The `normalized_gregorian_date` field in `event_dates` always stores the proleptic or actual Gregorian date regardless of the original calendar system. This enables uniform querying across all time periods.

## Hebrew Calendar

### Fields in event_dates
- `hebrew_year INTEGER` -- year in the Hebrew calendar (e.g. 5176 for Agincourt).
- `hebrew_month INTEGER` -- month number (1=Nisan, 7=Tishrei; Adar II is 13 in leap years).
- `hebrew_day INTEGER` -- day of the Hebrew month.
- `hebrew_after_sunset BOOLEAN` -- whether the moment falls after sunset (Hebrew day begins at sunset).

### Metonic Cycle
The Hebrew calendar follows a 19-year Metonic cycle where years 3, 6, 8, 11, 14, 17, and 19 are leap years with an extra month (Adar II, month 13). The `hebrew_month` field uses 1-13 numbering.

### Sunset Boundary
Hebrew days begin at sunset. The `afterSunset` input flag and `hebrew_after_sunset` stored flag track this. When `afterSunset` is true, the Hebrew date is one day ahead of the civil date. The UI shows the after-sunset toggle when `input.hour >= 18`.

### Hebrew Lens Matching
Events match on `hebrew_equivalent` lens when both `fingerprint.hebrewMonth` and `fingerprint.hebrewDay` match the event's `hebrewMonth` and `hebrewDay`. Both must be non-null.

## Confidence Scoring Model

### Three-Score System in event_dates
| Column                       | Type          | Default | Meaning                                                                 |
|------------------------------|---------------|---------|-------------------------------------------------------------------------|
| `date_certainty_score`       | NUMERIC(4,3)  | 0.500   | How certain we are about the original date itself (source quality)      |
| `conversion_certainty_score` | NUMERIC(4,3)  | 0.500   | How certain we are about the calendar conversion (reform ambiguity)     |
| `overall_confidence_score`   | NUMERIC(4,3)  | 0.500   | Blended score combining date certainty and conversion certainty         |

All scores are 0.000 to 1.000. The `confidence` field on catalog entries (used in sorting) maps to `overall_confidence_score`.

### Score Drivers
- **date_certainty_score** rises with: multiple corroborating sources, primary source availability, well-attested events. Falls with: single secondary source, disputed dates, approximate/range dates.
- **conversion_certainty_score** rises with: post-reform dates (no conversion needed, score near 1.0), unambiguous jurisdiction. Falls with: ambiguous jurisdiction at reform boundary, proleptic extension across millennia, Old Style year boundary ambiguity.
- **overall_confidence_score** blends both. Post-reform Gregorian events with strong sources score 0.95-0.99. Pre-reform events with clear Julian provenance score 0.85-0.95. Ancient or disputed dates score 0.30-0.70.

### Source Trust
The `source_systems` table has `source_rank NUMERIC(4,3)` and `event_sources` has `source_trust_score NUMERIC(4,3)`. Each source (wikidata, usgs, noaa, gvp, uspto, loc, manual) carries a baseline trust rank that factors into `date_certainty_score`.

### Event-Level Confidence in Sorting
Events within a lens are sorted by `confidence DESC, title ASC` (from `sortEvents`). Higher confidence events surface first.

## Temporal Fingerprint Algorithm

### buildTemporalFingerprint(input, catalog)
Computes a fingerprint object from user input:
```
{
  year:           input.year or null,
  month:          input.month or null,
  day:            input.day or null,
  hour:           input.hour or null,
  minute:         input.minute or null,
  place:          input.place or '',
  afterSunset:    Boolean(input.afterSunset),
  completeness:   'full_date' if year present, else 'month_day',
  solarDayBucket: computeSolarDayBucket(input),
  hebrewMonth:    from exact catalog match or null,
  hebrewDay:      from exact catalog match or null,
  exactMatch:     first catalog entry matching normalized or recorded date
}
```

### computeSolarDayBucket({year, month, day})
Returns the 1-based day-of-year (1..366). If month or day is missing, returns null. Uses a resolved year (defaults to 2024 if year is null) to compute:
```
resolvedYear = year ?? 2024
start = Date.UTC(resolvedYear, 0, 1)
current = Date.UTC(resolvedYear, month - 1, day)
bucket = floor((current - start) / 86400000) + 1
```
The `solar_day_bucket SMALLINT` column in `event_dates` stores this value (1..366) and is indexed for fast same-time-of-year queries.

### Exact Match Lookup
`lookupExactCatalogMatch` tries two strategies:
1. Match on `normalizedGregorianDate` (formatted as `YYYY-MM-DD`).
2. Match on `recordedYear`, `recordedMonth`, `recordedDay`.
Returns the first match found, or null.

### Completeness
- `full_date`: year, month, and day are all provided. All four lenses are available.
- `month_day`: only month and day provided. Solar bucket and month/day lenses work; year-specific matching is skipped.

## PostgreSQL Schema Patterns

### UUID Primary Keys
All tables use `UUID PRIMARY KEY DEFAULT uuid_generate_v4()`. Requires the `uuid-ossp` extension.

### Lookup Tables with Code Fields
Reference tables (`calendar_systems`, `dating_conventions`, `jurisdictions`, `event_categories`, `significance_bands`, `source_systems`, `event_tags`) use a `code TEXT NOT NULL UNIQUE` column for application-level lookups and a `display_name TEXT NOT NULL` for UI rendering.

### Denormalized Query Keys (event_query_keys)
The `event_query_keys` table pre-computes string keys for fast indexed lookups:
- `original_month_day_key TEXT` -- e.g. "10-25" for October 25
- `modern_month_day_key TEXT` -- e.g. "11-03" for November 3
- `solar_bucket_key TEXT` -- e.g. "307"
- `hebrew_month_day_key TEXT` -- e.g. "08-15"
- `sky_bucket_key TEXT` -- reserved for future same-sky mode
- `century_key TEXT` -- e.g. "15" for 1400s
- `geography_key TEXT` -- for geographic filtering

All key columns are indexed. This pattern avoids multi-column composite index lookups during query time.

### Indexes on event_dates
- `idx_event_dates_original_md` on `(original_month, original_day)` -- original_date lens
- `idx_event_dates_modern_md` on `(modern_month, modern_day)` -- modern_equivalent lens
- `idx_event_dates_solar_bucket` on `(solar_day_bucket)` -- same_time_of_year lens
- `idx_event_dates_hebrew_md` on `(hebrew_month, hebrew_day)` -- hebrew_equivalent lens
- `idx_event_dates_normalized_gregorian` on `(normalized_gregorian_date)` -- exact date lookup

### Cascade Deletes
`event_dates`, `event_sources`, and `event_tag_map` all use `ON DELETE CASCADE` from `events(id)`. Deleting an event removes all associated dates, sources, and tags.

### Automatic Timestamps
The `set_updated_at()` trigger function on the `events` table auto-sets `updated_at = now()` on every UPDATE. `created_at` columns use `DEFAULT now()`.

### Ingest Tracking
The `ingest_runs` table tracks bulk import operations with `started_at`, `completed_at`, `status` (running/completed/failed), and counters (`inserted_count`, `updated_count`, `error_count`).

## API Contract (OpenAPI 3.0.3)

### POST /v1/convert
Convert an input date into all supported temporal lenses.
- **Required body**: `{ year: int, month: int (1-12), day: int (1-31) }`
- **Optional body**: `hour: int (0-23)`, `minute: int (0-59)`, `place: string`, `afterSunset: boolean (default false)`
- **Response 200**: Conversion result with normalized dates across all calendar systems.

### POST /v1/fingerprint
Compute the temporal fingerprint for a date. Same input shape as /v1/convert.
- **Response 200**: Fingerprint object (year, month, day, completeness, solarDayBucket, hebrewMonth, hebrewDay, exactMatch).

### POST /v1/events/search
Search historical events by temporal mode.
- **Required body**: `mode` (one of: original_date, modern_equivalent, same_time_of_year, hebrew_equivalent, same_sky) and `date` object `{ year, month, day }`.
- **Optional filters**: `categories: string[]`, `centuries: int[]`, `geography: string[]`, `minConfidence: number`.
- **Pagination**: `{ limit: int (default 20), offset: int (default 0) }`.
- **Response 200**: Array of matching events sorted by confidence DESC, title ASC.

### GET /v1/events/{eventId}
Fetch full event details by UUID.
- **Path param**: `eventId` (UUID format).
- **Response 200**: Full event object with dates, sources, tags, and conversion notes.

## Event Data Model

### Split Truth Card Pattern
Each event has two date representations:
1. **Original/recorded**: `recordedYear`, `recordedMonth`, `recordedDay`, `recordedDate` (text), `calendarSystem`, `jurisdiction` -- the date as it appeared in the historical source.
2. **Normalized/modern**: `normalizedGregorianDate` (DATE), `modernMonth`, `modernDay` -- the proleptic Gregorian equivalent.

These can differ significantly. Example from catalog:
- Battle of Agincourt: recorded as October 25, 1415 (Julian), normalized to 1415-11-03 (Gregorian). The 9-day offset reflects the Julian/Gregorian drift in the 15th century.
- Seneca Falls Convention: recorded as July 19, 1848 (already Gregorian), no conversion needed.

### Significance Bands
The `significance_bands` table defines four levels with a `rank_weight NUMERIC(5,2)`:
- `local` -- local significance (e.g., town founding)
- `regional` -- regional significance (e.g., state-level political event)
- `global` -- global significance (e.g., world war battle)
- `canonical` -- universally known events (e.g., moon landing)

### Event Categories
Stored in `event_categories` with optional `parent_code` for hierarchy:
- `birth`, `death` -- biographical events
- `battle` -- military conflicts
- `political` -- governance, treaties, conventions
- `earthquake`, `eruption`, `climate` -- natural events
- `invention`, `discovery` -- scientific/technological milestones

### Source Provenance
Each event links to one or more `event_sources`, each tied to a `source_system`:
- `wikidata` -- Wikidata knowledge graph
- `usgs` -- U.S. Geological Survey (earthquakes)
- `noaa` -- National Oceanic and Atmospheric Administration (climate)
- `gvp` -- Global Volcanism Program (eruptions)
- `uspto` -- U.S. Patent and Trademark Office (inventions)
- `loc` -- Library of Congress
- `manual` -- hand-curated entries

Each source record includes: `source_record_id`, `source_url`, `source_title`, `source_date_text`, `source_quote_excerpt`, `source_trust_score`, and `is_primary` flag.

### Catalog Entry Shape (JavaScript/API)
```
{
  slug: string,              // URL-safe unique identifier
  title: string,             // display title
  category: string,          // event_categories.code
  summary: string,           // short description
  placeName: string,         // human-readable location
  recordedDate: string,      // original date as text (e.g. "25 October 1415")
  recordedYear: int,
  recordedMonth: int,
  recordedDay: int,
  calendarSystem: string,    // julian | gregorian | proleptic_gregorian | ...
  jurisdiction: string,      // jurisdictions.code
  normalizedGregorianDate: string,  // ISO date "YYYY-MM-DD"
  modernMonth: int,
  modernDay: int,
  solarDayBucket: int,       // 1..366
  hebrewMonth: int,
  hebrewDay: int,
  confidence: float,         // 0.0 to 1.0 (maps to overall_confidence_score)
  conversionNotes: string,
  uncertaintyNotes: string
}
```

## Service Boundaries
The architecture defines four services:
- `calendar-core` -- deterministic date parsing, calendar resolution, solar position, Hebrew conversion, explanation generation, confidence scoring.
- `catalog-api` -- event CRUD, search by temporal mode, filtering, pagination, ranking.
- `ingest-worker` -- source adapters, category enrichment, date normalization, key precomputation, provenance insertion.
- `frontend-web` -- Next.js app with mode selector, date input, timeline, event cards, explanation drawer.

## Caching Strategy
Cache keys are composed from: input date, mode, filters, locale/jurisdiction, and after-sunset toggle. This means the same date queried with and without afterSunset produces different cache entries (because the Hebrew date shifts).

## whyMatched Explanation Strings
Each event in a lens result includes a `whyMatched` explanation:
- original_date: "Matched on the original recorded date of {event.recordedDate}."
- modern_equivalent: "Matched the modern Gregorian date {event.normalizedGregorianDate}."
- same_time_of_year: "Matched the same solar-position bucket ({fingerprint.solarDayBucket})."
- hebrew_equivalent: "Matched the Hebrew date {event.hebrewMonth}/{event.hebrewDay}."
