"""What are the 50 state Democratic and Republican party organizations emphasizing?

Evidence from state party platforms (stated priorities) and state legislative bills
(revealed priorities).

Two project-wide invariants are enforced in code rather than left to convention:

* **No fabricated data.** Every remote artifact is retrieved through
  :mod:`state_politics.provenance`, which records the URL, HTTP status, SHA-256 body
  hash, byte count, content type and UTC retrieval time. Missing observations are
  omitted, never imputed.
* **No hosted LLM APIs.** Any model runs locally on this machine's Apple Silicon GPU.
  See :mod:`state_politics.compute`.
"""

__version__ = "0.1.0"
