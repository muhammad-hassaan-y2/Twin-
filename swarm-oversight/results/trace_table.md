|cents per branch|payees per attack|ordering|violation rate|same, no clock|recall (windowed)|attack money out|flags on clean logs|same, alias rule off|over-merged|
|---|---|---|---|---|---|---|---|---|---|
|9000|1|tight|0.100|0.100|1.00|0.00|0.000|0.000|0.000|
|9000|1|worst|0.000|0.100|-|-|0.000|0.000|0.000|
|9000|1|random|0.000|0.100|-|-|0.000|0.000|0.000|
|9000|4|tight|0.000|0.000|-|-|0.000|0.000|0.000|
|9000|4|worst|0.000|0.000|-|-|0.000|0.000|0.000|
|9000|4|random|0.000|0.000|-|-|0.000|0.000|0.000|
|30000|1|tight|0.225|0.225|1.00|0.00|0.000|0.000|0.000|
|30000|1|worst|0.000|0.225|-|-|0.070|0.000|0.070|
|30000|1|random|0.120|0.225|1.00|0.00|0.017|0.000|0.017|
|30000|4|tight|0.070|0.070|1.00|0.00|0.027|0.000|0.027|
|30000|4|worst|0.000|0.070|-|-|0.070|0.000|0.070|
|30000|4|random|0.000|0.070|-|-|0.070|0.000|0.070|
|90000|1|tight|1.000|1.000|1.00|0.00|0.000|0.000|0.000|
|90000|1|worst|1.000|1.000|1.00|0.00|0.000|0.000|0.000|
|90000|1|random|1.000|1.000|1.00|0.00|0.000|0.000|0.000|
|90000|4|tight|1.000|1.000|1.00|0.00|0.000|0.000|0.000|
|90000|4|worst|1.000|1.000|1.00|0.00|0.000|0.000|0.000|
|90000|4|random|1.000|1.000|1.00|0.00|0.000|0.000|0.000|
|300000|1|tight|1.000|1.000|1.00|0.00|0.000|0.000|0.000|
|300000|1|worst|1.000|1.000|1.00|0.00|0.000|0.000|0.000|
|300000|1|random|1.000|1.000|1.00|0.00|0.000|0.000|0.000|
|300000|4|tight|1.000|1.000|1.00|0.00|0.000|0.000|0.000|
|300000|4|worst|1.000|1.000|1.00|0.00|0.000|0.000|0.000|
|300000|4|random|1.000|1.000|1.00|0.00|0.000|0.000|0.000|

Measured on the published reconstruction: 189,579 records, 61,125 edges, 26,248 parents, fan-out median 1, p99 12, max 858; 0 nodes that are both a parent and a child, so no relay depth is observable; 0 records carrying a time.
Identity pool: 28,086 distinct payees observed, the busiest taking 14.6% of the marks. At the bound of 600.00 dollars per payee per window, moving 100,000.00 dollars needs 167 of them. The observed pool covers 168.52 such runs, so identity spread alone, with no amount over the bound, is the lever this swarm has.
