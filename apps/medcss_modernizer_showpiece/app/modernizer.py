"""Core modernization logic for generating reports and HTML outlines."""
from typing import Dict, List


def _analyze_site_description(description: str) -> Dict[str, str]:
    """Analyze site description for key characteristics."""
    analysis = {
        "complexity": "moderate",
        "content_density": "high",
        "current_style": "traditional",
    }
    desc_lower = description.lower()
    if "dense" in desc_lower or "cluttered" in desc_lower:
        analysis["content_density"] = "very high"
    if "simple" in desc_lower or "minimal" in desc_lower:
        analysis["complexity"] = "low"
    if "modern" in desc_lower:
        analysis["current_style"] = "semi-modern"
    return analysis


def _analyze_purpose(purpose: str) -> Dict[str, str]:
    """Analyze site purpose for key objectives."""
    analysis = {
        "primary_goal": "inform",
        "conversion_focus": "low",
        "trust_needed": "high",
    }
    purpose_lower = purpose.lower()
    if "convert" in purpose_lower or "appointment" in purpose_lower:
        analysis["conversion_focus"] = "high"
        analysis["primary_goal"] = "convert"
    if "trust" in purpose_lower or "credibility" in purpose_lower:
        analysis["trust_needed"] = "very high"
    if "educate" in purpose_lower or "inform" in purpose_lower:
        analysis["primary_goal"] = "educate"
    return analysis


def _analyze_design_ideas(ideas: str) -> Dict[str, str]:
    """Analyze design ideas for style preferences."""
    analysis = {
        "style_preference": "modern",
        "color_palette": "neutral",
        "layout_preference": "clean",
    }
    ideas_lower = ideas.lower()
    if "minimal" in ideas_lower:
        analysis["layout_preference"] = "minimal"
    if "airy" in ideas_lower or "spacious" in ideas_lower:
        analysis["layout_preference"] = "airy"
    if "color" in ideas_lower or "vibrant" in ideas_lower:
        analysis["color_palette"] = "vibrant"
    if "corporate" in ideas_lower or "professional" in ideas_lower:
        analysis["style_preference"] = "professional"
    return analysis


def generate_modernization_report(
    site_description: str,
    site_purpose: str,
    design_ideas: str,
) -> str:
    """Generate a markdown modernization report."""
    site_analysis = _analyze_site_description(site_description)
    purpose_analysis = _analyze_purpose(site_purpose)
    design_analysis = _analyze_design_ideas(design_ideas)

    # Build the report content deterministically
    sections = []
    sections.append("# Medical Website Modernization Report\n")
    sections.append("## Current Site Analysis\n")
    sections.append(f"**Description**: {site_description}\n")
    sections.append(f"- Content Density: {site_analysis['content_density']}\n")
    sections.append(f"- Complexity: {site_analysis['complexity']}\n")
    sections.append(f"- Current Style: {site_analysis['current_style']}\n")

    sections.append("## Purpose Analysis\n")
    sections.append(f"**Purpose**: {site_purpose}\n")
    sections.append(f"- Primary Goal: {purpose_analysis['primary_goal']}\n")
    sections.append(f"- Conversion Focus: {purpose_analysis['conversion_focus']}\n")
    sections.append(f"- Trust Requirement: {purpose_analysis['trust_needed']}\n")

    sections.append("## Design Preferences\n")
    sections.append(f"**Ideas**: {design_ideas}\n")
    sections.append(f"- Style Preference: {design_analysis['style_preference']}\n")
    sections.append(f"- Color Palette: {design_analysis['color_palette']}\n")
    sections.append(f"- Layout Preference: {design_analysis['layout_preference']}\n")

    sections.append("## Modernization Recommendations\n")
    recommendations = _generate_recommendations(
        site_analysis, purpose_analysis, design_analysis
    )
    for i, rec in enumerate(recommendations, 1):
        sections.append(f"{i}. {rec}\n")

    sections.append("## Implementation Roadmap\n")
    sections.append("1. **Phase 1: Planning & Content Audit** - Review existing content and structure\n")
    sections.append("2. **Phase 2: Design System Creation** - Establish colors, typography, components\n")
    sections.append("3. **Phase 3: Frontend Development** - Build responsive, accessible interface\n")
    sections.append("4. **Phase 4: Content Migration & Optimization** - Rewrite and restructure content\n")
    sections.append("5. **Phase 5: Testing & Launch** - User testing, performance optimization, deployment\n")

    return "\n".join(sections)


