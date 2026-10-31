# Getting the record-level dataset

What is known from the AIKosh metadata (assessed 1 Dec 2025, last modified 15 Dec 2025):
source Department of Agriculture & Farmers Welfare, refresh monthly, all States/UTs, **visibility Restricted**, quality 4.25/5.
Missing: tags, year range, licence, primary key, time granularity, collection method, column list, row count.

## Status

`aikosh.download(...)` with identifier `a6dd19e7-89b7-4348-85fb-ccbf07af94fc` failed with HTTP 400
**"User have no permission to download this file."** The API key authenticates; the account lacks download rights for a Restricted dataset.

## Next steps

1. On the dataset page while logged in, look for **Request Access / Request Download** and submit it with the purpose
   (decision-support research for government analysts, aggregates only).
2. Check that the AIKosh profile is complete and verified.
3. If there is no request button, contact AIKosh support with the identifier and the error text above.
4. Once approved: `python scripts/fetch_and_profile.py`, then follow the README section "When the real file arrives".

Never commit the API key or the downloaded file (both are covered by `.gitignore`). If a key was ever pasted into chat or a file, revoke and regenerate it.
