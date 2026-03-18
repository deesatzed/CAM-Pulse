# CAM Showpiece: medCSS Website Aesthetic Modernizer

This showpiece demonstrates a full CAM create workflow using `medCSS.md` as style inspiration input, with explicit validation and postcheck gates.

The point is not "agent said success". The point is that CAM produced a runnable standalone repo and passed executable checks.

## Goal

Create a standalone web app that:
- asks for current site URL or description
- asks for site purpose
- asks for design ideas/design direction
- supports an "Analyze First" path before recommendation output
- defaults to a light/non-dark modern direction
- returns structured recommendations for typography, color, layout, motion, and accessibility

## Repro Command

```bash
OPENROUTER_API_KEY=... GOOGLE_API_KEY=... ./scripts/test_medcss_modernizer.sh
```

Script:
- [scripts/test_medcss_modernizer.sh](../scripts/test_medcss_modernizer.sh)

What the harness does:
- reads style context from `medCSS.md`
- runs `cam create --execute` with explicit spec items
- runs `cam validate` against the generated create spec
- runs direct postchecks in the generated repo
- fails if create logs contain hidden rejection markers even with exit code 0

## Most Recent Passing Run

Run timestamp:
- `20260318-130044`

Generated repo:
- `/Users/o2satz/multiclaw/tmp/medcss-modernizer-showpiece`
- versioned copy in main repo: [`apps/medcss_modernizer_showpiece`](../apps/medcss_modernizer_showpiece)

Key artifacts:
- `app/cli.py`
- `app/modernizer.py`
- `demo_report.md`
- `demo_landing.html`

Validation outcomes:
- first generation pass failed (syntax/import defects), then repaired and revalidated
- repaired acceptance checks:
  - `pytest -q`: `16 passed`
  - `python -m app.cli --help`: passed
  - `python -m app.cli --site ... --purpose ... --ideas ... --out demo_report.md --html-out demo_landing.html`: passed
  - `test -f demo_report.md`: passed
  - `test -f demo_landing.html`: passed
  - `grep -q 'Modernization Recommendations' demo_report.md`: passed
- `cam validate` on create spec: `Checks run: 6`, `Expectation match: 1.000`

Spec file:
- `/Users/o2satz/multiclaw/data/create_specs/20260318-130044-medcss-modernizer-showpiece-create-spec.json`

## Acceptance Checks Executed

These checks were executed (not treated as manual text-only checks):

```bash
pytest -q
python -m app.cli --help
python -m app.cli --site 'legacy clinic site with dense text' --purpose 'increase trust and appointment conversions' --ideas 'minimal, airy, modern medical' --out demo_report.md --html-out demo_landing.html
test -f demo_report.md
test -f demo_landing.html
grep -q 'Modernization Recommendations' demo_report.md
```

## Notes

- This proves a real create/validate pass for this showpiece path.
- This does not claim universal autonomous app generation for all requests.
- If you need stronger UX quality enforcement for this CLI showpiece, add snapshot-style assertions over generated markdown/html artifacts.
