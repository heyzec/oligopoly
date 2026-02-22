from datetime import datetime
import re
from typing import Any
from typing import NamedTuple, Callable, Optional, Sequence, Type
from itertools import zip_longest

import fitz

from utils import DEBUG, RAINBOW, BLACK, GREEN
from utils import draw, to_cents, show


class Word(NamedTuple):
    """Thin wrapper around fitz's word representation."""
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    block_no: Optional[int] = None
    line_no: Optional[int] = None
    word_no: Optional[int] = None

def binned[T](bins: Sequence[float], values: list[T], key: Callable[[T], float]) -> list[list[T]]:
    if sorted(bins) != bins:
        raise ValueError("bins must be sorted")

    stream = iter(sorted(values, key=key))
    groups = []

    value = next(stream, None)
    if value is None:
        return []
    while key(value) < bins[0]:
        value = next(stream, None)
        if value is None:
            return []

    for i in range(len(bins)-1):
        bin, next_bin = bins[i], bins[i+1]
        group = []
        while value is not None:
            inside = key(value) >= bin and key(value) < next_bin
            if not inside:
                break
            group.append(value)
            value = next(stream, None)
        groups.append(group)

    return groups

def grouped[T](bins: Sequence[float], values: list[T], key: Callable[[T], float]) -> list[list[T]]:
    pregroups = binned(list(map(abs, bins)), values, key)
    assert len(pregroups) == len(bins) - 1 or len(pregroups) == 0, f"Number of bins must be one more than number of groups, got {len(bins)} bins and {len(pregroups)} pregroups"
    groups = []
    for i, pregroup in enumerate(pregroups):
        if bins[i] >= 0:
            groups.append(pregroup)
    return groups


class BaseModel(dict): # inherit from dict for json serialization
    def __setattr__(self, key, value):
        self[key] = value

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError:  # we change error type, otherwise `getattr(model, custom, default)` will break
            raise AttributeError(f"{type(self).__qualname__} has no attribute {item}")

    def __repr__(self):
        return f"{type(self).__qualname__}({super().__repr__()})"