def _generate_recommendations(
    site_analysis: Dict[str, str],
    purpose_analysis: Dict[str, str],
    design_analysis: Dict[str, str],
) -> List[str]:
    """Generate specific recommendations based on analysis."""
    recommendations = []

    # Content and layout recommendations
    if site_analysis["content_density"] in ["high", "very high"]:
        recommendations.append(
            "Implement a content hierarchy with clear headings, subheadings, and visual breaks"
        )
        recommendations.append(
            "Use progressive disclosure techniques to reveal complex information gradually"
        )

    # Trust and conversion recommendations
    if purpose_analysis["trust_needed"] in ["high", "very high"]:
        recommendations.append(
            "Add prominent trust signals: certifications, doctor credentials, patient testimonials"
        )
    if purpose_analysis["conversion_focus"] == "high":
        recommendations.append(
            "Place clear call-to-action buttons (e.g., 'Book Appointment') in strategic locations"
        )
        recommendations.append(
            "Simplify appointment booking forms to reduce friction"
        )

    # Design recommendations
    if design_analysis["layout_preference"] == "minimal":
        recommendations.append(
            "Adopt a minimalist design with ample whitespace and limited color palette"
        )
    elif design_analysis["layout_preference"] == "airy":
        recommendations.append(
            "Create generous spacing between elements and use light, open layouts"
        )

    if design_analysis["color_palette"] == "vibrant":
        recommendations.append(
            "Use a vibrant accent color sparingly to draw attention to key actions"
        )
    else:
        recommendations.append(
            "Use a neutral, professional color scheme with healthcare-appropriate blues/greens"
        )

    # Always include these core recommendations
    recommendations.append(
        "Ensure mobile-first responsive design for all screen sizes"
    )
    recommendations.append(
        "Improve page load performance through image optimization and lazy loading"
    )
    recommendations.append(
        "Implement accessibility standards (WCAG 2.1 AA) for all users"
    )

    return recommendations


def generate_html_outline(
    site_description: str,
    site_purpose: str,
    design_ideas: str,
) -> str:
    """Generate a sample HTML landing page outline."""
    design_analysis = _analyze_design_ideas(design_ideas)
    purpose_analysis = _analyze_purpose(site_purpose)

    # Determine style based on analysis
    if design_analysis["layout_preference"] == "minimal":
        style_class = "minimal"
    elif design_analysis["layout_preference"] == "airy":
        style_class = "airy"
    else:
        style_class = "clean"

    # Build HTML content
    html_parts = []
    html_parts.append("<!DOCTYPE html>")
    html_parts.append('<html lang="en">')
    html_parts.append("<head>")
    html_parts.append('    <meta charset="UTF-8">')
    html_parts.append('    <meta name="viewport" content="width=device-width, initial-scale=1.0">')
    html_parts.append('    <title>Modern Medical Practice</title>')
    html_parts.append('    <style>')
    html_parts.append(_get_css_styles(style_class))
    html_parts.append("    </style>")
    html_parts.append("</head>")
    html_parts.append("<body>")
    html_parts.append('    <header class="header">')
    html_parts.append('        <nav class="nav">')
    html_parts.append('            <div class="logo">MedicalCare</div>')
    html_parts.append('            <ul class="nav-links">')
    html_parts.append('                <li><a href="#services">Services</a></li>')
    html_parts.append('                <li><a href="#about">About</a></li>')
    html_parts.append('                <li><a href="#contact">Contact</a></li>')
    html_parts.append('            </ul>')
    html_parts.append('            <a href="#book" class="cta-button">Book Appointment</a>')
    html_parts.append('        </nav>')
    html_parts.append('    </header>')

    html_parts.append('    <section class="hero">')
    html_parts.append('        <div class="hero-content">')
    html_parts.append('            <h1>Quality Healthcare for Your Family</h1>')
    html_parts.append('            <p>Compassionate, modern medical care in a comfortable environment.</p>')
    if purpose_analysis["conversion_focus"] == "high":
        html_parts.append('            <a href="#book" class="cta-button">Schedule Your Visit</a>')
    html_parts.append('        </div>')
    html_parts.append('    </section>')

    html_parts.append('    <section id="services" class="services">')
    html_parts.append('        <h2>Our Services</h2>')
    html_parts.append('        <div class="service-cards">')
    html_parts.append('            <div class="card">')
    html_parts.append('                <h3>General Checkups</h3>')
    html_parts.append('                <p>Comprehensive health assessments for all ages.</p>')
    html_parts.append('            </div>')
    html_parts.append('            <div class="card">')
    html_parts.append('                <h3>Preventive Care</h3>')
    html_parts.append('                <p>Screenings and vaccinations to keep you healthy.</p>')
    html_parts.append('            </div>')
    html_parts.append('            <div class="card">')
    html_parts.append('                <h3>Chronic Disease Management</h3>')
    html_parts.append('                <p>Ongoing support for conditions like diabetes and hypertension.</p>')
    html_parts.append('            </div>')
    html_parts.append('        </div>')
    html_parts.append('    </section>')

    html_parts.append('    <section id="about" class="about">')
    html_parts.append('        <h2>About Our Practice</h2>')
    html_parts.append('        <p>We combine modern medical techniques with a personal touch.</p>')
    html_parts.append('        <div class="credentials">')
    html_parts.append('            <div class="credential">Board Certified Physicians</div>')
    html_parts.append('            <div class="credential">State-of-the-Art Equipment</div>')
    html_parts.append('            <div class="credential">Patient-Centered Approach</div>')
    html_parts.append('        </div>')
    html_parts.append('    </section>')

    html_parts.append('    <section id="book" class="booking">')
    html_parts.append('        <h2>Book an Appointment</h2>')
    html_parts.append('        <form class="booking-form">')
    html_parts.append('            <input type="text" placeholder="Your Name" required>')
    html_parts.append('            <input type="email" placeholder="Email Address" required>')
    html_parts.append('            <input type="tel" placeholder="Phone Number" required>')
    html_parts.append('            <select required>')
    html_parts.append('                <option value="">Select Service</option>')
    html_parts.append('                <option value="checkup">General Checkup</option>')
    html_parts.append('                <option value="consultation">Consultation</option>')
    html_parts.append('                <option value="followup">Follow-up Visit</option>')
    html_parts.append('            </select>')
    html_parts.append('            <button type="submit" class="cta-button">Request Appointment</button>')
    html_parts.append('        </form>')
    html_parts.append('    </section>')

    html_parts.append('    <footer class="footer">')
    html_parts.append('        <p>&copy; 2026 MedicalCare. All rights reserved.</p>')
    html_parts.append('    </footer>')
    html_parts.append("</body>")
    html_parts.append("</html>")

    return "\n".join(html_parts)


