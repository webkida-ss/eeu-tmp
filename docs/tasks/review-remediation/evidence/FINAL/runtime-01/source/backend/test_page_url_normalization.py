from repositories.page_preload_repository import normalize_page_url


def test_normalize_page_url_strips_trailing_slash_and_hash() -> None:
    assert (
        normalize_page_url("https://www.bbc.com/sport/football/articles/cqj1pd8lqw9o/")
        == "https://www.bbc.com/sport/football/articles/cqj1pd8lqw9o"
    )
    assert (
        normalize_page_url("https://www.bbc.com/sport/football/articles/cqj1pd8lqw9o#section")
        == "https://www.bbc.com/sport/football/articles/cqj1pd8lqw9o"
    )


def test_normalize_page_url_preserves_host() -> None:
    assert normalize_page_url("https://www.bbc.com/foo") == "https://www.bbc.com/foo"
    assert normalize_page_url("https://bbc.com/foo") == "https://bbc.com/foo"
