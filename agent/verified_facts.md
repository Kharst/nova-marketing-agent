# Verified facts: the only regulatory and technical claims the agents may state

This file is owned by the founder (Ben). If a page on the website says something different, this file wins.

How this file works
- Every claim about what a law, regulator, standard, utility or municipality REQUIRES, ALLOWS or DEFINES
  (anything with words like "compliant", "aligned to", "approved", "registered", "the standard says")
  may only be written if a VERIFIED line below says it.
- If a claim is not listed, the agents describe what Solar Intelligence does instead
  ("Solar Intelligence flags a ratio outside the range you set") and never what the standard requires.
- To approve a claim: add one line starting with VERIFIED: , write the claim in plain words, then say
  where you checked it. Only add what you have checked yourself.
- NEVER lines are claims known to be wrong. The text after || is a pattern the code searches for, so the
  claim is blocked automatically before the editor even reads it. Delete a line if you no longer want the rule.
- PENDING lines are things that appear on the website or in the agent brief but are NOT yet confirmed.
  The agents may only describe them as what Solar Intelligence assumes, never as what a law or standard says.
  When you have checked one, move it to a VERIFIED: line (or to a NEVER: line if it is wrong).
- Statements about what Solar Intelligence itself does are fine without being listed here.
- How to edit: github.com, this repository, agent folder, verified_facts.md, pencil icon, Commit changes.

## Verified (add your own lines here, starting with VERIFIED:)
# VERIFIED: <the claim in plain words> (checked: <document or website>, <date>)

## Never say
NEVER: Do not say NRS 097-2-1 sets, defines or requires a DC/AC ratio range (such as 1.0 to 1.5), or that a ratio is compliant with NRS 097-2-1. || (NRS\s*097[^.\n]{0,160}(DC\s*/\s*AC|ratio))|((DC\s*/\s*AC|ratio)[^.\n]{0,160}NRS\s*097)
NEVER: Do not say a system is "NRS 097-2-1 compliant" or that Solar Intelligence makes a system compliant. || NRS\s*097[-\s]?2[-\s]?1[^.\n]{0,40}(compliant|complies|compliance)|(compliant|complies|compliance)[^.\n]{0,40}NRS\s*097
NEVER: Do not promise that a municipality, Eskom or NERSA will approve or register a system. || (will|guarantee[sd]?|ensures?)\s+(be\s+)?(approved|registered|accepted)|guarantee[^.\n]{0,80}(approv|regist|NERSA|Eskom|municipal)
NEVER: Do not say Solar Intelligence ensures, certifies or guarantees legal or regulatory compliance. || (certif(y|ies|ied)|ensures?|guarantees?)\s+(full\s+)?(legal\s+|regulatory\s+)?compliance

## Pending review (add or remove lines starting with PENDING:)
PENDING: Specific yield of 1,700 kWh/kWp/yr attributed to the SAURAN Solar Atlas, with an 80% performance ratio and 97% availability.
PENDING: Tariff escalation of 8.76% (2026), 8.83% (2027) and about 5% a year after, attributed to NERSA's multi-year price determination.
PENDING: Section 12B tax treatment: 100% first-year write-off for systems up to 1MW, 50/30/20 over three years above 1MW.
PENDING: Panel degradation of 0.55% a year attributed to IEC 61215 (check what IEC 61215 actually covers before anyone cites it).
PENDING: Systems classed as NERSA SSEG Category A and B.
PENDING: The recommended DC/AC ratio range quoted in the website sizing guide (check it and the NRS wording in the product).
