import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from cadstudio import server
from cadstudio.catalog import preset
from cadstudio.models import DraftRequest, Project
from cadstudio.planner import AIReply, local_draft, openai_draft, strict_schema


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(server.app, headers={"X-CAD-Request":"1"}) as client:
        yield client


def test_api_build_and_download(client):
    design = preset("wafer").model_dump()
    assert client.get("/api/status").json()["api_configured"] is False
    assert client.get("/").status_code == 200
    result = client.post("/api/build", json=design)
    assert result.status_code == 200 and result.json()["stats"]["valid"]
    for fmt, prefix in [("step", b"ISO-10303"), ("stl", None)]:
        r = client.post("/api/export/"+fmt, json=design)
        assert r.status_code == 200 and len(r.content) > 200
        assert "attachment" in r.headers["content-disposition"]
        if prefix: assert r.content.startswith(prefix)
    assert client.post("/api/export/py", json=design).status_code == 404


def test_projects_persist_load_validate_and_update(client):
    p = Project(design=preset("robot_arm"), prompt="2링크 로봇 조립").model_dump()
    created = client.post("/api/projects", json=p)
    assert created.status_code == 200
    identifier = created.json()["id"]
    assert client.get("/api/projects/"+identifier).json() == p
    assert client.get("/api/projects").json()[0]["id"] == identifier
    p["design"]["name"] = "바뀐 프로젝트"
    assert client.put("/api/projects/"+identifier, json=p).status_code == 200
    assert client.get("/api/projects/"+identifier).json() == p
    assert client.post("/api/projects/validate", json=p).json()["stats"]["parts"] == 5
    assert client.get("/api/projects/not-a-uuid").status_code == 404


def test_boundary_rejects_cross_origin_bad_host_and_large_body(client):
    design = preset("wafer").model_dump()
    assert client.post("/api/build", json=design, headers={"Origin":"https://untrusted.example"}).status_code == 403
    assert client.post("/api/build", json=design, headers={"X-CAD-Request":""}).status_code == 403
    assert client.get("/api/status", headers={"Host":"attacker.example"}).status_code == 400
    assert client.post("/api/build", content=b"x"*1_000_001).status_code == 413
    assert client.post("/api/build", content=b'{"parts": [NaN]}', headers={"Content-Type":"application/json"}).status_code == 422


def test_invalid_design_does_not_write_project(client):
    p = Project(design=preset("round_specimen")).model_dump()
    p["design"]["parts"][0]["geometry"]["gauge_diameter"] = 100
    response = client.post("/api/projects", json=p)
    assert response.status_code == 422
    assert client.get("/api/projects").json() == []
    assert "input" not in response.text


@pytest.mark.parametrize("prompt,kind,field,value", [
    ("원통형 시편 목 직경 6 mm", "round_specimen", "gauge_diameter", 6),
    ("웨이퍼 직경 10 cm 두께 525 um 플랫 깊이 0", "wafer", "thickness", .525),
    ("평판형 시편 목 폭 8 두께 2", "flat_specimen", "gauge_width", 8),
    ("튜브 직경 30 높이 20 내경 15", "cylinder", "bore_diameter", 15),
    ("링크 길이 120 폭 30 구멍 간격 80 구멍 직경 10", "link", "hole_diameter", 10),
])
def test_local_prompt_dimension_mapping(prompt,kind,field,value):
    result = local_draft(DraftRequest(prompt=prompt))
    g = result["design"]["parts"][0]["geometry"]
    assert g["kind"] == kind and g[field] == pytest.approx(value)


def test_prompt_edits_only_selected_part_and_keeps_assembly():
    design = preset("robot_arm")
    result = local_draft(DraftRequest(prompt="두께 7 mm",current=design,selected_part="link-2"))
    assert len(result["design"]["parts"]) == 5
    assert result["design"]["parts"][2]["geometry"]["thickness"] == 7
    assert result["design"]["parts"][1] == design.parts[1].model_dump()
    added = local_draft(DraftRequest(prompt="브래킷 추가",current=design))
    assert len(added["design"]["parts"]) == 6


def test_missing_api_key_and_unsupported_prompt(client):
    response = client.post("/api/draft",json={"prompt":"원통형 시편", "provider":"openai"})
    assert response.status_code == 422 and "API 키" in response.text
    assert client.post("/api/draft",json={"prompt":"뭔가 멋진 것"}).status_code == 422
    assert client.post("/api/draft",json={"prompt":"원통형 시편 길이 -5"}).status_code == 422
    assert client.post("/api/draft",json={"prompt":"원통형 시편 직경 5"}).status_code == 422


def test_ai_structured_reply_repair_and_no_code_execution():
    valid = AIReply(design=preset("extrusion"),summary="맞춤 부품",assumptions=[]).model_dump_json()
    invalid = json.loads(valid);invalid["design"]["parts"][0]["geometry"]["thickness"] = -5
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="completed",output_text=json.dumps(invalid) if len(calls)==1 else valid)
    result = openai_draft(DraftRequest(prompt="새 판형 부품"),client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    assert result["attempts"] == 2 and result["design"]["parts"][0]["geometry"]["kind"] == "extrusion"
    assert calls[0]["store"] is False and calls[0]["text"]["format"]["strict"] is True
    assert "validation_feedback" in json.loads(calls[1]["input"])
    schema = json.dumps(strict_schema(AIReply.model_json_schema()))
    assert '"oneOf"' not in schema and '"discriminator"' not in schema


def test_ai_refusal_and_provider_error_sanitized(client, monkeypatch):
    fake = SimpleNamespace(responses=SimpleNamespace(create=lambda **_:SimpleNamespace(status="completed",output_text="")))
    with pytest.raises(ValueError):
        openai_draft(DraftRequest(prompt="시편"),client=fake)
    def broken(_):
        raise RuntimeError("Authorization Bearer sk-test-do-not-leak")
    monkeypatch.setattr(server,"openai_draft",broken)
    result = client.post("/api/draft",json={"prompt":"시편","provider":"openai"})
    assert result.status_code == 502 and "sk-test" not in result.text
