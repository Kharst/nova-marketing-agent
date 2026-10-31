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
VERIFIED: Since 1 October 2023 every solar PV system on a City of Cape Town supply point, with or without batteries, is treated as grid-tied, so off-grid and standby PV systems are no longer accepted; solar PV geysers are the one off-grid type still allowed. (checked: City of Cape Town SSEG requirements, Oct 2026)
VERIFIED: The City of Cape Town requires the SSEG application to be signed by the property owner; if an installer applies on the owner's behalf, an approved letter of proxy must be attached. (checked: City of Cape Town SSEG requirements, Oct 2026)
VERIFIED: Applications to the City of Cape Town are made on its online SSEG application platform. (checked: City of Cape Town SSEG requirements, Oct 2026)
VERIFIED: The City of Cape Town issues a Permission to Install letter. Installers should not buy equipment before it is issued because approval is not guaranteed, and registration must be completed within three months of the letter or the application is cancelled. (checked: City of Cape Town SSEG requirements, Oct 2026)
VERIFIED: Every inverter connected in the City of Cape Town must be type tested to NRS 097-2-1 by an accredited body and must appear on the City's approved inverter list, which is updated monthly. (checked: City of Cape Town SSEG requirements and EEB 705, Oct 2026)
VERIFIED: In the City of Cape Town, an exporting system needs a bi-directional AMI meter at the customer's cost, and a non-export system needs reverse power flow blocking protection. (checked: City of Cape Town SSEG requirements, Oct 2026)
VERIFIED: The City of Cape Town sets no maximum battery capacity, but the maximum battery charging current is 25% of the service circuit breaker size. (checked: City of Cape Town SSEG requirements, Oct 2026)
VERIFIED: In the City of Cape Town, until SANS 10142-1-2 is published, grid-tied systems need an ECSA professional sign-off: an engineer, engineering technologist or certified engineer for residential, commercial and industrial systems, or a professional technician for residential systems only. (checked: City of Cape Town SSEG requirements, Oct 2026)
VERIFIED: After commissioning, a system on the City of Cape Town grid must stay disconnected until the Commissioning Approval Letter is issued; generating without it brings a contravention notice and a service fee. (checked: City of Cape Town SSEG requirements, Oct 2026)
VERIFIED: City of Cape Town drawing SK5276 gives the symbols and typical layouts for circuit diagrams, and on hybrid systems the essential loads must be fed through an interlocked change-over switch or from a separate sub-DB fed by the inverter, never directly from the grid. (checked: City of Cape Town drawing guideline SK5276, Oct 2026)
VERIFIED: Applications to the City of Ekurhuleni for systems below 1 MVA are made online at apply.sseg.org.za. (checked: City of Ekurhuleni email, Oct 2026)
VERIFIED: The City of Ekurhuleni requires Annexure 4, the Notice of Commencement of Installation Work, to be completed by the electrician who will issue the CoC; the application is not approved without it. (checked: City of Ekurhuleni Annexure 4 and email, Oct 2026)
VERIFIED: The City of Ekurhuleni asks for an NRS 097-2-1 type test certificate for the inverter, issued by an accredited third-party test house, and a separate NRS 097-2-1 certificate if a storage inverter runs in parallel. (checked: City of Ekurhuleni SSEG Commissioning Report, Oct 2026)
VERIFIED: The City of Ekurhuleni requires the final as-built circuit diagram to show the point of connection to the municipal network, the protection devices, the breakers, isolators and disconnectors, the measurement locations and the connection point of the SSEG to the total system. (checked: City of Ekurhuleni SSEG Commissioning Report, Oct 2026)
VERIFIED: After installation the City of Ekurhuleni asks for a completed and signed commissioning form, the CoC for the PV installation, photos of the safety labels at the municipal supply point showing dual supply, and the final as-built circuit diagram. (checked: City of Ekurhuleni email, Oct 2026)
VERIFIED: The City of Ekurhuleni commissioning declaration includes an on-site anti-islanding test, a momentary disconnection of the mains supply, and confirmation that safety labels are fitted in line with NRS 097-2-1 at the distribution board and metering point. (checked: City of Ekurhuleni SSEG Commissioning Report, Oct 2026)
VERIFIED: In the City of Ekurhuleni, exporting needs a 4-quadrant bi-directional AMR meter installed by the City at the customer's cost, manual-read credit and prepayment meters may not run backwards, and systems that do not export must install reverse power flow blocking protection. (checked: City of Ekurhuleni email, Oct 2026)

## Never say
NEVER: Do not say Solar Intelligence flags a DC/AC ratio below 1.0, checks depth of discharge stays within 85%, or never silently approves a design. It flags a ratio above 1.5 (commercial proposals only) and a battery that cannot meet 98% of the requested runtime. || (flags?\s+a?\s*ratio\s+outside)|(checks?\s+that\s+the\s+depth\s+of\s+discharge)|(not\s+silently\s+approve)
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

