import pytest

from app.integrations.llm import parse_draft_result


def test_parse_draft_result_accepts_allowed_category():
    raw = '{"category": "product_question", "needs_attention": false, "attention_reason": "", "draft": "Version A"}'
    result = parse_draft_result(raw)

    assert result.category == "product_question"
    assert result.needs_attention is False
    assert result.attention_reason == ""
    assert result.draft == "Version A"


def test_parse_draft_result_rejects_invalid_json():
    with pytest.raises(ValueError):
        parse_draft_result('{"category": "product_question"}')


def test_parse_draft_result_requires_attention_for_sensitive_categories():
    with pytest.raises(ValueError):
        parse_draft_result('{"category": "refund", "needs_attention": false, "attention_reason": "", "draft": "Version A"}')


def test_parse_draft_result_requires_reason_when_attention_is_needed():
    with pytest.raises(ValueError):
        parse_draft_result('{"category": "legal", "needs_attention": true, "attention_reason": "", "draft": "Version A"}')
