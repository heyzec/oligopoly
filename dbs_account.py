from datetime import datetime
from typing import Any, Optional

from base import BaseScanner, BaseModel
from utils import to_cents, show, GREEN, draw


class DbsAccount(BaseScanner):
    class Model(BaseModel):
        date: datetime
        description: str
        withdrawal: Optional[int]
        deposit: Optional[int]
        balance: Optional[int]  # For V1, balance is only printed for last entry of each date

    # no horizontal guides, each page can have varying header size

    def is_compatible(self):
        V1 = (377.25, 70.86900329589844, 549.91796875, 84.27300262451172)          # 2021 Jan and before
        V2 = (401.01593017578125, 69.515625, 561.2584228515625, 83.51548767089844) # 2021 Feb and after
        for clip in [V1, V2]:
            spans = self.get_spans(self.doc.load_page(0), clip=clip)
            if len(spans) == 1 and spans[0]['text'].lower() == "consolidated statement":
                return True
        return False
        for i in range(6):
            span = self.get_spans(self.doc.load_page(0))[i]
            text = span['text'].strip().lower()
            if text == 'consolidated statement':
                print(span)
        print(self.get_spans(self.doc.load_page(0))[1]['text'])
        return self.get_spans(self.doc.load_page(0))[1]['text'] == "Consolidated Statement"

    def get_anchors(self, page_no):
        regex = r"\d\d/\d\d/\d\d\d\d" # V2
        regex = r"^\d\d [A-Z][a-z]{2}$" # V1
        return self.get_anchors_generic(page_no, vertical_i=0, regex=regex)

    def get_verticals(self, page_no):
        verticals = super().get_verticals(page_no)
        return [x - 16 for x in verticals] if verticals else None  # this is not needed if we detect right-aligned text

    def get_entries(self, page_no, anchors):
        return self.get_entries_generic(page_no, anchors, span_size=9.0, span_flags=0) # consider no filter
        # return self.get_entries_generic(page_no, anchors, span_size=9.000057220458984, span_flags=4)

    def extract_meta(self) -> Any:
        # Part 1: Account metadata
        acc_meta: list[tuple[dict, int, float]] = []
        for page_no in range(self.doc.page_count):
            if page_no == 0:  # skip first page which is account summary
                continue
            page = self.doc.load_page(page_no)

            account_name = None
            for block in page.get_text("dict")["blocks"]: # type: ignore
                for line in block.get("lines", []): # type: ignore
                    span = line.get("spans", [])[0]

                    # Match only Heading 3
                    if not (span['color'] == 16777215 and span['size'] == 9.000057220458984 # V1
                            or span['size'] == 10.0 and span['flags'] == 16):               # V2
                        continue

                    if account_name is None:
                        account_name = span['text']
                    else:
                        account_no = span['text'][12:]  # trim constant of "Account No. "
                        y = span['bbox'][1]
                        meta = dict(account_name=account_name, account_no=account_no)
                        if len(acc_meta) == 0 or meta != acc_meta[-1][0]:
                            acc_meta.append((meta, page_no, y))
                        account_name = None

        # Part 2: Balance metadata per account
        acc_balances: list[tuple[dict, int, float]] = []
        spans = iter(
            (span, page_no)
            for page_no in range(self.doc.page_count)
            for span in self.get_spans(self.doc.load_page(page_no))              # type: ignore
            if page_no != 0
            if (span['color'] == 0 and span['font'] == "Arial-BoldMT" and span['size'] == 9.000057220458984) # V1
            or span['size'] == 9.0 and span['flags'] == 16 # V2
        )

        balance = {}
        span, page_no = next(spans)
        while span:
            if span['text'] == "Balance Brought Forward" and balance.get('brought_forward') is None:
                span, page_no = next(spans)
                try:
                    balance['brought_forward'] = to_cents(span['text'].strip())
                except ValueError:
                    assert 'SGD' in span['text']
                    pass  # don't handle DBS Multiplier Account for now
            elif span['text'] == "Total Balance Carried Forward:":
                span, page_no = next(spans)
                balance['total_withdrawal'] = to_cents(span['text'].strip())
                span, page_no = next(spans)
                balance['total_deposit'] = to_cents(span['text'].strip())
                span, page_no = next(spans)
                balance['carried_forward'] = to_cents(span['text'].strip())
                acc_balances.append((balance, page_no, span['bbox'][1]))
                balance = {}
            span, page_no = next(spans, (None, None))

        return acc_meta, acc_balances
