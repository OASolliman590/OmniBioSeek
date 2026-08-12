from __future__ import annotations

from omnibioseek.adapters.pubmed import PubMedAdapter, extract_accessions
from omnibioseek.http import HttpResponse
from omnibioseek.models import Modality


def test_extract_accessions_supports_major_omics_repositories():
    text = "Data: GSE166355, PXD012345, E-MTAB-1234, PRJNA765432 and MTBLS999. GSE166355 repeated."
    assert extract_accessions(text) == [
        "GSE166355",
        "PXD012345",
        "E-MTAB-1234",
        "PRJNA765432",
        "MTBLS999",
    ]


def test_pubmed_mines_accession_from_pmc_full_text(query):
    search_json = b'{"esearchresult":{"idlist":["12345"]}}'
    pubmed_xml = b'''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>12345</PMID><Article><ArticleTitle>PVAT transcriptomics in metabolic syndrome</ArticleTitle><Abstract><AbstractText>RNA sequencing of perivascular adipose tissue.</AbstractText></Abstract></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1000/test</ArticleId><ArticleId IdType="pmc">PMC999</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'''
    pmc_xml = b'''<article><body><p>Processed RNA-seq data are deposited under accession GSE166355. Angiotensin II and ACE2 were evaluated.</p></body></article>'''

    def transport(url, headers):
        if "esearch.fcgi" in url:
            body = search_json
        elif "db=pmc" in url:
            body = pmc_xml
        else:
            body = pubmed_xml
        return HttpResponse(status=200, body=body, headers={}, url=url)

    from omnibioseek.http import HttpClient

    adapter = PubMedAdapter(HttpClient(transport=transport))
    records = list(adapter.search(query))
    assert len(records) == 1
    record = records[0]
    assert record.accession == "GSE166355"
    assert record.pmids == ["12345"]
    assert "10.1000/test" in record.dois
    assert Modality.TRANSCRIPTOMICS in record.modalities
    assert record.provenance["cross_accessions"] == ["GSE166355"]
    assert "angiotensin ii" in record.provenance["literature_text"].casefold()
