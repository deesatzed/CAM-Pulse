"""Command-line interface for medcss-modernizer."""
import argparse
import sys
from typing import List, Optional

from . import __version__
from .modernizer import generate_modernization_report, generate_html_outline


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="medcss-modernizer",
        description="Generate modernization reports and HTML landing page outlines for medical/healthcare websites.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--site",
        required=True,
        help="Description of the current site (e.g., 'legacy clinic site with dense text')",
    )
    parser.add_argument(
        "--purpose",
        required=True,
        help="Primary purpose of the site (e.g., 'increase trust and appointment conversions')",
    )
    parser.add_argument(
        "--ideas",
        required=True,
        help="Design ideas or preferences (e.g., 'minimal, airy, modern medical')",
    )
    parser.add_argument(
        "--out",
        default="modernization_report.md",
        help="Output file for the markdown modernization report (default: modernization_report.md)",
    )
    parser.add_argument(
        "--html-out",
        default="landing_page.html",
        help="Output file for the sample HTML landing page outline (default: landing_page.html)",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point for the CLI."""
    parser = create_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # Return the exit code so help/version return 0, invalid args return non-zero
        return int(exc.code)

    # Generate the report and HTML outline
    report_content = generate_modernization_report(
        site_description=args.site,
        site_purpose=args.purpose,
        design_ideas=args.ideas,
    )
    html_content = generate_html_outline(
        site_description=args.site,
        site_purpose=args.purpose,
        design_ideas=args.ideas,
    )

    # Write the files
    try:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report_content)
        with open(args.html_out, "w", encoding="utf-8") as f:
            f.write(html_content)
    except OSError as e:
        print(f"Error writing output files: {e}", file=sys.stderr)
        return 1

    print(f"Modernization report written to: {args.out}")
    print(f"HTML landing page outline written to: {args.html_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())