# Pipeline schedule

Team: 1 PM, 2 dev lane(s), 2 QA lane(s). Makespan **10** units (dependency lower bound 9). Overall idle rate **42%**.

## Critical path

S0:SPEC -> S0:BUILD -> S1:BUILD -> S2:BUILD -> S3:BUILD -> S3:VERIFY

## Lanes

Idle = all unused time; Gaps = idle between a lane's first and last task (ramp-up and ramp-down excluded).

| Lane | Busy | Idle | Gaps | Work (start-end task) |
|---|---|---|---|---|
| pm1 | 6 | 40% | 0% | 0-1 S0:SPEC; 1-2 S1:SPEC; 2-3 S2:SPEC; 3-4 S4:SPEC; 4-5 S3:SPEC; 5-6 S5:SPEC |
| dev1 | 8 | 20% | 0% | 1-2 S0:BUILD; 2-4 S1:BUILD; 4-6 S2:BUILD; 6-8 S3:BUILD; 8-9 S5:BUILD |
| dev2 | 3 | 70% | 0% | 4-7 S4:BUILD |
| qa1 | 9 | 10% | 0% | 1-2 S0:PREWRITE; 2-3 S0:VERIFY; 3-4 S2:PREWRITE; 4-5 S1:VERIFY; 5-6 S3:PREWRITE; 6-7 S2:VERIFY; 7-8 S4:VERIFY; 8-9 S3:VERIFY; 9-10 S5:VERIFY |
| qa2 | 3 | 70% | 20% | 2-3 S1:PREWRITE; 4-5 S4:PREWRITE; 6-7 S5:PREWRITE |

## Idle windows (fill from the standby backlog)

- pm1: 6-10
- dev1: 0-1, 9-10
- dev2: 0-4, 7-10
- qa1: 0-1
- qa2: 0-2, 3-4, 5-6, 7-10

## Timeline by unit

| Lane | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|---|
| pm1 | S0S | S1S | S2S | S4S | S3S | S5S | . | . | . | . |
| dev1 | . | S0B | S1B | S1B | S2B | S2B | S3B | S3B | S5B | . |
| dev2 | . | . | . | . | S4B | S4B | S4B | . | . | . |
| qa1 | . | S0P | S0V | S2P | S1V | S3P | S2V | S4V | S3V | S5V |
| qa2 | . | . | S1P | . | S4P | . | S5P | . | . | . |

Legend: S=spec, P=prewrite tests, B=build, V=verify, .=idle

## Warnings

- dev2 idles 70% overall (mostly ramp-up/down): consider dropping the lane or giving it standby work
- qa2 idles 70% overall (mostly ramp-up/down): consider dropping the lane or giving it standby work
