"""The bolt preview never substitutes a guessed load or whole-joint verdict."""

from datetime import date
import math
from urllib.parse import urlsplit

import pytest

from cadstudio.fastener_checks import (SPECS, check_axial_bolts,
                                       format_axial_check, get_bolt_proof_spec)


@pytest.mark.parametrize("thread,pitch,area,proof_88,proof_109", (
    ("M4", 0.7, 8.78, 5100, 7290),
    ("M5", 0.8, 14.2, 8230, 11800),
    ("M6", 1.0, 20.1, 11600, 16700),
    ("M8", 1.25, 36.6, 21200, 30400),
))
def test_exact_bossard_coarse_pitch_proof_records(thread, pitch, area,
                                                  proof_88, proof_109):
    for strength, stress, load in (("8.8", 580, proof_88),
                                   ("10.9", 830, proof_109)):
        spec = get_bolt_proof_spec(thread, strength)
        assert spec and spec.pitch_mm == pytest.approx(pitch)
        assert spec.stress_area_mm2 == pytest.approx(area)
        assert spec.proof_stress_mpa == stress
        assert spec.published_proof_load_n == load
        assert spec.conservative_proof_force_n == min(load, area * stress)
        assert date.fromisoformat(spec.retrieved_on)
        assert urlsplit(spec.source_url).hostname == "assets.eu.ctfassets.net"
        assert urlsplit(spec.pitch_source_url).hostname == "assets.eu.ctfassets.net"
        assert urlsplit(spec.source_page_url).hostname == "www.bossard.com"
    assert len(SPECS) == 8


def test_axial_check_uses_user_load_equal_share_and_conservative_proof_limit():
    result = check_axial_bolts("M6", "8.8", 1000, 2, 2,
                               assume_equal_sharing=True, applicable_head_geometry=True)
    assert result.actual_force_per_bolt_n == pytest.approx(500)
    assert result.factored_force_per_bolt_n == pytest.approx(1000)
    assert result.factored_tensile_stress_mpa == pytest.approx(1000 / 20.1)
    assert result.stress_utilization == pytest.approx(1000 / (20.1 * 580))
    assert result.table_load_utilization == pytest.approx(1000 / 11600)
    assert result.utilization == pytest.approx(1000 / 11600)
    assert result.proof_margin == pytest.approx(10.6)
    assert result.reference_capacity_total_n == pytest.approx(11600)
    assert result.within_proof_reference
    report = format_axial_check(result)
    assert "1000 N" in report and "볼트 2개" in report
    assert "균등 하중 분담" in report and "피로" in report
    assert "조립체 안전 인증 아님" in report and result.spec.source_url in report
    english = format_axial_check(result, "en")
    assert "not a joint safety certification" in english
    assert "equal load sharing assumed" in english
    assert "does not certify the joint" in english
    assert result.spec.pitch_source_url in english


def test_just_above_proof_and_rounded_table_do_not_get_false_clearance():
    # M4's printed 5,100 N is rounded above 8.78 mm² × 580 MPa.
    at_stress_limit = check_axial_bolts("M4", "8.8", 5092.4, 1, 1,
                                        assume_equal_sharing=True, applicable_head_geometry=True)
    assert at_stress_limit.utilization == pytest.approx(1)
    assert at_stress_limit.within_proof_reference
    above = check_axial_bolts("M4", "8.8", 5093, 1, 1,
                              assume_equal_sharing=True, applicable_head_geometry=True)
    assert above.utilization > 1
    assert above.proof_margin < 0
    assert not above.within_proof_reference


@pytest.mark.parametrize("force,count,safety,share,m8_ok", (
    (None, 2, 2, True, False),
    (0, 2, 2, True, False),
    (-1, 2, 2, True, False),
    (math.nan, 2, 2, True, False),
    (1e-320, 2, 2, True, False),
    (1000, 0, 2, True, False),
    (1000, 1.5, 2, True, False),
    (1000, 2, 0.9, True, False),
    (1000, 2, math.inf, True, False),
    (1000, 2, 2, False, False),
))
def test_missing_invalid_or_unconfirmed_input_cannot_produce_result(
        force, count, safety, share, m8_ok):
    with pytest.raises(ValueError):
        check_axial_bolts("M4", "8.8", force, count, safety,
                          assume_equal_sharing=share,
                          applicable_head_geometry=True,
                          m8_standard_proof_variant=m8_ok)


def test_unsupported_sizes_classes_and_m8_coating_condition_are_rejected():
    assert get_bolt_proof_spec("M3") is None
    assert get_bolt_proof_spec("M4", "12.9") is None
    with pytest.raises(ValueError):
        check_axial_bolts("M8", "8.8", 1000, 2, 2,
                          assume_equal_sharing=True, applicable_head_geometry=True)
    checked = check_axial_bolts("M8", "10.9", 1000, 2, 2,
                                assume_equal_sharing=True,
                                applicable_head_geometry=True,
                                m8_standard_proof_variant=True)
    assert checked.spec.published_proof_load_n == 30400
    assert checked.within_proof_reference


def test_low_head_geometry_is_not_silently_assumed_to_match_proof_table():
    with pytest.raises(ValueError, match="머리"):
        check_axial_bolts("M4", "8.8", 1000, 1, 1,
                          assume_equal_sharing=True)
