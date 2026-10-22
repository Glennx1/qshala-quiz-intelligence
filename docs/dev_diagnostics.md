# Item-5 Dev-Set Diagnostics (Read-Only Analysis on 145 Questions)

Evaluated Run 2 Flash-Lite on updated ground truth (N = 145).

## 1. Top Remaining Confusion Pairs (Gold L2 vs. Predicted L2)
| Gold Subtopic | Predicted Subtopic | Count | Notes |
|---|---|---|---|
| Money History | Brand Identity | 2 | Boundary ambiguity between Money History and Brand Identity |
| Company Origins | Consumer Brands | 1 | Boundary ambiguity between Company Origins and Consumer Brands |
| Company Origins | Banking | 1 | Boundary ambiguity between Company Origins and Banking |
| Entertainment | Sponsorships | 1 | Boundary ambiguity between Entertainment and Sponsorships |
| Global Trade | Consumer Prices | 1 | Boundary ambiguity between Global Trade and Consumer Prices |
| Government Policy | Commodities | 1 | Boundary ambiguity between Government Policy and Commodities |
| Social Impact | Corporate Scandals | 1 | Boundary ambiguity between Social Impact and Corporate Scandals |

## 2. Performance by Macro Domain (Level 1)
| Domain (L1) | N | L1 Strict | L2 Strict | L2 Lenient |
|---|---|---|---|---|
| Banking & Money | 28 | 82.1% | 71.4% | 92.9% |
| Companies & Business | 28 | 75.0% | 60.7% | 92.9% |
| Culture & Society | 22 | 90.9% | 86.4% | 95.5% |
| Brands & Marketing | 20 | 85.0% | 70.0% | 100.0% |
| Sports & Entertainment | 15 | 80.0% | 73.3% | 93.3% |
| Economy & Policy | 13 | 84.6% | 76.9% | 84.6% |
| Markets & Investing | 13 | 84.6% | 84.6% | 100.0% |
| Technology | 6 | 100.0% | 66.7% | 100.0% |

## 3. Performance by Self-Rated Fit
| Fit | N | L2 Lenient Accuracy | Auto-Confirmed % |
|---|---|---|---|
| good | 117 | 95.7% | 55.6% |
| weak | 28 | 89.3% | 0.0% |

## 4. Non-L2 Metadata Accuracy
- **Entity Type**: 86.2% (125/145)
- **Geography (India vs. International)**: 88.3% (128/145)
- **Shelf Life (Evergreen vs. Time-Sensitive)**: 77.2% (112/145)
- **Sensitivity**: 97.2% (141/145)

## 5. Complete Roster of Remaining Disagreements (Lenient Misses)
| ID | Gold L2 | Pred L2 | Status | Fit | Question Snippet |
|---|---|---|---|---|---|
| zvq-pre-001 | Money History | Brand Identity | draft | weak | What is the significance of this photo of Mahatma Gandhi with Lord Frederick William Pethi... |
| zvq-pre-034 | Company Origins | Consumer Brands | confirmed | good | 24 years. A billion inspired. Now, he is channeling decades of experience into crafting sp... |
| zvq-pre-035 | Company Origins | Banking | draft | good | ‘A Bank for the Buck’ is the untold tale of how India’s biggest bank by market capitalizat... |
| zvq-pre-044 | Entertainment | Sponsorships | draft | good | In one of the most unexpected crossovers in Indian television, this person was seen offeri... |
| zvq-fin-001 | Global Trade | Consumer Prices | confirmed | good | In 2014, The World Bank published a blog addressing the increasing wealth gap in the world... |
| zvq-fin-018 | Money History | Brand Identity | draft | weak | Created by German designer, Arthur Eisenmenger, this is the logo of the CE mark, a standar... |
| zvq-fin-038 | Government Policy | Commodities | confirmed | good | On Jan 14, 2025 Union Minister of Commerce and Industry Piyush Goyal, and Nizamabad MP, Dh... |
| zvq-fin-050 | Social Impact | Corporate Scandals | draft | weak | This ad by a family-run company named Böcker is about which incident? One of their mobile ... |