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
- `20260317-140202`

Generated repo:
- `/Users/o2satz/multiclaw/tmp/medcss-web-modernizer-20260317-140202`

Key artifacts:
- `index.html`
- `README.md`
- `package.json`
- `tests/test-workflow.html`

Validation outcomes:
- `Create exit: 0`
- `Validate exit: 0`
- `Postcheck exit: 0`
- `Checks run: 6`
- `Expectation match: 1.000`

Logs:
- `/Users/o2satz/multiclaw/tmp/medcss_test_logs/medcss_modernizer_create_20260317-140202.log`
- `/Users/o2satz/multiclaw/tmp/medcss_test_logs/medcss_modernizer_validate_20260317-140202.log`
- `/Users/o2satz/multiclaw/tmp/medcss_test_logs/medcss_modernizer_postcheck_20260317-140202.log`

## Acceptance Checks Executed

These checks were executed (not treated as manual text-only checks):

```bash
test -f index.html
test -f README.md
rg -q -i 'current site' .
rg -q -i 'purpose' .
rg -q -i 'design direction' .
rg -q -i 'analyze first' .
```

## Notes

- This proves a real create/validate pass for this showpiece path.
- This does not claim universal autonomous app generation for all requests.
- If you need stronger UX quality enforcement, extend the harness with browser E2E assertions.
