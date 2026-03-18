"""Tests for the modernizer module."""
from app.modernizer import (
    _analyze_site_description,
    _analyze_purpose,
    _analyze_design_ideas,
    generate_modernization_report,
    generate_html_outline,
)


class TestAnalysisFunctions:
    """Test analysis functions."""

    def test_analyze_site_description(self):
        """Test site description analysis."""
        analysis = _analyze_site_description("legacy clinic site with dense text")
        assert analysis["content_density"] == "very high"
        assert analysis["complexity"] == "moderate"
        assert analysis["current_style"] == "traditional"

    def test_analyze_purpose(self):
        """Test purpose analysis."""
        analysis = _analyze_purpose("increase trust and appointment conversions")
        assert analysis["primary_goal"] == "convert"
        assert analysis["conversion_focus"] == "high"
        assert analysis["trust_needed"] == "very high"

    def test_analyze_design_ideas(self):
        """Test design ideas analysis."""
        analysis = _analyze_design_ideas("minimal, airy, modern medical")
        assert analysis["style_preference"] == "modern"
        assert analysis["color_palette"] == "neutral"
        assert analysis["layout_preference"] == "airy"


class TestReportGeneration:
    """Test report generation."""

    def test_generate_modernization_report(self):
        """Test that report generation works and contains expected sections."""
        report = generate_modernization_report(
            site_description="legacy clinic site with dense text",
            site_purpose="increase trust and appointment conversions",
            design_ideas="minimal, airy, modern medical",
        )
        assert "# Medical Website Modernization Report" in report
        assert "## Current Site Analysis" in report
        assert "## Purpose Analysis" in report
        assert "## Design Preferences" in report
        assert "## Modernization Recommendations" in report
        assert "## Implementation Roadmap" in report
        # Check that recommendations are present
        assert "1." in report  # At least one numbered recommendation

    def test_report_contains_recommendations(self):
        """Test that specific recommendations are generated."""
        report = generate_modernization_report(
            site_description="simple informative site",
            site_purpose="educate patients",
            design_ideas="corporate, professional",
        )
        assert "Ensure mobile-first responsive design" in report
        assert "Improve page load performance" in report


class TestHTMLOutline:
    """Test HTML outline generation."""

    def test_generate_html_outline(self):
        """Test that HTML outline is valid and contains key elements."""
        html = generate_html_outline(
            site_description="test site",
            site_purpose="test purpose",
            design_ideas="minimal",
        )
        assert "<!DOCTYPE html>" in html
        assert "<html lang=\"en\">" in html
        assert "<title>Modern Medical Practice</title>" in html
        assert "Book Appointment" in html
        assert "<footer class=\"footer\">" in html

    def test_html_contains_styles(self):
        """Test that HTML contains CSS styles."""
        html = generate_html_outline(
            site_description="test",
            site_purpose="test",
            design_ideas="airy",
        )
        assert "<style>" in html
        assert "</style>" in html
        assert "body {" in html

    def test_html_different_styles(self):
        """Test that different design ideas produce different HTML."""
        html_minimal = generate_html_outline("test", "test", "minimal")
        html_airy = generate_html_outline("test", "test", "airy")
        html_clean = generate_html_outline("test", "test", "corporate")
        # They should be different
        assert html_minimal != html_airy
        assert html_airy != html_clean
        # Minimal should have specific style
        assert "background: #f8f9fa" in html_minimal
        # Airy should have larger padding
        assert "padding: 7rem 2rem" in html_airy
