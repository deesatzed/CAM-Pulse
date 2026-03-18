# medcss-modernizer

A standalone Python CLI application that generates modernization reports and sample HTML landing page outlines for medical/healthcare websites.

## Features

- Analyzes current site description, site purpose, and design ideas
- Generates a practical markdown modernization report with:
  - Current site analysis
  - Purpose analysis
  - Design preferences
  - Specific, actionable recommendations
  - Implementation roadmap
- Creates a sample modern HTML landing page outline with:
  - Responsive design
  - Healthcare-appropriate styling
  - Call-to-action elements
  - Different style variations (minimal, airy, clean)

## Installation

Clone the repository and install dependencies:

```bash
git clone <repository-url>
cd medcss-modernizer
pip install -r requirements.txt
```

## Usage

Run the CLI tool with required arguments:

```bash
python -m app.cli \
  --site "legacy clinic site with dense text" \
  --purpose "increase trust and appointment conversions" \
  --ideas "minimal, airy, modern medical" \
  --out modernization_report.md \
  --html-out landing_page.html
```

### Arguments

- `--site` (required): Description of the current site
- `--purpose` (required): Primary purpose of the site
- `--ideas` (required): Design ideas or preferences
- `--out`: Output file for the markdown report (default: `modernization_report.md`)
- `--html-out`: Output file for the HTML outline (default: `landing_page.html`)
- `--version`: Show version information
- `--help`: Show help message

## Output Files

1. **Modernization Report** (`modernization_report.md`): Contains analysis and recommendations
2. **HTML Landing Page Outline** (`landing_page.html`): A sample HTML page with modern design

## Examples

### Example 1: Minimal Modern Design
```bash
python -m app.cli \
  --site "outdated family practice website" \
  --purpose "attract new patients and build trust" \
  --ideas "minimal, clean, professional" \
  --out family_practice_report.md \
  --html-out family_practice_landing.html
```

### Example 2: Vibrant Pediatric Clinic
```bash
python -m app.cli \
  --site "colorful pediatric clinic site" \
  --purpose "provide information and schedule appointments" \
  --ideas "vibrant, friendly, approachable" \
  --out pediatric_report.md \
  --html-out pediatric_landing.html
```

## Development

### Running Tests

```bash
pytest -q
```

### Code Structure

```
medcss-modernizer/
├── app/
│   ├── __init__.py       # Package version
│   ├── cli.py            # Command-line interface
│   └── modernizer.py     # Core modernization logic
├── tests/
│   ├── test_cli.py       # CLI tests
│   └── test_modernizer.py # Modernizer tests
├── README.md
└── requirements.txt
```

## License

MIT License

## Version

1.0.0