# Demo names for the presentation

Score of the person's **original** record for each query, per method, with the app's
current rules. Verdict cut-offs: ≥ 0.85 likely duplicate, 0.65–0.85 needs review, below
that different person. Hybrid uses the winning weights: 0.50 Double Metaphone,
0.30 trigram, 0.20 Levenshtein. Set the sidebar threshold to 0.50, search once, then
switch methods; the table updates without clicking Search again.

Each query string also exists in the data as a variant of the same person, so every
method lists that exact variant at 1.000. Point at the original record's row instead.

| # | Type this | Original record | Norm. | Trigram | Lev. | DMeta | Soundex | Hybrid |
|---|---|---|---:|---:|---:|---:|---:|---:|
| 1 | `Md. Hasan Islam` | Mohammad Hasan Islam | **1.000** | 0.565 | 0.650 | 0.667 | 0.667 | **1.000** |
| 2 | `Haque, Farzana` | Farzana Haque | 1.000 | 1.000 | **0.143** | 1.000 | 1.000 | 0.831 |
| 3 | `J. Cruze` | Jerome Cruze | 0.500 | 0.500 | 0.583 | 0.500 | 0.500 | 0.517 |
| 4 | `Asshok Dey` | Ashok Dey | **1.000** | 0.750 | 0.900 | **0.500** | 1.000 | 1.000 |
| 5 | `Musammat Shathi Islam` | Mst. Shathi Islam | **1.000** | 0.560 | 0.714 | 0.667 | 0.667 | 1.000 |
| 6 | `Prosenjit Kumar Son` | Prosenjit Kumar Sen (a different person) | 0.773 | 0.773 | 0.947 | **1.000** | **1.000** | **0.921** |

What each name shows:

1. **Md./Mohammad prefix.** Only normalization and Hybrid reach "Likely duplicate". Trigram
   (0.565) calls it "Different person", and the other three methods stop at "Needs review".
2. **Word-order swap.** Levenshtein fails completely (0.143), because the letters move.
   Hybrid falls to 0.831 ("Needs review") because its 0.20 Levenshtein weight drags it down.
   *Changed:* this used to be 1.00 for Hybrid.
3. **Initials.** Every method lands at about 0.50, so every verdict is "Different person". The
   top-10 list is mostly other people: Double Metaphone and Soundex show 1 correct record and
   9 wrong ones (`Joyaa Ghosh` …), and every method lists `T. Cruze`. This is the hardest case.
4. **Doubled consonant.** *Changed:* normalization now scores 1.000 (it was 0.73), because the
   new collapse rule turns `Asshok` into `asok`. Hybrid also reaches 1.000. Double Metaphone,
   on raw names, still fails (0.500), because `ssh` and `sh` get different codes.
5. **Female prefix Musammat/Mst.** Normalization and Hybrid score 1.000. Trigram says
   "Different person" (0.560).
6. **Hard negative** (a different person, one letter apart). Double Metaphone and Soundex give
   a confident wrong 1.000. *Changed:* Hybrid is now fooled too (0.921, "Likely duplicate"),
   because its biggest weight is Double Metaphone. Only normalization and trigram (0.773)
   correctly stop at "Needs review".
