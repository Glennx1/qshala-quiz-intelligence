# QShala tagger evaluation — gemini-3.5-flash-lite

Run: 2026-10-22 13:21  |  N: 145  |  throttle: 2.5s/req

The **VERIFIED** row (20 Bangalore prelims reviewed by a quizmaster) is the real signal. The **SILVER** row (125 vault questions with my own first-pass labels) is directional only.

## Accuracy
| Slice | N | L1 strict | L2 strict | L2 lenient | Entity | Geo | Shelf | Sens | KW format | Answer in KW |
|---|---|---|---|---|---|---|---|---|---|---|
| ALL (145) | 145 | 82.8 | 71.0 | 84.1 | 86.2 | 88.3 | 77.2 | 97.2 | 100.0 | 92.4 |
| VERIFIED (20 BLR) | 20 | 100.0 | 90.0 | 95.0 | 90.0 | 80.0 | 70.0 | 90.0 | 100.0 | 95.0 |
| SILVER (125) | 125 | 80.0 | 68.0 | 82.4 | 85.6 | 89.6 | 78.4 | 98.4 | 100.0 | 92.0 |
| TEXT-TAGGABLE (Non-Image) | 118 | 82.2 | 69.5 | 84.7 | 85.6 | 88.1 | 79.7 | 97.5 | 100.0 | 94.1 |
| IMAGE-DEPENDENT | 27 | 85.2 | 77.8 | 81.5 | 88.9 | 88.9 | 66.7 | 96.3 | 100.0 | 85.2 |
| UNAMBIGUOUS NON-IMAGE (95% Target) | 15 | 100.0 | 100.0 | 100.0 | 93.3 | 73.3 | 86.7 | 93.3 | 100.0 | 93.3 |

## Routing & Confirmed Precision (Target: >=95% on Unambiguous Non-Image)
| Slice | Coverage (Confirmed %) | Confirmed Count | L2 Strict on Confirmed | Wilson 95% LB (Strict) | L2 Lenient on Confirmed | Wilson 95% LB (Lenient) |
|---|---|---|---|---|---|---|
| ALL (145) | 44.8% | 65/145 | 64.6% | **52.5%** | 83.1% | **72.2%** |
| VERIFIED (20 BLR) | 45.0% | 9/20 | 88.9% | **56.5%** | 88.9% | **56.5%** |
| SILVER (125) | 44.8% | 56/125 | 60.7% | **47.6%** | 82.1% | **70.2%** |
| TEXT-TAGGABLE (Non-Image) | 55.1% | 65/118 | 64.6% | **52.5%** | 83.1% | **72.2%** |
| IMAGE-DEPENDENT | 0.0% | 0/27 | 0.0% | **0.0%** | 0.0% | **0.0%** |
| UNAMBIGUOUS NON-IMAGE (95% Target) | 40.0% | 6/15 | 100.0% | **61.0%** | 100.0% | **61.0%** |

Auto-confirmed is what the system will treat as settled without review. Wilson 95% LB is the conservative statistical lower bound on precision.

## Accuracy by Model Fit
| Fit | N | L1 strict | L2 strict | L2 lenient | Auto-confirmed % |
|---|---|---|---|---|---|
| good | 117 | 82.1% | 69.2% | 84.6% | 55.6% |
| weak | 28 | 85.7% | 78.6% | 82.1% | 0.0% |

## Accuracy by Pipeline Status
| Status | N | L1 strict | L2 strict | L2 lenient | Avg Confidence |
|---|---|---|---|---|---|
| confirmed | 65 | 80.0% | 64.6% | 83.1% | 0.90 |
| draft | 80 | 85.0% | 76.2% | 85.0% | 0.64 |