class BaseScanner:
    Model: Type

    verticals: list[float] = []
    horizontals: list[float] = []

    def __init__(self, path):
        if not hasattr(self, "Model"):
            raise NotImplementedError("Model not defined for scanner")

        self.doc: fitz.Document = fitz.open(path)

    def get_words(self, page, clip=None):
        """Wrapper around get_text() to ensure order and wrapper"""
        ordered = sorted(page.get_text("words", clip=clip), key=lambda w: (w[1], w[0]))
        words = [Word(*w) for w in ordered]
        return words

    def get_spans(self, page, clip=None):
        spans = []
        for block in page.get_text("dict", clip=clip)["blocks"]:  # type: ignore
            for line in block.get("lines", []):        # type: ignore
                for span in line.get("spans", []):
                    spans.append(span)
        ordered = sorted(spans, key=lambda s: (s['bbox'][1], s['bbox'][0]))
        return ordered

    def is_compatible(self):
        raise NotImplementedError()

    def scan(self):
        doc = self.doc

        err = None
        try:
            all_entries: list[tuple[BaseModel, int, float]] = []
            for page_no in range(doc.page_count):
                anchors = self.get_anchors(page_no)
                if DEBUG:
                    self.draw_horizontals(pages=[doc.load_page(page_no)], ys=[abs(y) for y in anchors])
                entries = self.get_entries(page_no, anchors)
                for entry, y in entries:
                    all_entries.append((entry, page_no, y))

            print(f"Extracted {len(all_entries)} entries across {doc.page_count} pages")

            meta = self.extract_meta()
            output = self.assemble(all_entries, meta)

        # Show output PDF, even if error
        except Exception as e:
            err = e
            pass
        finally:
            if DEBUG:
                show(doc)
            if err:
                raise err

        return output  # type: ignore

    def get_verticals(self, page_no) -> Optional[list[float]]:
        """Detect header boundaries even if some headers are multi-word and wrapped.
        Weakness

        PDF:
            Please pay by statement date, date or date.
                                    ^^^^  ^^^^    ^^^^
            |DATE|AMOUNT|
        Model:
            date, amount

        The first line in PDF gets preferred because it matched on same word "date" 3 times.
        """

        doc = self.doc
        page = doc.load_page(page_no)
        expected_headers = list(self.Model.__annotations__.keys())
        if len(expected_headers) == 0:
            raise Exception("Model has no fields, cannot determine verticals")

        # Multi-word headers have multiple parts, e.g. transaction_date -> transaction, date
        expected_parts = [[part for part in header.split('_')] for header in expected_headers]
        keywords = set(part.lower() for g in expected_parts for part in g)

        # Step 1: Filter to find words that match parts
        words = self.get_words(page)
        matched = [w for w in words if w.text.lower() in keywords]
        if not matched:
            print("No matched words found for vertical detection", page_no)
            return None  # zero matches

        # Step 2: Group by y-coordinate and get the largest group
        top_aligned: dict[float, list[Word]] = {}
        for word in matched:
            top_aligned.setdefault(word.y0, []).append(word)
        if not top_aligned:
            print("No matched words found for vertical detection", page_no)
        baseline_words = max(top_aligned.values(), key=len)
        if len(baseline_words) < 2:
            print("Not enough matched words found for vertical detection", page_no)
            return None  # no verticals found with confidence

        # Step 3: Check if unmatched parts are present up to alignment of x-coordinate
        left_aligned = {}
        for word in matched:
            left_aligned.setdefault(word.x0, []).append(word)
        detected_parts = []
        for w in baseline_words:
            detected_parts.append([ww.text.lower() for ww in left_aligned[w.x0]])
        for dp, ep in zip(detected_parts, expected_parts):
            if not set(ep) <= set(dp):
                print("Detected parts do not match expected parts for vertical detection", page_no)
                print("Expected parts:", expected_parts)
                print("Detected parts:", detected_parts)
                return None  # some parts failed to match

        verticals = [w.x0 for w in baseline_words]
        if DEBUG:
            for i, word in enumerate(baseline_words):
                draw(page, word[:4], color=RAINBOW[i % len(RAINBOW)])
        return verticals

    def get_anchors(self, page_no: int) -> list[float]:
        raise NotImplementedError()

    def get_anchors_generic(self, page_no: int, vertical_i=0, regex="", with_infinity=True):
        page = self.doc.load_page(page_no)
        # if verticals is not None:
        #     self.draw_verticals(pages=[page], xs=verticals)

        output: list[float] = []

        for span in self.get_spans(page):
            text = span['text']
            if re.match(regex, text):
                y = span['bbox'][1]
                if len(output) == 0 or output[-1] != y:  # avoid duplicates (another solution is to use vertical_i)
                    output.append(y)

        if DEBUG:
            self.draw_horizontals(pages=[page], ys=output) # drawing here is inaccurate
        return output

    def get_entries(self, page_no: int, anchors: list[float]) -> list[tuple[BaseModel, float]]:
        raise NotImplementedError()

    def get_entries_generic(self, page_no, anchors, span_size=None, span_flags=None) -> list[tuple[BaseModel, float]]:
        page = self.doc.load_page(page_no)
        verticals = self.get_verticals(page_no)
        if verticals and DEBUG:
            self.draw_verticals(pages=[page], xs=verticals)
        if verticals is None:
            return []
        if anchors == []:
            return []

        words: list[Word] = []
        block: Any
        clip=fitz.Rect(0, anchors[0], page.rect.width, anchors[-1]) # TODO: will fail if anchors 
        for block in page.get_text("dict", clip=clip)["blocks"]: # type: ignore
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                for span in spans:
                    if span_size is not None and span['size'] != span_size:
                        continue
                    if span_flags is not None and span["flags"] != span_flags:
                        continue

                    if DEBUG:
                        draw(page, span['bbox'])
                    words.append(Word(*span['bbox'], span["text"])) # type: ignore

        # Step 1: Group words by horizontal anchors
        bins = [y-0.5 if y > 0 else y + 5 for y in anchors] # bad code
        groups = grouped(bins, words, key=lambda w: w.y0)

        # Step 2: For each group, further group by vertical anchors, then generate entry
        preentries: list[tuple[list[str], float]] = []
        bins = [int(x) for x in verticals] + [float('inf')]
        for group in groups:
            assert group != [], "No words between anchors"
            subgroups = grouped(bins, group, key=lambda w: w.x0)
            preentry = []
            for i, subgroup in enumerate(subgroups):
                for word in subgroup:
                    draw(page, word[:4], color=RAINBOW[i % len(RAINBOW)])
                preentry.append('\n'.join(word.text for word in subgroup).strip())

            preentries.append((preentry, subgroups[0][0].y0))

        entries: list[tuple[BaseModel, float]] = []
        for preentry in preentries:
            entry: BaseModel = self.Model()
            xs, y = preentry

            # TODO: This is a hack for DBS Account V1, where an anchor is falsely detected on the second header in page
            # To fix, we should make extract_meta run before get_anchors, so it can exclude these two regions:
            # headers and extra info like carried forward
            skip_entry = False

            for (attr, cls), s in zip_longest(self.Model.__annotations__.items(), xs):
                if skip_entry:
                    break

                if (parser := getattr(entry, f'parse_{attr}', None)) is not None:
                    value = parser(xs)
                    setattr(entry, attr, value)
                    continue


                if cls is str:
                    setattr(entry, attr, s)
                elif cls is int:
                    if not re.match(r"(\d+,)?\d+\.\d\d", s):
                        raise ValueError(f"Unsure how to parse {s} to int ({attr})")
                    try:
                        value = to_cents(s)
                    except ValueError:
                        pass
                    setattr(entry, attr, value)
                elif cls is Optional[int]:
                    # dedupe this part with above case
                    if s == "":
                        value = None
                    else:
                        if not re.match(r"(\d+,)?\d+\.\d\d", s):
                            raise ValueError(f"Unsure how to parse {s} to int ({attr})")
                        try:
                            value = to_cents(s)
                        except ValueError:
                            # this is also a hack, remove after removing skip_entry
                            value = to_cents(s.split('\n')[0])

                    setattr(entry, attr, value)
                elif cls is datetime:
                    if re.match(r"\d{2}/\d{2}/\d{4}", s):
                        dt = datetime.strptime(s, "%d/%m/%Y")
                    elif re.match(r"\d{2} [A-Za-z]{3}", s):
                        try:
                            dt = datetime.strptime(s, "%d %b")
                        except ValueError:
                            skip_entry = True
                            continue
                    else:
                        raise ValueError(f"Unsure how to parse '{s}' to datetime ({attr})")
                    setattr(entry, attr, dt)

            entries.append((entry, y))

        return entries

    def extract_meta(self) -> Any:
        raise NotImplementedError()

    def assemble(self, entries: list[tuple[BaseModel, int, float]], meta: Any) -> Any:
        acc_meta, acc_balances = meta

        i = j = k = 0
        accounts: list[dict] = []
        account = None
        while i < len(entries) or j < len(acc_meta) or k < len(acc_balances):
            x = entries[i][1:] if i < len(entries) else (float('inf'), float('inf'))
            y = acc_meta[j][1:] if j < len(acc_meta) else (float('inf'), float('inf'))
            z = acc_balances[k][1:] if k < len(acc_balances) else (float('inf'), float('inf'))
            if y > x < z:
                # next smallest from entries
                assert account is not None
                account.setdefault('entries', []).append(entries[i][0])
                i += 1
            elif x > y < z:
                if account is not None:
                    accounts.append(account)
                account = acc_meta[j][0].copy()
                # next smallest from acc_meta
                j += 1
            elif x > z < y:
                assert account is not None
                account |= acc_balances[k][0]
                # next smallest from acc_balances
                k += 1
        if account is not None:
            accounts.append(account)

        return accounts

    def draw_drawings(self, fill=None):
        doc = self.doc
        for page_no in range(doc.page_count):
            page = doc.load_page(page_no)
            for drawing in page.get_drawings():
                d_fill = drawing['fill']
                if fill is None or bool(d_fill) is bool(fill):
                    rect = drawing['rect']
                    draw(page, rect)

    def draw_all_words(self):
        doc = self.doc
        for page_no in range(doc.page_count):
            page = doc.load_page(page_no)
            for word in page.get_text("words"):
                rect = fitz.Rect(word[:4])
                draw(page, rect)

    def draw_verticals(self, pages=None, xs=None):
        doc = self.doc
        if pages is None:
            pages = [doc.load_page(page_no) for page_no in range(doc.page_count)]
        if xs is None:
            assert False, "xs cannot be None"
            # xs = self.get_verticals()
        doc = self.doc
        for page in pages:
            Y1 = page.rect.height
            for x in xs:
                page.draw_line(p1=(x, 0), p2=(x, Y1), color=BLACK, width=2)

    def draw_horizontals(self, pages:Optional[list[Any]]=None, ys=None):
        doc = self.doc
        if pages is None:
            pages = [doc.load_page(page_no) for page_no in range(doc.page_count)]
        if ys is None:
            assert False
            # ys = self.horizontals
        for page in pages:
            X1 = page.rect.height
            for y in ys:
                page.draw_line(p1=(0, y), p2=(X1, y), color=BLACK, width=2)
