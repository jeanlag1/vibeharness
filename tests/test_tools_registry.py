from vibeharness.tools import build_default_registry, dispatch


def test_registry_has_expected_tools():
    reg = build_default_registry()
    expected = {
        "read_file", "write_file", "edit_file", "grep", "glob_files", "list_dir",
        "bash", "bash_background", "bash_read", "bash_stop",
    }
    assert expected.issubset(reg.keys())


def test_anthropic_schema_shape():
    reg = build_default_registry()
    schema = reg["edit_file"].to_anthropic()
    assert schema["name"] == "edit_file"
    assert "description" in schema
    assert schema["input_schema"]["type"] == "object"
    assert "old" in schema["input_schema"]["properties"]


def test_openai_schema_shape():
    reg = build_default_registry()
    schema = reg["bash"].to_openai()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "bash"


def test_dispatch_unknown():
    reg = build_default_registry()
    out = dispatch(reg, "not_a_tool", {})
    assert "error" in out


def test_dispatch_read_write(tmp_path):
    reg = build_default_registry()
    p = tmp_path / "x.txt"
    dispatch(reg, "write_file", {"path": str(p), "content": "yo"})
    out = dispatch(reg, "read_file", {"path": str(p)})
    assert out["content"] == "yo"


def test_dispatch_bad_args(tmp_path):
    reg = build_default_registry()
    out = dispatch(reg, "read_file", {})  # missing path
    assert "error" in out


def test_mutating_flags():
    reg = build_default_registry()
    assert reg["read_file"].mutating is False
    assert reg["write_file"].mutating is True
    assert reg["bash"].mutating is True
