# Housing Agent Presentation Notes

Slide 1: The design thesis is a student-housing agent that chooses among three site-scraping tools.
Slide 2: The problem is understanding student preferences near university hubs well enough to choose the right tool.
Slide 3: Walk through the pipeline and branch points.
Slide 4: Explain the three site scrapers as the primary tools plus artifact persistence.
Slide 5: Be explicit that memory is structured state, not vector retrieval.
Slide 6: The three main tools are Ohana, RentalSource, and AffordableHousing; the LLM/planner support tool choice.
Slide 7: Routing logic: short-term/student/private room -> Ohana; long-term/full rental/multiple roommates -> RentalSource; affordable/voucher/accessibility -> AffordableHousing.
Slide 8: Threat model maps risks to guardrails.
Slide 9: Result presentation includes price, location-vs-campus, map artifact, comparisons, and narrowing commands.
Slide 10: Current verification: 108 tests passed, 4 live tests skipped by default.
Slide 11: Use the three transcripts as demo behaviors and acknowledge limitations.
