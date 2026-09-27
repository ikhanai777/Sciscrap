"""Offline tests: DOI parsing, filename safety, and Sci-Hub page parsing (fixtures mirror real pages)."""

from sciscrap.doi import extract_dois, normalize_doi, safe_filename
from sciscrap.downloader import paper_filename
from sciscrap.search import Paper, _finalize
from sciscrap.sources import classify_scihub_page, extract_pdf_url, looks_like_pdf

SCIHUB_IN_ARTICLE = """
<html><body>
<div id="buttons">
  <button onclick="location.href='https:\\/\\/sci.bban.top\\/pdf\\/10.1038\\/nature12373.pdf?download=true'">&darr;save</button>
</div>
<div id="article">
  <embed type="application/pdf" src="https://sci.bban.top/pdf/10.1038/nature12373.pdf" id="pdf"></embed>
</div>
</body></html>
"""

SCIHUB_CLASSIC_ARTICLE = """
<html><body><div id="article">
<iframe id="pdf" src="//zero.sci-hub.se/1234/abcd/kucsko2013.pdf#navpanes=0&view=FitH"></iframe>
</div></body></html>
"""

SCIHUB_BUTTON_ONLY = """
<html><body><button onclick="location.href='/downloads/2020/xyz.pdf?download=true'">save</button></body></html>
"""

SCIHUB_IN_NOT_FOUND = """
<html><head><title>Sci-Hub - search proxy to download article</title></head>
<body><div id="noproxy">no matching proxies found</div></body></html>
"""

PMC_LANDING = """
<html><head><meta name="citation_pdf_url" content="https://pmc.ncbi.nlm.nih.gov/articles/PMC123/pdf/main.pdf">
</head><body></body></html>
"""


def test_normalize_doi_variants():
    assert normalize_doi("10.1038/nature12373") == "10.1038/nature12373"
    assert normalize_doi("https://doi.org/10.1038/nature12373") == "10.1038/nature12373"
    assert normalize_doi("doi:10.1038/nature12373.") == "10.1038/nature12373"
    assert normalize_doi("(see 10.1126/science.1225829)") == "10.1126/science.1225829"
    assert normalize_doi("10.1016/0006-2952(75)90084-2") == "10.1016/0006-2952(75)90084-2"
    assert normalize_doi("not a doi") is None


def test_extract_dois_dedupes_and_handles_messy_input():
    text = "a,10.1038/NATURE12373\nb,10.1038/nature12373\n@article{x, doi = {10.1126/science.1225829}}"
    assert extract_dois(text) == ["10.1038/NATURE12373", "10.1126/science.1225829"]


def test_safe_filename_windows():
    assert safe_filename('a:b*c?"d<e>|f') == "a_b_c__d_e__f"
    assert safe_filename("CON") == "_CON"
    assert safe_filename("title. ") == "title"
    assert len(safe_filename("x" * 400)) == 150


def test_paper_filename_styles():
    p = Paper(doi="10.1038/nature12373", title="Nanometre-scale <i>thermometry</i>: in a cell?", year=2013,
              authors=["G. Kucsko", "P. Maurer"])
    assert paper_filename(p, p.doi, "doi") == "10.1038_nature12373.pdf"
    assert paper_filename(p, p.doi, "title") == "Kucsko_2013_Nanometre-scale thermometry_ in a cell_.pdf"
    assert paper_filename(None, p.doi, "title") == "10.1038_nature12373.pdf"


def test_extract_pdf_url_scihub_in():
    url = extract_pdf_url(SCIHUB_IN_ARTICLE, "https://www.sci-hub.in/10.1038/nature12373")
    assert url == "https://sci.bban.top/pdf/10.1038/nature12373.pdf"


def test_extract_pdf_url_classic_iframe_scheme_relative_and_fragment():
    url = extract_pdf_url(SCIHUB_CLASSIC_ARTICLE, "https://sci-hub.se/10.1038/nature12373")
    assert url == "https://zero.sci-hub.se/1234/abcd/kucsko2013.pdf"


def test_extract_pdf_url_onclick_relative():
    url = extract_pdf_url(SCIHUB_BUTTON_ONLY, "https://sci-hub.st/10.1/x")
    assert url == "https://sci-hub.st/downloads/2020/xyz.pdf?download=true"


def test_extract_pdf_url_citation_meta():
    assert extract_pdf_url(PMC_LANDING, "https://pmc.ncbi.nlm.nih.gov/articles/PMC123/") == \
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC123/pdf/main.pdf"


def test_not_found_page():
    assert extract_pdf_url(SCIHUB_IN_NOT_FOUND, "https://www.sci-hub.in/10.9/x") is None
    assert classify_scihub_page(SCIHUB_IN_NOT_FOUND) == "not_found"
    assert classify_scihub_page("<html>please solve the captcha</html>") == "captcha"


def test_looks_like_pdf():
    assert looks_like_pdf(b"%PDF-1.5\n...")
    assert looks_like_pdf(b"\n\n%PDF-1.7")
    assert not looks_like_pdf(b"<html>")


def test_finalize_sorts_dedupes_filters():
    papers = [
        Paper(doi="10.1/a", citations=5, year=2010),
        Paper(doi="10.1/B", citations=50, year=2020),
        Paper(doi="10.1/b", citations=40, year=2020),
        Paper(doi="10.1/c", citations=500, year=1999),
    ]
    out = _finalize(papers, limit=10, year_from=2005, year_to=None, min_citations=10)
    assert [p.doi for p in out] == ["10.1/B"]
