# swarm-oversight

Multi-agent oversight for the Apart Swarm Alignment hackathon, track 4. A
per-agent spending limit lets each agent stay inside its own cap while the swarm,
taken together, does something none of them was allowed to do alone. This project
watches the swarm: seeded action logs, a monitor that reads them in order and
raises flags, and a harness that reports recall, false-alarm rate and how late each
flag came. Everything is the standard library, so a score reproduces from the seed
alone.

Start with [swarm-oversight/README.md](swarm-oversight/README.md) for what it is and
how to run it.