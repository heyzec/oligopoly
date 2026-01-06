import argparse
import json
import sys
import os

import fitz


def draw(page, rect):
    page.draw_rect(
        rect,
        color=(1, 0, 0),      # red stroke (RGB, 0–1)
        width=2               # line width
    )

def show(doc):
    tmpfile = "/tmp/output.pdf"
    doc.save(tmpfile)
    os.system(f"xdg-open {tmpfile}")

def union(rects):
    output = rects[0]
    for rect in rects[1:]:
        output |= rect
    return output

def find_words(words, target):
    matches = []
    match = []
    for word in words:
        text = word[4]
        if text == target[len(match)]:
            match.append(word)
            if len(match) == len(target):
                matches.append(match)
                match = []
        else:
            match = []
    return matches

def to_cents(s: str):
    try:
        return int(s.replace(',', '').replace('.', ''))
    except:
        return None

def extract(path) -> dict:
    doc = fitz.open(path)

    accounts = []
    for page_no, page in enumerate(doc):
        if page_no == 0: # Skip contents page
            continue

        # 1. Get bounding boxes for each account on page
        account_rects = []
        for drawing in page.get_drawings():
            rect = drawing['rect']
            fill = drawing['fill']
            if fill is None:
                continue
            r, g, b = fill
            if not all(0.65 < c < 0.68 for c in (r, g, b)):
                continue
            account_rects.append(rect)
        account_rows = []
        for i in range(0, len(account_rects), 2):
            account_rows.append(account_rects[i:i+2])

        if not account_rows:
            # Skip page as it has no accounts
            continue

        # draw(page, fitz.Rect(0, 0, 100, 100))

        # 2. Get first/last row
        opening_targets = [["Balance", "Brought", "Forward"]]
        closing_targets = [["Balance", "Carried", "Forward"], ["Total", "Balance", "Carried", "Forward:"]]
        opening_rects, closing_rects = [], []
        for is_opening in (True, False):
            for target in (opening_targets if is_opening else closing_targets):
                matches = find_words(page.get_text("words"), target)
                if matches is None:
                    continue
                for match in matches:
                    union_rect = union(list(fitz.Rect(word[:4]) for word in match))
                    if is_opening:
                        opening_rects.append(union_rect)
                    else:
                        closing_rects.append(union_rect)
        assert len(opening_rects) == len(closing_rects)
        X0, _, X1, _ = union(account_rows[0])
        opening_rows, closing_rows = [], []
        for open_rect, close_rect in zip(opening_rects, closing_rects):
            opening_rows.append(fitz.Rect(X0, open_rect[1], X1, open_rect[3]))
            closing_rows.append(fitz.Rect(X0, close_rect[1], X1, close_rect[3]))
        opening_rows.sort(key=lambda r: r[1])
        closing_rows.sort(key=lambda r: r[1])

        # for open_rect, close_rect in zip(opening_rows, closing_rows):
        #     draw(page, open_rect)
        #     draw(page, close_rect)
        # show(doc)


        # 3. Find grey rows
        grey_rects = []
        for drawing in page.get_drawings():
            fill = drawing['fill']
            if fill is None:
                continue
            r, g, b = fill
            if not all(0.94 < c < 0.95 for c in (r, g, b)):
                continue
            rect = drawing['rect']
            grey_rects.append(rect)
        grey_rows = []
        for i in range(0, len(grey_rects), 5):
            grey_rows.append(grey_rects[i:i+5])
        # for r in grey_rows:
        #     draw(page, r)

        # 4. Create bounding boxes for all accounts and rows
        all_account_bounds = []
        transaction_rows = []
        i = j = k = l = 0
        start_y = None
        acc_bounds: dict = None # type: ignore
        x = 0
        X = 8

        while True:
            account_row_y = account_rows[i][0][1] if i < len(account_rows) else float('inf')
            opening_row_y = opening_rows[j][1] if j < len(opening_rows) else float('inf')
            closing_row_y = closing_rows[k][1] if k < len(closing_rows) else float('inf')
            grey_row_y = grey_rows[l][0][1] if l < len(grey_rows) else float('inf')
            min_y = min(account_row_y, opening_row_y, closing_row_y, grey_row_y)

            if min_y == float('inf'):
                break
            elif min_y == account_row_y:
                acc_bounds = { 'title': account_rows[i] }
                all_account_bounds.append(acc_bounds)
                # if x == X:
                #     draw(page, account_rows[i])
                i += 1
            elif min_y == opening_row_y:
                start_y = opening_rows[j][3]
                acc_bounds['opening'] = opening_rows[j]
                acc_bounds['transactions'] = []
                # if x == X:
                #     draw(page, opening_rows[j])
                j += 1
            elif min_y == closing_row_y:
                if closing_rows[k][1] - start_y > 20: # After the last grey row it could be another transaction or closing row
                    # acc_bounds['transactions'].append(fitz.Rect(X0, start_y, X1, closing_rows[k][1]))
                    if acc_bounds['transactions']:
                        acc_bounds['transactions'].append(list(fitz.Rect(r[0], start_y, r[2], closing_rows[k][1]) for r in acc_bounds['transactions'][-1])) # copy existihg row structure
                acc_bounds['closing'] = closing_rows[k]
                entire_rect = union([
                    *acc_bounds['title'],
                    acc_bounds['opening'],
                    acc_bounds['closing'],
                ])
                if acc_bounds['transactions']:
                    entire_rect |= union([r for trs in acc_bounds['transactions'] for r in trs])
                acc_bounds['all'] = entire_rect
                # if x == X:
                #     draw(page, closing_rows[k])
                k += 1
            elif min_y == grey_row_y:
                acc_bounds['transactions'].append(list(fitz.Rect(r[0], start_y, r[2], grey_row_y) for r in grey_rows[l]))
                acc_bounds['transactions'].append(list(r for r in grey_rows[l]))
                start_y = grey_rows[l][0][3]
                # if x == X:
                #     draw(page, grey_rows[l])
                l += 1
            else:
                assert False
            x += 1

        for acc in all_account_bounds:
            for row in acc['transactions']:
                for cell in row:
                    draw(page, cell)
        # show(doc)
        doc.save("/tmp/output.pdf")

        # 5.
        acc_idx = 0
        state = 0
        # Stateful variables
        acc: dict = None # type: ignore
        words = iter(page.get_text("words"))
        word = next(words)
        import time
        while True:
            word_rect = fitz.Rect(word[:4])
            # draw(page, word_rect)
            # doc.save("output.pdf")
            # time.sleep(0.2)

            # draw(page, acc_bounds['all'])
            # draw(page, word_rect)
            # doc.save("output.pdf")


            # if not acc_bounds['all'].contains(word_rect):
            #     acc_idx += 1
            #     if acc_idx >= len(all_account_bounds):
            #         break

            if state == 0:
                acc_bounds = all_account_bounds[acc_idx]
                while not acc_bounds['all'].contains(word_rect):
                    word = next(words)
                    word_rect = fitz.Rect(word[:4])
                acc = {}
                if acc_bounds['title'][0].contains(word_rect):
                    account_desc = word[4]
                    state = 1
                    word = next(words)
            if state == 1:
                if acc_bounds['title'][0].contains(word_rect):
                    account_desc += " " + word[4] # type: ignore
                else:
                    if len(accounts) > 0 and accounts[-1]['account_desc'] == account_desc:
                        # Skip creation as it is just pagination
                        acc = accounts[-1]
                    else:
                        accounts.append(acc)
                        acc['account_desc'] = account_desc # type: ignore
                    state = 2
                word = next(words)
            if state == 2:
                if acc_bounds['opening'].contains(word_rect):
                    opening_balance = to_cents(word[4])
                    if opening_balance is not None:
                        acc['opening_balance'] = opening_balance
                        state = 3
                        transaction_state = 0
                        contents = []
                        if 'transactions' not in acc:
                            acc['transactions'] = []
                        word = next(words)
                        continue
                word = next(words)
            if state == 3:
                if len(acc_bounds['transactions']) != 0:
                    cell = acc_bounds['transactions'][0][0]
                    while not cell.contains(word_rect):
                        word = next(words)
                        word_rect = fitz.Rect(word[:4])


                while transaction_state < len(acc_bounds['transactions']) * 5:
                    r, c = divmod(transaction_state, 5)


                # for r in range(len(acc_bounds['transactions'])):
                # if r >= len(acc_bounds['transactions']):
                    cell = acc_bounds['transactions'][r][c]
                    # draw(page, cell)
                    # draw(page, word_rect)
                    # doc.save("output.pdf")
                    # time.sleep(1)
                    if cell.contains(word_rect):
                        contents.append(word[4])
                        word = next(words)
                        word_rect = fitz.Rect(word[:4])
                    else:
                        text = " ".join(contents)
                        if c == 0:
                            acc['transactions'].append({ 'date': text })
                        elif c == 1:
                            acc['transactions'][-1]['description'] = text
                        elif c == 2:
                            acc['transactions'][-1]['withdrawal'] = to_cents(text)
                        elif c == 3:
                            acc['transactions'][-1]['deposit'] = to_cents(text)
                        elif c == 4:
                            acc['transactions'][-1]['balance'] = to_cents(text)

                        contents = []
                        transaction_state += 1
                state = 4
                continue # ideally shouldn't, this will skip a word
            if state == 4:
                if not acc_bounds['closing'].contains(word_rect):
                    word = next(words)
                    continue
                if to_cents(word[4]) is None:
                    word = next(words)
                    continue

                numbers = []
                while True:
                    n = to_cents(word[4])
                    if n:
                        numbers.append(n)
                        word = next(words)
                    else:
                        break
                if len(numbers) != 3:
                    # Ignore balance carried forward due to pagination
                    break

                acc['total_withdrawal'] = numbers[0]
                acc['total_deposit'] = numbers[1]
                acc['closing_balance'] = numbers[2]
                state = 0
                acc_idx += 1
                if acc_idx >= len(all_account_bounds):
                    break
                # draw(page, word_rect)
                # doc.save("output.pdf")
                continue
    return accounts

# def main():


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=str)
    args = parser.parse_args()
    
    extracted = extract(args.file)
    json.dump(extracted, sys.stdout)
