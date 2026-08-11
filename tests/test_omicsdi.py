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


def test_omicsdi_fetch_study_uses_live_path_contract(query):
    calls = []

    def transport(url, headers):
        calls.append(url)
        import json

        if "/search?" in url:
            return HttpResponse(
                200,
                json.dumps(
                    {
                        "count": 1,
                        "datasets": [
                            {
                                "id": "E-GEOD-18662",
                                "source": "biostudies-arrayexpress",
                                "title": "Perirenal adipose tissue",
                                "description": "kidney donor",
                            }
                        ],
                    }
                ).encode(),
                {},
                url,
            )
        return HttpResponse(
            200,
            json.dumps(
                {
                    "accession": "E-GEOD-18662",
                    "database": "biostudies-arrayexpress",
                    "name": "Perirenal adipose tissue",
                    "description": "kidney donor",
                    "cross_references": {"pubmed": ["20846162"]},
                }
            ).encode(),
            {},
            url,
        )

    from omnibioseek.http import HttpClient

    adapter = OmicsDIAdapter(HttpClient(transport=transport))
    minimal = query.model_copy(update={"modalities": [Modality.TRANSCRIPTOMICS], "priority_terms": []})
    record = next(iter(adapter.search(minimal)))
    detail = adapter.fetch_study(record.accession)
    assert detail is not None
    assert detail.pmids == ["20846162"]
    assert calls[-1].endswith("/dataset/biostudies-arrayexpress/E-GEOD-18662")
