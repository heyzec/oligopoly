from datetime import datetime
from typing import Any, Optional
from pprint import pprint

import fitz

from base import BaseScanner, BaseModel
from utils import DEBUG, draw, to_cents


class Ocbc(BaseScanner):
    class Model(BaseModel):
        transaction_date: datetime
        value_date: datetime
        description: str
        cheque: str
        withdrawal: Optional[int]
        deposit: Optional[int]
        balance: int

    def is_compatible(self):
        # Note that header may have varying number of spans, "OCBC" or "FRANK BY OCBC"
        CLIP = (406.55999755859375, 125.57442474365234, 568.5508422851562, 139.4419708251953) # "STATEMENT OF ACCOUNT" in this area
        spans = self.get_spans(self.doc.load_page(0), clip=CLIP)
        return len(spans) == 1 and spans[0]['text'] == "STATEMENT OF ACCOUNT"


    def get_verticals(self, page_no):
        verticals = super().get_verticals(page_no)
        return [x - 16 for x in verticals] if verticals else None

    def get_anchors(self, page_no):
        regex = r"^\d{2} [A-Z]{3}$"
        anchors = self.get_anchors_generic(page_no, vertical_i=0, regex=regex, with_infinity=False)
        page = self.doc.load_page(page_no)

        # The balance carried forward entry looks just like normal entries, we need to manually exclude it
        for span in self.get_spans(page):
            if span['text'] == 'BALANCE C/F':
                anchors.append(span['bbox'][1])
                break
        else:
            anchors.append(float('inf'))

        return anchors

    def get_entries(self, page_no, anchors):
        return self.get_entries_generic(page_no, anchors, span_size=6.684999942779541, span_flags=0)

    def extract_meta(self) -> Any:
        BOUNDS = fitz.Rect(46.20000076293945, 238.28724670410156, 144.25938415527344, 263.919677734375)

        acc_meta: list[tuple[dict, int, float]] = []
        for page_no in range(self.doc.page_count):
            page = self.doc.load_page(page_no)
            if DEBUG:
                draw(page, BOUNDS)
            spans = self.get_spans(page, clip=BOUNDS)
            if not spans or len(spans) != 2:
                continue
            if spans[0]['size'] != 9.550000190734863:
                continue
            meta = {
                'account_name': spans[0]['text'],
                'account_no': spans[1]['text'][12:],  # trim constant of "Account No. "
            }
            if not acc_meta or acc_meta and meta != acc_meta[-1][0]:
                acc_meta.append((meta, page_no, spans[0]['bbox'][1]))

        spans = iter(
            (span, page_no)
            for page_no in range(self.doc.page_count)
            for span in self.get_spans(self.doc.load_page(page_no))
        )
        acc_balances = []
        balance = {}
        span, page_no = next(spans)
        while span:
            if span['text'] == "BALANCE B/F":
                span, page_no = next(spans)
                # Even though they are visually on the same line, the amount is slighly above the keyword
                balance['brought_forward'] = to_cents(span['text'])
            elif span['text'] == "BALANCE C/F":
                span, page_no = next(spans)
                balance['carried_forward'] = to_cents(span['text'])
            elif span['text'] == "Total Withdrawals/Deposits":
                span, page_no = next(spans)
                balance['total_withdrawals'] = to_cents(span['text'])
                span, page_no = next(spans)
                balance['total_deposits'] = to_cents(span['text'])
            elif span['text'] == "Total Interest Paid This Year":
                span, page_no = next(spans)
                balance['total_interest_paid_this_year'] = to_cents(span['text'])
            elif span['text'] == "Average Balance":
                span, page_no = next(spans)
                balance['average_balance'] = to_cents(span['text'])
                acc_balances.append((balance, page_no, span['bbox'][1]))

            span, page_no = next(spans, (None, None))

        return acc_meta, acc_balances
