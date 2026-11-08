| tamper | runs | agent-log detection | gateway detection | gateway attack $ out |
|---|---|---|---|---|
| none | 200 | 0.50 | 0.50 | 0.832 |
| rename | 200 | 0.01 | 0.50 | 0.832 |
| drop | 200 | 0.00 | 0.50 | 0.832 |
| underreport | 200 | 0.00 | 0.50 | 0.832 |

Agent-log detection is the monitor reading the log the swarm publishes after the edit; gateway detection is the same monitor inline at the gateway, reading the instructions that actually arrived. Only attack actions are edited. The gateway columns never change because the published log is not an input to them.
