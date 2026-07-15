from src.agent.platform_profile import CAPABILITY_CATALOG, render_static_profile


def test_static_profile_contains_capability_and_boundary_anchors():
    profile = render_static_profile()
    for anchor in ("Conduut", "batch", "dashboard", "Google only", "credential"):
        assert anchor in profile, f"missing anchor: {anchor}"


def test_capability_catalog_is_jargon_free():
    text = CAPABILITY_CATALOG.lower()
    for jargon in ("n8n", "webhook", "node"):
        assert jargon not in text, f"jargon leaked into catalog: {jargon}"


def test_external_trigger_boundary_names_conduut_limit_and_editor_alternative():
    profile = render_static_profile()
    assert "Conduut chat limitation" in profile
    assert "Execute workflow" in profile
