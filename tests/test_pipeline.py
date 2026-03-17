def test_pipeline_fetches_email_and_posts_one_draft(pipeline):
    result = pipeline.run("msg-1")

    assert result["category"] == "product_question"
    assert result["needs_attention"] is False
    assert result["draft"]
    assert len(pipeline.slack.posts) == 1


def test_pipeline_loads_thread_history(pipeline):
    email = pipeline.gmail.fetch_email("msg-1")

    assert email.thread_history
    assert "contract" in email.thread_history[0].lower()
