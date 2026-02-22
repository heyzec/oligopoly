import bisect
from datetime import datetime

from base import BaseScanner, BaseModel
from utils import to_cents


class DbsCredit(BaseScanner):
    class Model(BaseModel):
        date: datetime
        description: str
        amount: int
        is_credit: str

        def parse_amount(self, preentry: list[str]):
            parts = preentry[2].split(' ')
            s = parts[0]
            return to_cents(s)

        def parse_is_credit(self, preentry: list[str]):
            parts = preentry[2].split(' ')
            if len(parts) > 1:
                assert parts[1] == 'CR'
                return True
            return False

    def is_compatible(self):
        return (
            [span['text'].strip() for span in self.get_spans(self.doc.load_page(0))[:2]]
            ==
            ["Credit Cards", "Statement of Account"]
        )

    def get_verticals(self, page_no):
        """Hardcoded logic because only first page has headers."""
        verticals = [
            53.999786376953125,   # Date
            94.60054016113281,    # Desc
            460.59112548828125,   # Amount
            # 548.9669799804688,    # CR or not
            # 567.0008544921875,
        ]
        return verticals

    def get_anchors(self, page_no):
        regex = r"\d{2} [A-Z]{3}"
        anchors = self.get_anchors_generic(page_no, vertical_i=0, regex=regex, with_infinity=False)
        page = self.doc.load_page(page_no)
        for span in self.get_spans(page):
            if span['text'] == "SUB-TOTAL:":  # TODO: careful of accidentally detecting in description
                y = span['bbox'][1]
                bisect.insort(anchors, -y, key=abs)
            if span['text'] == "TOTAL:":
                y = span['bbox'][1]
                anchors.append(y)
                break
        return anchors

    def get_entries(self, page_no, anchors):
        return self.get_entries_generic(page_no, anchors, 8.000164031982422, 4)

    def extract_meta(self) -> dict:
        return [({}, 0, 0)], []

