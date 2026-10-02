"""Offline standards browser keeps exact sources and conditional ratings."""

from datetime import date
from urllib.parse import urlsplit

import pytest

from cadstudio.mechanical_catalog import (CATALOG, format_ai_spec,
                                          get_catalog_entry, get_clearance_hole,
                                          get_socket_head, search_catalog)


OFFICIAL_HOSTS = {
    "www.jst-mfg.com", "www.molex.com", "www.phoenixcontact.com",
    "www.kycon.com", "www.switchcraft.com", "www.belden.com",
    "www.iso.org", "www.bossard.com", "assets.eu.ctfassets.net",
}


def test_catalog_has_unique_exact_records_with_primary_sources_and_units():
    assert len(CATALOG) >= 21
    assert len({entry.catalog_id for entry in CATALOG}) == len(CATALOG)
    for entry in CATALOG:
        assert entry.catalog_id.isascii()
        assert entry.category and entry.manufacturer and entry.model and entry.summary
        assert get_catalog_entry(entry.catalog_id) is entry
        assert entry.sources
        for source in entry.sources:
            parsed = urlsplit(source.url)
            assert parsed.scheme == "https" and parsed.hostname in OFFICIAL_HOSTS
            assert not parsed.username and not parsed.password
            date.fromisoformat(source.retrieved_on)
        for fact in (*entry.ratings, *entry.dimensions):
            assert fact.label and fact.unit is not None and fact.qualifier
            if "전류" in fact.label:
                assert fact.condition, (entry.catalog_id, fact.label)


def test_search_and_clearance_hole_do_not_mix_hole_with_head_or_fit_classes():
    assert get_catalog_entry("phoenix_mstb_2") in search_catalog("Phoenix 1757019")
    assert get_catalog_entry("jst_vh_2") in search_catalog("B2P-VH")
    assert get_catalog_entry("belden_9918") in search_catalog("AWG18")
    assert get_catalog_entry("iso273_medium_m4") in search_catalog("M4 관통홀")
    assert all(e.category == "전선" for e in search_catalog("", "전선"))
    assert search_catalog("해당품번없음") == ()
    hole = get_clearance_hole("m4")
    assert hole and hole.thread == "M4" and hole.fit == "medium"
    assert hole.diameter_mm == pytest.approx(4.5)
    assert get_clearance_hole("M4", "fine") is None
    assert get_clearance_hole("M3") is None
    assert get_catalog_entry("iso4762_head_m4").hole_spec is None
    assert get_socket_head("M4").diameter_mm == pytest.approx(7.0)
    assert get_socket_head("M8").diameter_mm == pytest.approx(13.0)
    assert get_socket_head("M3") is None


def test_power_limits_and_wire_free_air_values_remain_conditional_references():
    molex = get_catalog_entry("molex_minifit_jr_2")
    assert any(f.value == 9 and f.qualifier == "maximum" for f in molex.ratings)
    assert "운전" in format_ai_spec(molex)

    phoenix = get_catalog_entry("phoenix_mstb_2")
    assert set(phoenix.exact_skus) == {"1757019", "1759017"}
    assert "부하 또는 전압" in format_ai_spec(phoenix)
    assert all(f.condition for f in phoenix.ratings if "전류" in f.label)

    wire = get_catalog_entry("belden_9918")
    assert wire.wire_spec.dcr_ohm_per_1000ft == pytest.approx(7.15)
    assert wire.wire_spec.dcr_ohm_per_m == pytest.approx(7.15 / 304.8)
    prompt = format_ai_spec(wire)
    assert "단일 도체, 자유공기, 주변 30 °C" in prompt
    assert "하네스 허용 전류가 아님" in prompt
    assert "명목 도체 DC 저항" in prompt


def test_panel_jack_does_not_fabricate_cutout_or_assume_polarity():
    jack = get_catalog_entry("kycon_kldlx_b")
    assert jack and jack.exact_skus == ("KLDLX-0202-B",)
    assert jack.hole_spec is None
    assert not any("cutout" in fact.label.casefold() for fact in jack.dimensions)
    text = format_ai_spec(jack)
    assert "와셔 내경" in text and "cutout으로 사용하지" in text
    assert "센터핀 극성" in text


def test_native_browser_selects_only_verified_clearance_hole_and_copies_source():
    # A real QApplication is needed, but no CAD viewport or render surface is created.
    from PySide6.QtWidgets import QApplication, QDialog
    from cadstudio.native.mechanical_catalog_dialog import MechanicalCatalogDialog

    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    dialog = MechanicalCatalogDialog(query="M6 관통홀")
    try:
        assert dialog.selected().catalog_id == "iso273_medium_m6"
        dialog.copy_ai_spec()
        copied = dialog.copied_spec
        assert "Ø6.6 mm" in copied and "www.bossard.com" in copied
        assert app._mechanical_catalog_copy == copied
        dialog.choose()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.entry.catalog_id == "iso273_medium_m6"
        assert dialog.hole_spec.diameter_mm == pytest.approx(6.6)
    finally:
        dialog.deleteLater()
        app.processEvents()
