"""An analytical circuit actively solves more than the former 128-node bound."""
import pytest

from cadstudio.electrical import ElectricalWorkspace, evaluate_electrical


def test_large_active_resistor_chain_current_voltages_and_power_balance():
    nodes = ["GND", *(f"N{i:03}" for i in range(1, 141))]
    workspace = ElectricalWorkspace.model_validate(dict(nodes=nodes, components=[
        dict(id="source", name="Analytical 12V source", kind="battery", a="N001", b="GND",
             voltage_v=12, internal_resistance_ohm=.1),
        *(dict(id=f"R{i:03}", name=f"Analytical resistor {i}", kind="resistor", a=f"N{i:03}",
               b=f"N{i+1:03}" if i < 140 else "GND", resistance_ohm=10)
          for i in range(1, 141)),
    ]))
    before = workspace.model_dump()
    result = evaluate_electrical(workspace)
    current = 12 / (140 * 10 + .1)
    assert len(result.node_voltages_v) == 141
    for i in range(1, 141):
        assert result.node_voltages_v[f"N{i:03}"] == pytest.approx(current * (141-i) * 10)
    assert all(branch.current_a == pytest.approx(current) for branch in result.components)
    assert result.source_power_w == pytest.approx((12 - current * .1) * current)
    assert result.absorbed_power_w == pytest.approx(result.source_power_w)
    assert workspace.model_dump() == before
