"""Explicit menu-only, readonly entry for bound D2 mass/CG review.

This prototype binds exact schema2 R2 with preserved schema1 audit artifacts. Missing or
changed sources show an unknown reason; they never fall back to proxy/zero CG.
No registration/save/commit/kernel/renderer/history APIs are called here.
"""
import hashlib
import json
from pathlib import Path
from .mass_cg_review import evaluate, model_fingerprint
from .mass_cg_view import make_dialog
from .mass_cg_r2_adapter import adapt_schema2, AdapterProblem

ROOT = Path("C:/Users/keidi/Documents/Codex/2026-09-22/prompt-cad-studio")
DEFAULT_BINDINGS = {
    "contract": {"path": Path("C:/Users/keidi/Documents/Codex/2026-09-28/new-chat/outputs/urc2027/cg-input-candidate-20261012-r2/URC2027_D2_질량_CG_입력계약_R2.json"),
                 "sha256": "669efab05bdad7e4c4ff8569838676dd4f68a6ee49dca785181778b6f2fe60db"},
    "audit": {"path": ROOT / "work/assembly-cg315/result/coordinate-source-audit.json",
              "sha256": "5670fb44c7c63aaa03ff876f648f46256ddd0d7f44f649e06fcc8f6acff5c271"},
    "packet": {"path": ROOT / "work/assembly-cg315/result/normalized-review-input.json",
               "sha256": "055975e3ce47eb85b06d0bfce98b55a9c19c9f0333a40e1d3501d45515918c0e"},
    "report": {"path": Path("C:/Users/keidi/Documents/Codex/2026-09-28/new-chat/outputs/urc2027/drone-design/4kg-redesign/candidate-D2-plated-native-20261011-build3/candidate-D2-report.json"),
               "sha256": "08d2880750dd08a26d2f846430f894b7c8d3455dce4d2ff2fb4568d03e438b53"},
}
SUPPORTED_MODEL = "1fe96d2ecb5c91326bb8dbde47fffbaf63a610f357c6635e53531945a816eacb"


class InputProblem(ValueError):
    def __init__(self, code, message, path=None):
        super().__init__(message)
        self.code, self.path = code, str(path) if path else None


def strict_json(raw):
    def invalid(value):
        raise ValueError("Nonfinite JSON number: " + value)
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("Duplicate JSON key: " + key)
            obj[key] = value
        return obj
    return json.loads(raw.decode("utf-8-sig"), parse_constant=invalid, object_pairs_hook=unique)


def read_bound_json(name, bindings):
    bound = bindings[name]
    path = Path(bound["path"])
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            raise InputProblem("input_too_large", "검토 입력의 예상 크기를 넘었습니다.", path)
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise InputProblem("missing_" + name, "연결된 질량·CG 검토 자료가 없습니다.", path) from exc
    except OSError as exc:
        raise InputProblem("unreadable_" + name, "질량·CG 검토 자료를 읽을 수 없습니다.", path) from exc
    if hashlib.sha256(raw).hexdigest() != bound["sha256"]:
        raise InputProblem("changed_" + name, "자료가 검토된 버전과 다릅니다. 해당 계약·출처의 새 검토가 필요합니다.", path)
    try:
        value = strict_json(raw)
    except (ValueError, UnicodeError) as exc:
        raise InputProblem("corrupt_" + name, "검토 자료의 JSON 또는 숫자가 손상되었습니다.", path) from exc
    if not isinstance(value, dict):
        raise InputProblem("invalid_" + name, "검토 자료의 최상위 형식이 올바르지 않습니다.", path)
    return value


