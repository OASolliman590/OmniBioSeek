from __future__ import annotations

import pytest

from omnibioseek.adapters.arc import ArcAdapter
from omnibioseek.adapters.base import AdapterUnavailable
from omnibioseek.adapters.ncbi import NcbiAdapter


def test_ncbi_query_contains_tissue_disease_and_taxonomy(query):
    term = NcbiAdapter.build_term(query)
    assert '"perivascular adipose tissue"[All Fields]' in term
    assert '"prediabetes"[All Fields]' in term
    assert '"9606"[Taxonomy ID]' in term
    assert "GSE[ETYP]" in term


def test_geo_soft_sample_parser(query):
    text = """^SAMPLE = GSM1
!Sample_title = PRAT CKD case
!Sample_source_name_ch1 = perirenal adipose tissue
!Sample_organism_ch1 = Homo sapiens
!Sample_characteristics_ch1 = diagnosis: chronic kidney disease
!Sample_characteristics_ch1 = subject: donor-1
!Sample_treatment_protocol_ch1 = untreated baseline
"""

    class Client:
        def get_text(self, *args, **kwargs):
            return text

    samples = list(NcbiAdapter(client=Client()).fetch_samples("GSE1"))
    assert samples[0].accession == "GSM1"
    assert samples[0].tissue_raw == "perirenal adipose tissue"
    assert samples[0].disease_raw == "chronic kidney disease"
    assert samples[0].donor_id == "donor-1"


def test_arc_filters_human_metadata(query):
    rows = [
        {
            "srx_accession": "SRX1",
            "organism": "Homo sapiens",
            "tissue": "perivascular adipose tissue",
            "disease": "prediabetes",
            "file_path": "gs://bucket/SRX1.h5ad",
        },
        {
            "srx_accession": "SRX2",
            "organism": "Homo sapiens",
            "tissue": "lung",
            "disease": "prediabetes",
            "file_path": "gs://bucket/SRX2.h5ad",
        },
    ]
    adapter = ArcAdapter(metadata_loader=lambda: rows)
    records = list(adapter.search(query))
    assert [record.accession for record in records] == ["SRX1"]
    assert list(adapter.fetch_samples("SRX1"))[0].file_paths == ["gs://bucket/SRX1.h5ad"]


def test_arc_without_project_warns_instead_of_faking_access(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    with pytest.raises(AdapterUnavailable, match="requester-pays"):
        list(ArcAdapter().search(__import__("omnibioseek").QuerySpec()))

