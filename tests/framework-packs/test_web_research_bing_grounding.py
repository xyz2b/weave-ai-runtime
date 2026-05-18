import json
import os
from typing import Any
import urllib.parse

import pytest

from weavert_web_research import (
    BackendSearchResult,
    BingGroundingSearchProvider,
    FixtureWebResearchProvider,
    SerpApiGoogleSearchProvider,
    WebResearchPolicy,
    WebSearchProviderRegistry,
    default_web_search_provider_registry,
    search_web,
)


class _JsonResponse:
    headers: dict[str, str] = {}
    status = 200

    def __init__(self, payload: dict[str, Any]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_JsonResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, *_args: object) -> bytes:
        return self._body


def _configured_provider(*, urlopen: Any | None = None) -> BingGroundingSearchProvider:
    return BingGroundingSearchProvider(
        project_endpoint="https://example.services.ai.azure.com/api/projects/demo",
        model_deployment="gpt-4.1-mini",
        bing_connection_id="/subscriptions/s/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/a/projects/p/connections/bing",
        agent_token="token",
        urlopen=urlopen,
        poll_interval=0,
    )


def test_bing_grounding_configuration_and_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "FOUNDRY_PROJECT_ENDPOINT",
        "FOUNDRY_MODEL_DEPLOYMENT_NAME",
        "BING_PROJECT_CONNECTION_ID",
        "AGENT_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    provider = BingGroundingSearchProvider()
    assert provider.configured is False
    assert provider.provider_metadata.provider_id == "bing-grounding"
    assert provider.provider_metadata.capabilities.result_limit is True
    assert provider.provider_metadata.capabilities.domain_filtering is False
    assert provider.provider_metadata.capabilities.freshness is True
    assert provider.provider_metadata.capabilities.fetch is False
    assert provider.provider_metadata.capabilities.page_find is False


def test_bing_grounding_builds_foundry_responses_request_without_bing_v7() -> None:
    captured: list[Any] = []

    def fake_urlopen(request: Any, *, timeout: float) -> _JsonResponse:
        captured.append((request, timeout))
        return _JsonResponse({"output": [{"url": "https://example.com/a", "title": "A"}]})

    provider = _configured_provider(urlopen=fake_urlopen)
    results = provider.search(
        "azure ai search",
        limit=3,
        policy=WebResearchPolicy(
            allowed_domains=("example.com",),
            blocked_domains=("blocked.example",),
            freshness_days=7,
        ),
    )

    request, timeout = captured[0]
    body = json.loads(request.data.decode("utf-8"))
    assert timeout == 30
    assert "/openai/v1/responses" in request.full_url
    assert "api.bing.microsoft.com/v7.0/search" not in request.full_url
    assert body["model"] == "gpt-4.1-mini"
    assert body["input"] == "azure ai search"
    assert body["tool_choice"] == "required"
    assert body["tools"][0]["type"] == "bing_grounding"
    search_config = body["tools"][0]["bing_grounding"]["search_configurations"][0]
    assert search_config["project_connection_id"]
    assert search_config["count"] == 3
    assert search_config["freshness"] == "7d"
    assert "stable http or https URLs" in body["instructions"]
    assert results == [
        BackendSearchResult(
            title="A",
            url="https://example.com/a",
            excerpt="",
            metadata={"provider": "bing-grounding", "grounding_type": None},
        )
    ]


def test_bing_grounding_normalizes_nested_citations_and_skips_unstable_urls() -> None:
    provider = _configured_provider()
    results = provider.normalize_response(
        {
            "output": [
                {
                    "content": [
                        {
                            "annotations": [
                                {"url": "https://example.com/a#fragment", "title": "A", "snippet": "Alpha"},
                                {"url": "mailto:test@example.com", "title": "Mail"},
                                {"title": "No URL"},
                                {"uri": "https://example.com/a", "title": "Duplicate"},
                                {"source_url": "https://example.org/b", "name": "B"},
                            ]
                        }
                    ]
                }
            ]
        },
        limit=10,
    )

    assert [(item.title, item.url, item.excerpt) for item in results] == [
        ("A", "https://example.com/a", "Alpha"),
        ("B", "https://example.org/b", ""),
    ]


def test_bing_grounding_selection_fallback_and_constraint_metadata() -> None:
    bing = FixtureWebResearchProvider(
        provider_id="bing-grounding",
        display_name="Bing Grounding Fixture",
        fail_search=True,
        supports_freshness=True,
    )
    google = FixtureWebResearchProvider(
        provider_id="google-search",
        display_name="Google Fixture",
        search_results={"query": [{"title": "Allowed", "url": "https://allowed.example/page"}]},
        supports_freshness=True,
    )
    registry = WebSearchProviderRegistry((bing, google), default_provider="bing-grounding")

    result = search_web(
        "query",
        registry=registry,
        policy=WebResearchPolicy(
            allowed_domains=("allowed.example",),
            blocked_domains=("blocked.example",),
            freshness_days=3,
            max_search_results=5,
        ),
    )

    assert result["provider"]["id"] == "google-search"
    assert result["provider_selection"]["status"] == "fallback"
    assert result["provider_fallback"]["from"] == "bing-grounding"
    assert result["freshness_scope"]["status"] == "enforced"
    assert result["constraint_outcomes"]["allowed_domains"]["status"] == "enforced"
    assert result["results"][0]["url"] == "https://allowed.example/page"


