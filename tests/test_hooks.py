from vibeharness.agent import Agent
from vibeharness.hooks import HookManager, load_user_hooks
from vibeharness.llm import AssistantTurn, ToolCall
from vibeharness.permissions import PermissionPolicy


class Provider:
    name = "fake"; model = "x"
    def __init__(self, script):
        self.script = list(script)
    def complete(self, system, messages, tools, max_tokens=4096, on_text_delta=None):
        return self.script.pop(0) if self.script else AssistantTurn(text="(done)")


def test_before_hook_can_deny(tmp_path):
    def deny_writes(name, args):
        if name == "write_file":
            raise PermissionError("nope")
        return args

    mgr = HookManager()
    mgr.add_before(deny_writes)

    captured: list[dict] = []
    agent = Agent(
        provider=Provider([
            AssistantTurn(tool_calls=[ToolCall(id="c", name="write_file",
                args={"path": str(tmp_path / "x.txt"), "content": "no"})]),
            AssistantTurn(text="done"),
        ]),
        permissions=PermissionPolicy(mode="auto"),
    )
    agent.hook_manager = mgr
    agent.hooks.on_tool_end = lambda tc, r: captured.append(r)
    agent.run("try")
    assert "error" in captured[0]
    assert not (tmp_path / "x.txt").exists()


def test_after_hook_can_modify_result(tmp_path):
    def annotate(name, args, result):
        if name == "list_dir":
            result["annotated"] = True
        return result

    mgr = HookManager()
    mgr.add_after(annotate)
    captured: list[dict] = []
    agent = Agent(
        provider=Provider([
            AssistantTurn(tool_calls=[ToolCall(id="c", name="list_dir",
                args={"path": str(tmp_path)})]),
            AssistantTurn(text="done"),
        ]),
        permissions=PermissionPolicy(mode="auto"),
    )
    agent.hook_manager = mgr
    agent.hooks.on_tool_end = lambda tc, r: captured.append(r)
    agent.run("ls")
    assert captured[0].get("annotated") is True


def test_load_user_hooks_missing_file(tmp_path):
    mgr = load_user_hooks(tmp_path / "nope.py")
    assert mgr.before == [] and mgr.after == []


def test_load_user_hooks_from_disk(tmp_path):
    p = tmp_path / "hooks.py"
    p.write_text(
        "def before_tool(name, args):\n    return args\n"
        "def after_tool(name, args, result):\n    result['tagged']=1; return result\n"
    )
    mgr = load_user_hooks(p)
    assert len(mgr.before) == 1 and len(mgr.after) == 1


def test_checkpoint_fires_after_each_tool_round(tmp_path):
    counter = {"n": 0}
    agent = Agent(
        provider=Provider([
            AssistantTurn(tool_calls=[ToolCall(id="a", name="list_dir", args={"path": str(tmp_path)})]),
            AssistantTurn(tool_calls=[ToolCall(id="b", name="list_dir", args={"path": str(tmp_path)})]),
            AssistantTurn(text="done"),
        ]),
        permissions=PermissionPolicy(mode="auto"),
    )
    agent.on_checkpoint = lambda: counter.__setitem__("n", counter["n"] + 1)
    agent.run("hi")
    assert counter["n"] == 2  # two tool rounds → two checkpoints
