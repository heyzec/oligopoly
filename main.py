import argparse
import json
from pprint import pprint
import sys

from utils import DEBUG
from dbs_account import DbsAccount
from dbs_credit import DbsCredit
from ocbc import Ocbc


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=str)
    args = parser.parse_args()

    scanners = [DbsAccount, DbsCredit, Ocbc]
    for scanner in scanners:
        s = scanner(args.file)
        if s.is_compatible():
            print("compatible with scanner ", scanner.__name__)
            break
    else:
        print("No compatible scanner found")
        exit(1)

    data = s.scan()

    # add default=str to handle datetime serialization
    if not DEBUG:
        json.dump(data, sys.stdout, default=str)
    else:
        pprint(data)

