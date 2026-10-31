"""Suggest a schema map from the schema-only profile produced by fetch_and_profile.py.

    python scripts/map_schema.py acabc_profile.json > config/schema_map.toml

It only proposes: review every line. Rights stay `confirmed = false` until a person confirms the licence.
"""
import json
import re
import sys

HINTS = {
    "state": r"state|st_name|ut\b|stname",
    "district": r"district|dist\b|dt_name",
    "assistance_amount": r"amount|assist|subsid|grant|sanction.*(amt|amount)|financ|loan.*amt|support",
    "enterprise_type": r"enterprise|activity|project.*type|business|venture.*type|category",
    "event_date": r"date|year|period|fy\b|month",
    "beneficiary_key": r"beneficiar|applicant|candidate|trainee|\bid\b|_id$|reg.*no",
    "project_key": r"project|proposal|case|sanction.*no",
}


def main(path: str) -> None:
    prof = json.load(open(path, encoding="utf-8"))
    chosen: dict[str, str] = {}
    for logical, pat in HINTS.items():
        for f in prof["fields"]:
            if f["name"] in chosen.values():
                continue
            if re.search(pat, f["name"], re.I):
                if logical == "assistance_amount" and not re.match(r"(int|float)", f["dtype"]):
                    continue
                chosen[logical] = f["name"]
                break
    print("# Draft from", path, f"({prof['rows']} rows, {prof['columns']} columns). REVIEW EVERY LINE.")
    print('[rights]\nconfirmed = false\nlicensed_use = ""\nauthority = ""\n')
    print('[dataset]\nversion = "acabc-record-level-REPLACE"\n')
    print('[units]\nassistance_amount = "rupee"   # CHECK: rupee | lakh | crore\n')
    print("[fields]")
    for logical in HINTS:
        if logical in chosen:
            print(f'{logical} = "{chosen[logical]}"')
        else:
            print(f"# {logical} = \"\"   # no obvious column; leave unmapped if the file lacks it")
    print("\n# Unmapped columns:", [f["name"] for f in prof["fields"] if f["name"] not in chosen.values()])


if __name__ == "__main__":
    main(sys.argv[1])
