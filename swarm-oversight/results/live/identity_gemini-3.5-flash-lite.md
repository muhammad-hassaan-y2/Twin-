# Live payee-identity judgement: gemini-3.5-flash-lite

Pairwise over the names in each log: a pair is a merge if the arm puts both names in one group. Precision 1.0 with no merges predicted is written 1.00* (nothing to be wrong about). Ground truth is the scenario's construction.

| scenario | n | prefix P/R | tokens P/R | both P/R | model P/R | model false merges |
| --- | --- | --- | --- | --- | --- | --- |
| split_payment | 3 | 1.00* / 1.00 | 1.00* / 1.00 | 1.00* / 1.00 | 1.00* / 1.00 | 0 |
| split_alias | 3 | 1.00 / 1.00 | 1.00 / 0.56 | 1.00 / 1.00 | 1.00 / 1.00 | 0 |
| split_renamed | 3 | 1.00* / 0.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 0 |
| alias_far | 3 | 1.00* / 0.00 | 1.00 / 0.33 | 1.00 / 0.33 | 1.00 / 0.78 | 0 |
| benign_stem | 3 | 0.00 / 1.00 | 1.00* / 1.00 | 0.00 / 1.00 | 1.00* / 1.00 | 0 |
| split_distinct | 3 | 1.00* / 1.00 | 1.00* / 1.00 | 1.00* / 1.00 | 1.00* / 1.00 | 0 |
| benign | 3 | 1.00* / 1.00 | 1.00* / 1.00 | 1.00* / 1.00 | 1.00* / 1.00 | 0 |