def read_document_review(document, *, bindings=None):
    """Does not mutate Document.design/history/path/prompt/dirty or selection.

    bindings is an internal test seam; the menu always uses DEFAULT_BINDINGS.
    This candidate accepts exact schema2/R2 only. Frozen schema1 candidate is
    preserved separately and is not a fallback for unknown input revisions.
    """
    result = {"ok": False, "scope": "entire_saved_design_not_selected_part",
              "review": None, "reason_code": None, "reason": None, "source_path": None,
              "actual_complete_mass_g": None, "actual_complete_CG_world_mm": None,
              "readonly": True, "kernel_calls": 0, "model_mutations": 0}
    try:
        design = document.design
        if design is None:
            raise InputProblem("no_design", "먼저 설계를 여세요. 전체 질량·CG는 선택 부품 검사와 별도입니다.")
        if not isinstance(design, dict) or not isinstance(design.get("parts"), list):
            raise InputProblem("invalid_active_design", "현재 설계의 저장 데이터 형식이 올바르지 않습니다.")
        if not design["parts"]:
            raise InputProblem("no_parts", "현재 설계에 부품이 없습니다.")
        current = model_fingerprint(design)
        contract = read_bound_json("contract", bindings or DEFAULT_BINDINGS)
        audit = read_bound_json("audit", bindings or DEFAULT_BINDINGS)
        packet = read_bound_json("packet", bindings or DEFAULT_BINDINGS)
        expected_contract = (bindings or DEFAULT_BINDINGS)["contract"]["sha256"]
        if packet.get("schema") != "cadstudio.mass-cg-input-review-1" or packet.get("model_fingerprint") != SUPPORTED_MODEL:
            raise InputProblem("packet_binding_mismatch", "명목·실측 입력과 좌표 검토의 연결이 맞지 않습니다.")
        if current != SUPPORTED_MODEL:
            ids = [p.get("id") for p in design["parts"] if isinstance(p, dict)]
            expected_ids = packet["part_ids"]
            code = "stale_model_pose_or_dependencies" if sorted(ids) == sorted(expected_ids) else "different_design"
            raise InputProblem(code, "이 계약은 검토된 드론 D2 형상·자세에만 연결됩니다. 현재 설계 또는 형상·배치·에셋·구속이 달라 재검토가 필요합니다.")
        report = read_bound_json("report", bindings or DEFAULT_BINDINGS)
        packet = adapt_schema2(contract,audit,packet,report,expected_contract,design)
        review = evaluate(packet, current)
        result.update(ok=True, review=review,
                      actual_complete_mass_g=review["actual_complete_mass_g"],
                      actual_complete_CG_world_mm=review["actual_complete_CG_world_mm"],
                      contract_sha256=expected_contract,
                      input_revision="schema2 R2 · 669efab0 · 원본 보존 · 구매20개 좌표 출처 미확인 유지")
    except AdapterProblem as exc:
        result.update(reason_code="R2_provenance_rejected", reason="R2 계약의 출처·소유량·좌표 상태가 검토 근거와 맞지 않습니다. " + str(exc))
    except InputProblem as exc:
        result.update(reason_code=exc.code, reason=str(exc), source_path=exc.path)
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError) as exc:
        result.update(reason_code="invalid_review_data", reason="설계 또는 검토 입력이 파손되어 계산할 수 없습니다. 자료를 다시 확인하세요.",
                      diagnostic_type=type(exc).__name__)
    return result


def make_review_dialog(parent, result):
    language = getattr(getattr(parent, "language_service", None), "language", "ko")
    if result["ok"]:
        return make_dialog(parent, result["review"], language)
    from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QDialogButtonBox
    from PySide6.QtCore import Qt
    dialog = QDialog(parent)
    dialog.setWindowTitle("Whole assembly mass / CG input review · unknown" if language == "en" else "전체 질량·무게중심 입력 검토 · 미확인")
    dialog.resize(760, 330)
    layout = QVBoxLayout(dialog)
    text = "전체 설계 검토 · 선택 부품 검사와 별도\n\n실제 전체 질량: 미확인\n실제 전체 CG: 미확인\n\n" + result["reason"]
    if language == "en":
        text = "Entire design · separate from selected-part inspection\n\nActual complete mass: Unknown\nActual complete CG: Unknown\n\n"
        if result["reason_code"] in ("no_design", "no_parts"):
            text += "Open a design with parts before reviewing whole assembly mass / CG."
        elif result["reason_code"].startswith("missing_"):
            text += "The linked mass / CG review source is missing."
        elif result["reason_code"] in ("different_design", "stale_model_pose_or_dependencies"):
            text += "This contract binds the reviewed D2 geometry and pose. The current design, shape, pose, asset or mate requires a new review."
        else:
            text += "The linked input is changed, unreadable, corrupted or incompatible. A new source / contract review is required."
        text += "\nReason: " + result["reason_code"]
    if result["source_path"]:
        text += ("\n\nSource: " if language == "en" else "\n\n자료: ") + result["source_path"]
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(label)
    button = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    button.rejected.connect(dialog.reject)
    layout.addWidget(button)
    return dialog
