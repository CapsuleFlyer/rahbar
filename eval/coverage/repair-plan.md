# E2 coverage repair plan

- Current semantic coverage: 16/28 (57.1%)
- Similarity threshold: 0.85
- Existing golden questions: 51
- Uncovered candidates: 12

This is a review plan, not an automatic golden-set update. Verify source pages and expected answer phrases before adding any candidate.

## Candidates, lowest similarity first

| Live ID | Topic | Similarity | Source | Section | Exact duplicate? |
|---|---|---:|---|---|---|
| e28 | errata | 0.582 | monster-manual-errata-2018.pdf |  | no |
| e27 | errata | 0.616 | dungeon-master-s-guide-errata-2021.pdf |  | no |
| e26 | errata | 0.620 | player-s-handbook-errata-2021-scanned-copy.pdf |  | no |
| e25 | official-rulings | 0.672 | sage-advice-compendium-v2-7-2021.pdf |  | no |
| e19 | exploration | 0.728 | srd-5-2-1-2024.pdf | Travel Pace | no |
| e02 | version | 0.750 | srd-5-1-2014.pdf | Hide | no |
| e03 | version | 0.772 | srd-5-2-1-2024.pdf | Exhaustion | no |
| e07 | rest | 0.814 | srd-5-2-1-2024.pdf | Long Rest | no |
| e24 | combat | 0.844 | srd-5-1-2014.pdf | Opportunity Attacks | no |
| e17 | equipment | 0.847 | srd-5-2-1-2024.pdf | Weapons | no |
| e21 | combat | 0.849 | srd-5-2-1-2024.pdf | Stabilizing | no |
| e10 | conditions | 0.850 | srd-5-2-1-2024.pdf | Grappled | no |

## Candidate details

### e28 — errata

- Proposed question: What correction does the Monster Manual errata make?
- Source: monster-manual-errata-2018.pdf — section: 
- Nearest golden: g47 — What are the rules for making an ability check?
- Similarity: 0.582132
- Exact duplicate: no
- Required: verify the page number and expected answer phrases from the source.

### e27 — errata

- Proposed question: What corrections are listed in the Dungeon Master's Guide errata?
- Source: dungeon-master-s-guide-errata-2021.pdf — section: 
- Nearest golden: g47 — What are the rules for making an ability check?
- Similarity: 0.615672
- Exact duplicate: no
- Required: verify the page number and expected answer phrases from the source.

### e26 — errata

- Proposed question: What changes are listed in the Player's Handbook errata?
- Source: player-s-handbook-errata-2021-scanned-copy.pdf — section: 
- Nearest golden: g47 — What are the rules for making an ability check?
- Similarity: 0.619637
- Exact duplicate: no
- Required: verify the page number and expected answer phrases from the source.

### e25 — official-rulings

- Proposed question: What does the Sage Advice Compendium explain about rules interpretations?
- Source: sage-advice-compendium-v2-7-2021.pdf — section: 
- Nearest golden: g29 — In the newest Sage Advice rulings, does a creature that attacks from hiding stay hidden afterward?
- Similarity: 0.671975
- Exact duplicate: no
- Required: verify the page number and expected answer phrases from the source.

### e19 — exploration

- Proposed question: What happens to travel pace when moving slowly?
- Source: srd-5-2-1-2024.pdf — section: Travel Pace
- Nearest golden: g39 — How can a character increase their travel pace?
- Similarity: 0.727533
- Exact duplicate: no
- Required: verify the page number and expected answer phrases from the source.

### e02 — version

- Proposed question: How does the 2014 Hide action work? Stealth check versus passive Perception.
- Source: srd-5-1-2014.pdf — section: Hide
- Nearest golden: g20 — Under the 2014 rules, how does hiding work against a creature that is searching for you?
- Similarity: 0.750053
- Exact duplicate: no
- Required: verify the page number and expected answer phrases from the source.

### e03 — version

- Proposed question: How does the 2024 Exhaustion rule affect D20 Tests?
- Source: srd-5-2-1-2024.pdf — section: Exhaustion
- Nearest golden: g42 — What happens when a creature reaches six levels of Exhaustion under the 2024 rules?
- Similarity: 0.771675
- Exact duplicate: no
- Required: verify the page number and expected answer phrases from the source.

### e07 — rest

- Proposed question: How long is a Long Rest and what does it restore?
- Source: srd-5-2-1-2024.pdf — section: Long Rest
- Nearest golden: g49 — How long is a Long Rest, and what benefits does a character gain from it?
- Similarity: 0.813663
- Exact duplicate: no
- Required: verify the page number and expected answer phrases from the source.

### e24 — combat

- Proposed question: What does the 2014 rulebook say about opportunity attacks?
- Source: srd-5-1-2014.pdf — section: Opportunity Attacks
- Nearest golden: g48 — When does a creature provoke an opportunity attack under the 2014 rules?
- Similarity: 0.844172
- Exact duplicate: no
- Required: verify the page number and expected answer phrases from the source.

### e17 — equipment

- Proposed question: How many GP does a Longsword cost in the equipment weapon table?
- Source: srd-5-2-1-2024.pdf — section: Weapons
- Nearest golden: g18 — How much does a Longsword cost?
- Similarity: 0.846664
- Exact duplicate: no
- Required: verify the page number and expected answer phrases from the source.

### e21 — combat

- Proposed question: How can you stabilize another creature?
- Source: srd-5-2-1-2024.pdf — section: Stabilizing
- Nearest golden: g46 — How can you stabilize another creature that has 0 Hit Points?
- Similarity: 0.848524
- Exact duplicate: no
- Required: verify the page number and expected answer phrases from the source.

### e10 — conditions

- Proposed question: What does the Grappled condition do to a creature's Speed?
- Source: srd-5-2-1-2024.pdf — section: Grappled
- Nearest golden: g05 — What effects does the Grappled condition have?
- Similarity: 0.849507
- Exact duplicate: no
- Required: verify the page number and expected answer phrases from the source.

## Review rules

- A semantic miss is not automatically a missing knowledge topic; inspect its nearest golden question.
- The live-query dataset supplies a source filename and section, but not a verified page number.
- Expected answer phrases must be checked against the cited source passage.
- Do not add candidates marked as duplicates without a distinct information need.
