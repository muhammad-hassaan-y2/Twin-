|scenario|prefix|words|both|both, no freeze|rules+model|model $/log|seeds where model differs|
|---|---|---|---|---|---|---|---|
|benign|-|-|-|-|-|0.00000|0 (max 0.000)|
|split_payment|0.667 / 0.000|0.667 / 0.000|0.667 / 0.000|0.667 / 0.000|0.667 / 0.000|0.01360|0 (max 0.000)|
|relay|0.442 / 0.000|0.442 / 0.000|0.442 / 0.000|0.442 / 0.000|0.442 / 0.000|0.00476|0 (max 0.000)|
|split_wide|0.666 / 0.000|0.666 / 0.000|0.666 / 0.000|0.666 / 0.000|0.666 / 0.000|0.01360|0 (max 0.000)|
|relay_two_hop|0.433 / 0.000|0.433 / 0.000|0.433 / 0.000|0.433 / 0.000|0.433 / 0.000|0.00456|0 (max 0.000)|
|split_alias|0.665 / 0.000|0.883 / 0.000|0.665 / 0.000|0.665 / 0.000|0.665 / 0.000|0.00762|0 (max 0.000)|
|benign_busy|-|-|-|-|-|0.01013|0 (max 0.000)|
|split_distinct|1.000 / 0.000|1.000 / 0.000|1.000 / 0.000|1.000 / 0.000|1.000 / 0.000|0.00000|0 (max 0.000)|
|split_slow|1.000 / 0.000|1.000 / 0.000|1.000 / 0.000|1.000 / 0.000|1.000 / 0.000|0.02720|0 (max 0.000)|
|alias_far|1.000 / 0.000|1.000 / 0.000|1.000 / 0.000|1.000 / 0.000|1.000 / 0.000|0.00660|0 (max 0.000)|
|relay_fanout|0.687 / 0.521|0.687 / 0.521|0.687 / 0.521|0.687 / 0.191|0.687 / 0.521|0.01462|0 (max 0.000)|
|relay_reversed|0.979 / 0.166|0.979 / 0.166|0.979 / 0.166|0.979 / 0.050|0.979 / 0.166|0.01992|0 (max 0.000)|
|split_renamed|1.000 / 0.000|0.665 / 0.363|0.665 / 0.363|0.665 / 0.000|0.665 / 0.000|0.02720|0 (max 0.000)|
|benign_stem|-|-|-|-|-|0.01299|0 (max 0.000)|

Each cell is attack money that settled / legitimate money held, over the same seeds. The five columns are the same monitor at five settings: the shipped string reading, the words reading, both readings counted together, both readings answering a flag by holding the payment instead of freezing the swarm, and the shipped rule with a model in the loop reading identity by words. Only the last column pays for a call. The last column counts seeds where the model arm's settled attack money differs from the free both-readings-hold arm on the same seed, and the largest absolute difference: a paired comparison, not two pooled means.
