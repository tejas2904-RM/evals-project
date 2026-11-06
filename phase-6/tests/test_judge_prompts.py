import re


def test_judge_prompt_sections_and_placeholders(settings):
    text = settings.judge_prompts_path.read_text(encoding="utf-8")
    sections = dict(re.findall(r"^## (\w+)\n(.*?)(?=^## |\Z)", text, flags=re.M | re.S))
    assert {"judge_grounded", "judge_helpful_compliant", "changelog"} <= set(sections)
    assert {"{query}", "{context}", "{answer}"} <= set(re.findall(r"\{\w+\}", sections["judge_grounded"]))
    assert {"{query}", "{answer}", "{in_scope}"} <= set(re.findall(r"\{\w+\}", sections["judge_helpful_compliant"]))


def test_judge_prompts_are_binary(settings):
    text = settings.judge_prompts_path.read_text(encoding="utf-8")
    for name in ("judge_grounded", "judge_helpful_compliant"):
        section = text.split(f"## {name}", 1)[1].split("\n## ", 1)[0]
        assert '{"pass": true|false, "reason": "<one sentence>"}' in section
        assert not re.search(r"scale of|rate .* from 1|score", section, flags=re.I)