## Cost & Latency (USD & INR @ 87.0 INR/USD)
| Slice | Avg in tok | Avg out tok | p50 latency (ms) | p95 latency (ms) | Cost / 1k (USD) | Cost / 1k (INR) |
|---|---|---|---|---|---|---|
| ALL (145) | 1287 | 160 | 2053 | 20192 | $0.1444 | ₹12.57 |
| VERIFIED (20 BLR) | 1286 | 153 | 2004 | 3226 | $0.1424 | ₹12.39 |
| SILVER (125) | 1287 | 161 | 2064 | 20811 | $0.1448 | ₹12.59 |
| TEXT-TAGGABLE (Non-Image) | 1285 | 162 | 2073 | 21973 | $0.1449 | ₹12.60 |
| IMAGE-DEPENDENT | 1294 | 151 | 1990 | 2905 | $0.1425 | ₹12.40 |
| UNAMBIGUOUS NON-IMAGE (95% Target) | 1287 | 158 | 2107 | 21973 | $0.1439 | ₹12.52 |

## Top 15 Confusion Pairs (Gold L2 × Predicted L2)
| Count | Gold L2 | Predicted L2 | Lenient Accepted? |
|---|---|---|---|
| 4 | Money History | Banking | Yes (Alt) |
| 2 | Money History | Brand Identity | No (Mismatch) |
| 2 | Company Origins | Brand Identity | Yes (Alt) |
| 2 | Entertainment | Business Leaders | No (Mismatch) |
| 2 | Corporate Scandals | Company Origins | Yes (Alt) |
| 1 | Artificial Intelligence | Internet Platforms | Yes (Alt) |
| 1 | Advertising | Brand Collabs | Yes (Alt) |
| 1 | Stock Markets | Company Origins | Yes (Alt) |
| 1 | Money History | Word Origins | No (Mismatch) |
| 1 | Brand Identity | Consumer Brands | No (Mismatch) |
| 1 | Advertising | Banking | Yes (Alt) |
| 1 | Entertainment | Stock Markets | Yes (Alt) |
| 1 | Company Origins | Consumer Brands | No (Mismatch) |
| 1 | Company Origins | Banking | No (Mismatch) |
| 1 | Market Concepts | Word Origins | Yes (Alt) |

## Every mistake, for human review
| id | gold L2 | pred L2 | status | confidence |
|---|---|---|---|---|
| zvq-pre-001 | Money History | Brand Identity | draft | 0.50 |
| zvq-pre-012 | Company Origins | Brand Identity | confirmed | 0.90 |
| zvq-pre-022 | Money History | Word Origins | draft | 0.70 |
| zvq-pre-026 | Brand Identity | Consumer Brands | draft | 0.75 |
| zvq-pre-034 | Company Origins | Consumer Brands | confirmed | 0.90 |
| zvq-pre-035 | Company Origins | Banking | draft | 0.75 |
| zvq-pre-044 | Entertainment | Sponsorships | draft | 0.70 |
| zvq-pre-052 | Entertainment | Business Leaders | confirmed | 0.90 |
| zvq-pre-061 | Sponsorships | Consumer Brands | draft | 0.70 |
| zvq-fin-001 | Global Trade | Consumer Prices | confirmed | 0.90 |
| zvq-fin-004 | Business Leaders | Finance Books | confirmed | 0.90 |
| zvq-fin-005 | Brand Collabs | Consumer Brands | draft | 0.50 |
| zvq-fin-009 | Company Origins | Finance Books | confirmed | 0.90 |
| zvq-fin-018 | Money History | Brand Identity | draft | 0.50 |
| zvq-fin-019 | Business Jargon | Brand Identity | draft | 0.70 |
| zvq-fin-027 | Advertising | Brand Identity | confirmed | 0.90 |
| zvq-fin-030 | Advertising | Sports Leagues | draft | 0.50 |
| zvq-fin-032 | Heritage | Brand Identity | confirmed | 0.90 |
| zvq-fin-038 | Government Policy | Commodities | confirmed | 0.90 |
| zvq-fin-043 | Advertising | Sponsorships | draft | 0.70 |
| zvq-fin-048 | Money History | Company Origins | confirmed | 0.90 |
| zvq-fin-050 | Advertising | Corporate Scandals | draft | 0.50 |
| zvq-blr-015 | Corporate Scandals | Company Origins | confirmed | 0.90 |