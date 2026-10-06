from types import SimpleNamespace

from app.services.collectors.sources import collect_listing, collect_tender_table

TENDER_HTML = """<html><body><table><tr><td><table>
<tr><td>Tender Title</td><td>Reference No</td><td>Closing Date</td><td>Bid Opening Date</td></tr>
<tr><td><a href="/nicgep/app?component=x&session=T&sp=abc">1. Construction of boundary wall and internal roads at RIICO Industrial Area Tapukara</a></td>
<td>NIT 12/RIICO/BHIWADI/2026-27</td><td>20-Oct-2026 06:00 PM</td><td>21-Oct-2026 11:00 AM</td></tr>
<tr><td><a href="/x">2. Construction of New Building AT GUPS BHAGWANPURA BLOCK MANGROL</a></td>
<td>NIT15/JPR</td><td>14-Oct-2026 06:00 PM</td><td>15-Oct-2026 02:00 PM</td></tr>
</table></td></tr></table></body></html>"""

LISTING_HTML = """<html><body><ul>
<li>18-09-2026 Allotment of plots in Industrial Area Neemrana Phase III <a href="/writereaddata/notice1.pdf">View More ?</a></li>
<li><a href="/about">About us</a></li>
</ul></body></html>"""


class StubFetcher:
    def __init__(self, html, url):
        self.resp = SimpleNamespace(text=html, url=url, headers={"content-type": "text/html"})

    def get(self, url, **kw):
        return self.resp


def test_tender_table_filters_by_location_and_uses_stable_urls():
    src = SimpleNamespace(url="https://eproc.rajasthan.gov.in/nicgep/app", config={})
    items = collect_tender_table(src, StubFetcher(TENDER_HTML, src.url))
    assert len(items) == 1  # Mangrol row is outside the target clusters
    it = items[0]
    assert "Tapukara" in it.title and "session=" not in it.url and "lead_row=" in it.url
    again = collect_tender_table(src, StubFetcher(TENDER_HTML, src.url))
    assert again[0].url == it.url  # stable across runs
    assert it.published_at is not None


def test_listing_uses_row_text_for_generic_anchor():
    src = SimpleNamespace(url="https://riico.rajasthan.gov.in/", config={})
    items = collect_listing(src, StubFetcher(LISTING_HTML, src.url))
    assert len(items) == 1
    assert "Neemrana" in items[0].title and items[0].url.endswith("notice1.pdf")
    assert items[0].meta["is_document"]
