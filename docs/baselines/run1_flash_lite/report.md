# QShala tagger evaluation — gemini-3.5-flash-lite

Run: 2026-10-22 13:04  |  N: 145  |  throttle: 0.5s/req

The **VERIFIED** row (20 Bangalore prelims reviewed by a quizmaster) is the real signal. The **SILVER** row (125 vault questions with my own first-pass labels) is directional only.

## Accuracy
| Slice | N | L1 strict | L2 strict | L2 lenient | Entity | Geo | Shelf | Sens | KW format | Answer in KW |
|---|---|---|---|---|---|---|---|---|---|---|
| ALL (145) | 145 | 82.1 | 70.3 | 84.8 | 89.0 | 89.0 | 77.9 | 97.9 | 100.0 | 92.4 |
| VERIFIED (20 BLR) | 20 | 100.0 | 85.0 | 90.0 | 100.0 | 85.0 | 70.0 | 90.0 | 100.0 | 90.0 |
| SILVER (125) | 125 | 79.2 | 68.0 | 84.0 | 87.2 | 89.6 | 79.2 | 99.2 | 100.0 | 92.8 |
| TEXT-TAGGABLE (Non-Image) | 118 | 80.5 | 68.6 | 84.7 | 89.0 | 89.0 | 80.5 | 97.5 | 100.0 | 94.1 |
| IMAGE-DEPENDENT | 27 | 88.9 | 77.8 | 85.2 | 88.9 | 88.9 | 66.7 | 100.0 | 100.0 | 85.2 |
| UNAMBIGUOUS NON-IMAGE (95% Target) | 15 | 100.0 | 93.3 | 93.3 | 93.3 | 73.3 | 86.7 | 93.3 | 100.0 | 93.3 |

## Routing & Confirmed Precision (Target: >=95% on Unambiguous Non-Image)
| Slice | Coverage (Confirmed %) | Confirmed Count | L2 Strict on Confirmed | Wilson 95% LB (Strict) | L2 Lenient on Confirmed | Wilson 95% LB (Lenient) |
|---|---|---|---|---|---|---|
| ALL (145) | 44.8% | 65/145 | 63.1% | **50.9%** | 81.5% | **70.4%** |
| VERIFIED (20 BLR) | 45.0% | 9/20 | 77.8% | **45.3%** | 77.8% | **45.3%** |
| SILVER (125) | 44.8% | 56/125 | 60.7% | **47.6%** | 82.1% | **70.2%** |
| TEXT-TAGGABLE (Non-Image) | 55.1% | 65/118 | 63.1% | **50.9%** | 81.5% | **70.4%** |
| IMAGE-DEPENDENT | 0.0% | 0/27 | 0.0% | **0.0%** | 0.0% | **0.0%** |
| UNAMBIGUOUS NON-IMAGE (95% Target) | 40.0% | 6/15 | 83.3% | **43.6%** | 83.3% | **43.6%** |

Auto-confirmed is what the system will treat as settled without review. Wilson 95% LB is the conservative statistical lower bound on precision.

## Accuracy by Model Fit
| Fit | N | L1 strict | L2 strict | L2 lenient | Auto-confirmed % |
|---|---|---|---|---|---|
| good | 117 | 80.3% | 68.4% | 84.6% | 55.6% |
| weak | 28 | 89.3% | 78.6% | 85.7% | 0.0% |

## Accuracy by Pipeline Status
| Status | N | L1 strict | L2 strict | L2 lenient | Avg Confidence |
|---|---|---|---|---|---|
| confirmed | 65 | 78.5% | 63.1% | 81.5% | 0.90 |
| draft | 80 | 85.0% | 76.2% | 87.5% | 0.64 |