def test_explicit_bing_grounding_reports_domain_filtering_as_framework_enforced() -> None:
    bing = FixtureWebResearchProvider(
        provider_id="bing-grounding",
        display_name="Bing Grounding Fixture",
        search_results={"query": [{"title": "A", "url": "https://allowed.example/page"}]},
        supports_freshness=False,
    )
    bing.provider_metadata = BingGroundingSearchProvider.provider_metadata
    result = search_web(
        "query",
        registry=WebSearchProviderRegistry((bing,)),
        provider="bing-grounding",
        policy=WebResearchPolicy(
            allowed_domains=("allowed.example",),
            blocked_domains=("blocked.example",),
            freshness_days=2,
        ),
    )

    assert result["provider"]["id"] == "bing-grounding"
    assert result["provider"]["capabilities"]["domain_filtering"] is False
    assert result["constraint_outcomes"]["allowed_domains"]["status"] == "post_filtered"
    assert result["constraint_outcomes"]["blocked_domains"]["status"] == "post_filtered"
    assert result["freshness_scope"]["status"] == "enforced"


def test_default_registry_orders_bing_before_google_and_brave_when_all_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/demo")
    monkeypatch.setenv("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")
    monkeypatch.setenv("BING_PROJECT_CONNECTION_ID", "connection")
    monkeypatch.setenv("AGENT_TOKEN", "token")
    monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "google-key")
    monkeypatch.setenv("GOOGLE_SEARCH_CX", "cx")
    monkeypatch.setenv("SERPAPI_API_KEY", "serpapi-key")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-key")

    registry = default_web_search_provider_registry()

    assert [provider.provider_metadata.provider_id for provider in registry.providers] == [
        "bing-grounding",
        "google-search",
        "serpapi-google-search",
        "brave-search",
        "duckduckgo-html",
    ]


def test_serpapi_google_configuration_and_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)

    unconfigured = SerpApiGoogleSearchProvider()
    assert unconfigured.configured is False
    assert unconfigured.provider_metadata.provider_id == "serpapi-google-search"
    assert unconfigured.provider_metadata.credential_required is True
    assert unconfigured.provider_metadata.capabilities.domain_filtering is True
    assert unconfigured.provider_metadata.capabilities.blocked_domain_filtering is True
    assert unconfigured.provider_metadata.capabilities.result_limit is True
    assert unconfigured.provider_metadata.capabilities.freshness is False
    assert unconfigured.provider_metadata.capabilities.fetch is False
    assert unconfigured.provider_metadata.capabilities.page_find is False

    monkeypatch.setenv("SERPAPI_API_KEY", "serpapi-key")
    assert SerpApiGoogleSearchProvider().configured is True


def test_serpapi_google_maps_request_parameters_domains_and_normalizes_organic_results() -> None:
    requested_urls: list[str] = []

    def fake_urlopen(request: Any, *, timeout: float) -> _JsonResponse:
        assert timeout == 10
        requested_urls.append(request.full_url)
        return _JsonResponse(
            {
                "organic_results": [
                    {
                        "position": 1,
                        "title": "Parenting guide",
                        "link": "https://docs.example.test/guide#section",
                        "snippet": "Representative organic result",
                        "displayed_link": "docs.example.test",
                        "source": "Example Docs",
                        "date": "May 2026",
                        "favicon": "https://docs.example.test/favicon.ico",
                    },
                    {
                        "title": "Outside",
                        "link": "https://outside.example.test/page",
                        "snippet": "Filtered by core",
                    },
                ],
                "ai_overview": {"references": [{"link": "https://ai.example.test/reference"}]},
                "related_questions": [{"question": "What is this?", "link": "https://questions.example.test"}],
                "related_searches": [{"query": "related"}],
                "pagination": {"next": "https://serpapi.com/search.json?start=10"},
            }
        )

    provider = SerpApiGoogleSearchProvider(
        api_key="serpapi-token",
        google_domain="google.com",
        hl="en",
        gl="us",
        urlopen=fake_urlopen,
    )
    result = search_web(
        "育儿指南",
        provider="serpapi-google-search",
        registry=WebSearchProviderRegistry((provider,)),
        policy=WebResearchPolicy(
            allowed_domains=("docs.example.test",),
            blocked_domains=("old.example.test",),
            freshness_days=7,
            max_search_results=8,
        ),
    )

    parsed = urllib.parse.urlparse(requested_urls[0])
    query_params = urllib.parse.parse_qs(parsed.query)
    assert query_params["engine"] == ["google"]
    assert query_params["api_key"] == ["serpapi-token"]
    assert query_params["q"] == ["育儿指南 (site:docs.example.test) -site:old.example.test"]
    assert query_params["num"] == ["8"]
    assert query_params["google_domain"] == ["google.com"]
    assert query_params["hl"] == ["en"]
    assert query_params["gl"] == ["us"]
    assert result["provider"]["id"] == "serpapi-google-search"
    assert result["provider"]["capabilities"]["freshness"] is False
    assert result["freshness_scope"] == {"requested_days": 7, "status": "unsupported"}
    assert result["constraint_outcomes"]["allowed_domains"]["status"] == "enforced"
    assert result["constraint_outcomes"]["blocked_domains"]["status"] == "enforced"
    assert [item["url"] for item in result["results"]] == ["https://docs.example.test/guide"]
    assert result["results"][0]["metadata"]["provider_result_metadata"] == {
        "position": 1,
        "displayed_link": "docs.example.test",
        "source": "Example Docs",
        "date": "May 2026",
        "favicon": "https://docs.example.test/favicon.ico",
    }


