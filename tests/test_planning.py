from vibeharness.planning import AgentPlan, make_plan_tools


def test_set_and_query_plan():
    p = AgentPlan()
    out = p.set_plan([
        {"id": "a", "text": "do A"},
        {"id": "b", "text": "do B", "status": "in_progress"},
    ])
    assert len(out["items"]) == 2
    assert "1 in_progress" in out["summary"]


def test_update_status():
    p = AgentPlan()
    p.set_plan([{"id": "a", "text": "do A"}])
    out = p.update_item("a", status="done")
    assert out["items"][0]["status"] == "done"
    assert "1 done" in out["summary"]


def test_invalid_status_rejected():
    p = AgentPlan()
    p.set_plan([{"id": "a", "text": "do A"}])
    out = p.update_item("a", status="weird")
    assert "error" in out


def test_unknown_id_rejected():
    p = AgentPlan()
    p.set_plan([{"id": "a", "text": "do A"}])
    assert "error" in p.update_item("nope", status="done")


def test_empty_plan_summary():
    assert AgentPlan().get_plan()["summary"] == "(empty plan)"


def test_make_plan_tools_round_trip():
    p = AgentPlan()
    tools = make_plan_tools(p)
    by_name = {t.name: t for t in tools}
    assert {"set_plan", "update_plan_item", "get_plan"} == set(by_name)
    by_name["set_plan"].func(items=[{"id": "x", "text": "do x"}])
    assert p.items[0].id == "x"