## Cost & Latency (USD & INR @ 87.0 INR/USD)
| Slice | Avg in tok | Avg out tok | p50 latency (ms) | p95 latency (ms) | Cost / 1k (USD) | Cost / 1k (INR) |
|---|---|---|---|---|---|---|
| ALL (145) | 1287 | 161 | 1989 | 2550 | $0.1447 | ₹12.59 |
| VERIFIED (20 BLR) | 1286 | 160 | 1975 | 2225 | $0.1444 | ₹12.57 |
| SILVER (125) | 1287 | 161 | 1989 | 2554 | $0.1448 | ₹12.59 |
| TEXT-TAGGABLE (Non-Image) | 1285 | 164 | 1988 | 2578 | $0.1456 | ₹12.67 |
| IMAGE-DEPENDENT | 1294 | 146 | 1989 | 2364 | $0.1407 | ₹12.24 |
| UNAMBIGUOUS NON-IMAGE (95% Target) | 1287 | 154 | 1931 | 2958 | $0.1428 | ₹12.42 |

## Top 15 Confusion Pairs (Gold L2 × Predicted L2)
| Count | Gold L2 | Predicted L2 | Lenient Accepted? |
|---|---|---|---|
| 4 | Money History | Banking | Yes (Alt) |
| 2 | Money History | Brand Identity | No (Mismatch) |
| 2 | Company Origins | Brand Identity | Yes (Alt) |
| 2 | Entertainment | Stock Markets | Yes (Alt) |
| 1 | Artificial Intelligence | Internet Platforms | Yes (Alt) |
| 1 | Advertising | Brand Collabs | Yes (Alt) |
| 1 | Global Trade | Government Policy | Yes (Alt) |
| 1 | Stock Markets | Company Origins | Yes (Alt) |
| 1 | Money History | Word Origins | No (Mismatch) |
| 1 | Brand Identity | Consumer Brands | No (Mismatch) |
| 1 | Advertising | Banking | Yes (Alt) |
| 1 | Company Origins | Sponsorships | No (Mismatch) |
| 1 | Company Origins | Banking | No (Mismatch) |
| 1 | Market Concepts | Word Origins | Yes (Alt) |
| 1 | Money History | Investment Funds | Yes (Alt) |

## Every mistake, for human review
| id | gold L2 | pred L2 | status | confidence |
|---|---|---|---|---|
| zvq-pre-001 | Money History | Brand Identity | draft | 0.50 |
| zvq-pre-012 | Company Origins | Brand Identity | confirmed | 0.90 |
| zvq-pre-022 | Money History | Word Origins | draft | 0.70 |
| zvq-pre-026 | Brand Identity | Consumer Brands | draft | 0.75 |
| zvq-pre-034 | Company Origins | Sponsorships | confirmed | 0.90 |
| zvq-pre-035 | Company Origins | Banking | draft | 0.75 |
| zvq-pre-061 | Sponsorships | Consumer Brands | draft | 0.70 |
| zvq-fin-001 | Global Trade | Consumer Prices | confirmed | 0.90 |
| zvq-fin-004 | Business Leaders | Finance Books | confirmed | 0.90 |
| zvq-fin-005 | Brand Collabs | Consumer Brands | draft | 0.50 |
| zvq-fin-007 | Heritage | Indian Economy | confirmed | 0.90 |
| zvq-fin-009 | Company Origins | Finance Books | confirmed | 0.90 |
| zvq-fin-018 | Money History | Brand Identity | draft | 0.50 |
| zvq-fin-019 | Business Jargon | Banking | draft | 0.70 |
| zvq-fin-026 | Entertainment | Brand Identity | draft | 0.70 |
| zvq-fin-027 | Advertising | Brand Identity | confirmed | 0.90 |
| zvq-fin-030 | Advertising | Sports Leagues | draft | 0.50 |
| zvq-fin-038 | Government Policy | Commodities | confirmed | 0.90 |
| zvq-fin-047 | Corporate Scandals | Finance Books | confirmed | 0.90 |
| zvq-fin-048 | Money History | Company Origins | confirmed | 0.90 |
| zvq-blr-005 | Finance Books | Market Concepts | confirmed | 0.90 |
| zvq-blr-015 | Corporate Scandals | Company Origins | confirmed | 0.90 |