def test_default_registry_includes_serpapi_and_explicit_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERPAPI_API_KEY", "serpapi-key")
    monkeypatch.setenv("WEAVERT_WEB_SEARCH_PROVIDER", "serpapi-google-search")
    monkeypatch.delenv("FOUNDRY_PROJECT_ENDPOINT", raising=False)
    monkeypatch.delenv("FOUNDRY_MODEL_DEPLOYMENT_NAME", raising=False)
    monkeypatch.delenv("BING_PROJECT_CONNECTION_ID", raising=False)
    monkeypatch.delenv("AGENT_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_SEARCH_CX", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("WEAVERT_BRAVE_SEARCH_API_KEY", raising=False)

    registry = default_web_search_provider_registry()

    assert [provider.provider_metadata.provider_id for provider in registry.providers] == [
        "serpapi-google-search",
        "duckduckgo-html",
    ]
    _events, plan = registry.plan()
    assert [provider.provider_metadata.provider_id for provider in plan] == [
        "serpapi-google-search",
        "duckduckgo-html",
    ]


def test_serpapi_fallback_and_freshness_preference_planning() -> None:
    serpapi = FixtureWebResearchProvider(
        provider_id="serpapi-google-search",
        display_name="SerpAPI Fixture",
        fail_search=True,
        supports_freshness=False,
    )
    serpapi.provider_metadata = SerpApiGoogleSearchProvider(api_key="token").provider_metadata
    google = FixtureWebResearchProvider(
        provider_id="google-search",
        display_name="Google Fixture",
        search_results={"query": [{"title": "Allowed", "url": "https://allowed.example/page"}]},
        supports_freshness=True,
    )
    planning_registry = WebSearchProviderRegistry((serpapi, google))

    _events, freshness_plan = planning_registry.plan(prefer_freshness=True)
    assert [provider.provider_metadata.provider_id for provider in freshness_plan] == [
        "google-search",
        "serpapi-google-search",
    ]

    registry = WebSearchProviderRegistry((serpapi, google), default_provider="serpapi-google-search")
    result = search_web(
        "query",
        registry=registry,
        policy=WebResearchPolicy(allowed_domains=("allowed.example",), freshness_days=3),
    )

    assert result["provider"]["id"] == "google-search"
    assert result["provider_selection"]["status"] == "fallback"
    assert result["provider_fallback"]["from"] == "serpapi-google-search"
    assert result["provider_fallback"]["attempts"][0]["status"] == "failed"


@pytest.mark.skipif(
    not (os.environ.get("WEAVERT_LIVE_SERPAPI_GOOGLE_SMOKE") and os.environ.get("SERPAPI_API_KEY")),
    reason="SerpAPI Google live smoke requires opt-in flag and SERPAPI_API_KEY.",
)
def test_live_serpapi_google_smoke() -> None:
    result = search_web(
        "official SerpAPI Google Search API documentation",
        registry=WebSearchProviderRegistry((SerpApiGoogleSearchProvider(),)),
        provider="serpapi-google-search",
        policy=WebResearchPolicy(max_search_results=3),
    )

    assert result["provider"]["id"] == "serpapi-google-search"
    assert result["results"]
    assert all(item["url"].startswith(("http://", "https://")) for item in result["results"])


@pytest.mark.skipif(
    not all(
        __import__("os").environ.get(name)
        for name in (
            "WEAVERT_LIVE_BING_GROUNDING_SMOKE",
            "FOUNDRY_PROJECT_ENDPOINT",
            "FOUNDRY_MODEL_DEPLOYMENT_NAME",
            "BING_PROJECT_CONNECTION_ID",
            "AGENT_TOKEN",
        )
    ),
    reason="Bing grounding live smoke requires opt-in flag and complete Azure AI Foundry configuration.",
)
def test_live_bing_grounding_smoke() -> None:
    provider = BingGroundingSearchProvider()
    result = search_web(
        "official Azure AI Foundry Bing grounding documentation",
        registry=WebSearchProviderRegistry((provider,)),
        provider="bing-grounding",
        policy=WebResearchPolicy(max_search_results=3, freshness_days=30),
    )

    assert result["provider"]["id"] == "bing-grounding"
    assert result["freshness_scope"]["status"] in {"unsupported", "enforced", "satisfied"}
    assert result["results"]
    assert all(item["url"].startswith(("http://", "https://")) for item in result["results"])
