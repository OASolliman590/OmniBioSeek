from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from omnibioseek.adapters.omicsdi import OmicsDIAdapter
from omnibioseek.http import HttpResponse
from omnibioseek.models import Modality


def test_queries_cover_transcriptomics_proteomics_and_metformin(query):
    queries = OmicsDIAdapter().build_queries(query)
    assert any('omics_type:"Transcriptomics"' in item for item in queries)
    assert any('omics_type:"Proteomics"' in item for item in queries)
    assert any('"metformin"' in item for item in queries)
    assert all('TAXONOMY:"9606"' in item for item in queries)


def test_omicsdi_pagination_and_mapping(query):
    calls = []

    def transport(url, headers):
        calls.append(url)
        start = int(parse_qs(urlparse(url).query).get("start", ["0"])[0])
        payload = (
            {
                "count": 2,
                "datasets": [
                    {
                        "id": f"PXD00000{start + 1}",
                        "source": "pride",
                        "title": "Human perirenal proteomics",
                        "description": "CKD",
                        "organisms": [{"acc": "9606", "name": "Homo sapiens"}],
                        "keywords": ["proteomics"],
                    }
                ],
            }
            if start < 2
            else {"count": 2, "datasets": []}
        )
        import json

        return HttpResponse(200, json.dumps(payload).encode(), {}, url)

    from omnibioseek.http import HttpClient

    adapter = OmicsDIAdapter(HttpClient(transport=transport), page_size=1)
    minimal = query.model_copy(update={"modalities": [Modality.PROTEOMICS], "priority_terms": []})
    records = list(adapter.search(minimal))
    assert len(records) == 2
    assert records[0].repository == "pride"
    assert records[0].taxonomy_ids == ["9606"]
    assert len(calls) == 2

