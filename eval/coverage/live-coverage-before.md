# Part E2 — semantic live-query coverage

- Embedding model: `nomic-embed-text`
- Golden questions compared: 45
- Live queries: 40 (28 in-domain, 12 out-of-domain)
- Cosine similarity threshold: 0.85
- In-domain coverage: 14/28 (50.0%)
- Out-of-domain queries above threshold: 0/12 (0.0%)

The cosine threshold is 0.85. The assignment paper gives 0.85 as an example for flagging a coverage gap. The nearest golden question is selected independently for every live query.

## Uncovered in-domain queries by topic

- **checks**: e22
- **combat**: e21, e24
- **conditions**: e10
- **equipment**: e17
- **errata**: e26, e27, e28
- **exploration**: e19
- **official-rulings**: e25
- **rest**: e07
- **spells**: e13
- **version**: e02, e03

## Per-query nearest golden question

| Live ID | Scope | Topic | Best golden ID | Cosine | Result |
|---|---|---|---|---:|---|
| e01 | in | version | g40 | 1.000 | covered |
| e02 | in | version | g20 | 0.750 | uncovered |
| e03 | in | version | g42 | 0.772 | uncovered |
| e04 | in | version | g11 | 0.878 | covered |
| e05 | in | combat | g32 | 0.906 | covered |
| e06 | in | combat | g45 | 0.922 | covered |
| e07 | in | rest | g02 | 0.811 | uncovered |
| e08 | in | combat | g03 | 0.911 | covered |
| e09 | in | conditions | g08 | 0.955 | covered |
| e10 | in | conditions | g05 | 0.850 | uncovered |
| e11 | in | class-features | g06 | 0.956 | covered |
| e12 | in | spells | g17 | 0.928 | covered |
| e13 | in | spells | g38 | 0.834 | uncovered |
| e14 | in | equipment | g12 | 0.956 | covered |
| e15 | in | equipment | g19 | 0.967 | covered |
| e16 | in | equipment | g13 | 0.999 | covered |
| e17 | in | equipment | g18 | 0.847 | uncovered |
| e18 | in | exploration | g30 | 0.867 | covered |
| e19 | in | exploration | g39 | 0.728 | uncovered |
| e20 | in | combat | g04 | 0.984 | covered |
| e21 | in | combat | g08 | 0.665 | uncovered |
| e22 | in | checks | g34 | 0.662 | uncovered |
| e23 | in | version | g40 | 0.888 | covered |
| e24 | in | combat | g20 | 0.677 | uncovered |
| e25 | in | official-rulings | g29 | 0.672 | uncovered |
| e26 | in | errata | g39 | 0.584 | uncovered |
| e27 | in | errata | g06 | 0.576 | uncovered |
| e28 | in | errata | g09 | 0.582 | uncovered |
| e29 | out | technical-outside-domain | g07 | 0.582 | uncovered |
| e30 | out | general-science | g22 | 0.554 | uncovered |
| e31 | out | general-science | g07 | 0.510 | uncovered |
| e32 | out | technical-outside-domain | g40 | 0.475 | uncovered |
| e33 | out | food-outside-domain | g38 | 0.453 | uncovered |
| e34 | out | mathematics-outside-domain | g38 | 0.521 | uncovered |
| e35 | out | finance-outside-domain | g04 | 0.533 | uncovered |
| e36 | out | history-outside-domain | g08 | 0.522 | uncovered |
| e37 | out | technical-outside-domain | g04 | 0.528 | uncovered |
| e38 | out | engineering-outside-domain | g42 | 0.574 | uncovered |
| e39 | out | biology-outside-domain | g45 | 0.488 | uncovered |
| e40 | out | geology-outside-domain | g37 | 0.607 | uncovered |