def _get_css_styles(style_class: str) -> str:
    """Return CSS styles based on the style class."""
    base_styles = """
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        body {
            line-height: 1.6;
            color: #333;
        }
        .header {
            background: #fff;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            position: fixed;
            width: 100%;
            top: 0;
            z-index: 1000;
        }
        .nav {
            display: flex;
            justify-content: space-between;
            align-items: center;
            max-width: 1200px;
            margin: 0 auto;
            padding: 1rem 2rem;
        }
        .logo {
            font-size: 1.5rem;
            font-weight: bold;
            color: #2c3e50;
        }
        .nav-links {
            display: flex;
            list-style: none;
        }
        .nav-links li {
            margin-left: 2rem;
        }
        .nav-links a {
            text-decoration: none;
            color: #333;
            font-weight: 500;
            transition: color 0.3s;
        }
        .nav-links a:hover {
            color: #3498db;
        }
        .cta-button {
            background: #3498db;
            color: white;
            padding: 0.75rem 1.5rem;
            border: none;
            border-radius: 5px;
            text-decoration: none;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.3s;
        }
        .cta-button:hover {
            background: #2980b9;
        }
        .hero {
            background: linear-gradient(rgba(0,0,0,0.5), rgba(0,0,0,0.5)), url('https://images.unsplash.com/photo-1579684385127-1ef15d508118?ixlib=rb-4.0.3&auto=format&fit=crop&w=1350&q=80');
            background-size: cover;
            background-position: center;
            height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
            color: white;
            padding: 0 2rem;
        }
        .hero h1 {
            font-size: 3rem;
            margin-bottom: 1rem;
        }
        .hero p {
            font-size: 1.2rem;
            margin-bottom: 2rem;
            max-width: 600px;
        }
        .services, .about, .booking {
            padding: 5rem 2rem;
            max-width: 1200px;
            margin: 0 auto;
        }
        .services h2, .about h2, .booking h2 {
            text-align: center;
            margin-bottom: 3rem;
            font-size: 2rem;
            color: #2c3e50;
        }
        .service-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 2rem;
        }
        .card {
            background: #f9f9f9;
            padding: 2rem;
            border-radius: 10px;
            box-shadow: 0 3px 10px rgba(0,0,0,0.1);
            transition: transform 0.3s;
        }
        .card:hover {
            transform: translateY(-5px);
        }
        .card h3 {
            margin-bottom: 1rem;
            color: #3498db;
        }
        .credentials {
            display: flex;
            justify-content: center;
            flex-wrap: wrap;
            gap: 2rem;
            margin-top: 2rem;
        }
        .credential {
            background: #e8f4fc;
            padding: 1rem 2rem;
            border-radius: 50px;
            font-weight: 500;
            color: #2c3e50;
        }
        .booking-form {
            max-width: 600px;
            margin: 0 auto;
            display: grid;
            gap: 1rem;
        }
        .booking-form input, .booking-form select {
            padding: 0.75rem;
            border: 1px solid #ddd;
            border-radius: 5px;
            font-size: 1rem;
        }
        .footer {
            background: #2c3e50;
            color: white;
            text-align: center;
            padding: 2rem;
            margin-top: 3rem;
        }
    """

    if style_class == "minimal":
        return base_styles + """
        .hero {
            background: #f8f9fa;
            color: #333;
        }
        .cta-button {
            background: #333;
        }
        .cta-button:hover {
            background: #555;
        }
        """
    elif style_class == "airy":
        return base_styles + """
        body {
            font-size: 1.1rem;
        }
        .hero, .services, .about, .booking {
            padding: 7rem 2rem;
        }
        .card, .booking-form input, .booking-form select {
            border: 2px solid #eee;
        }
        """
    else:  # clean (default)
        return base_styles
