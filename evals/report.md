# LaunchScout benchmark

Run on 17 Nov 2026 · 3 cases · research model `gpt-4o-mini` (stages 1-2) / `gpt-4o-mini` (stages 3-4) · judge `gpt-4o-mini`

## Summary vs targets

| Metric | Result | Target | |
|---|---|---|---|
| Structure pass (6 sections, ≥3 competitors, citations resolve) | 100.0% | 100% | ✅ |
| Sources reachable | 100.0% | ≥ 90% | ✅ |
| Prices confirmed on their source | 100.0% | ≥ 70% | ✅ |
| Judge average (1-5) | 4.25 | ≥ 4 | ✅ |
| Average competitors | 3.3 | 3-5 | |
| Average time per run | 64.9 s | < 480 s | |
| Average cost per run | $0.0065 | | |

## Per case

| Case | Sections | Competitors | Sources reachable | Prices confirmed | Judge | Time | Cost |
|---|---|---|---|---|---|---|---|
| Healthy millet meal boxes, Coimbatore | ✅ | 3 | 4/4 | 1/1 | 4.0 | 72 s | $0.0068 |
| Pet grooming at home, Chennai | ✅ | 4 | 6/6 | 2/2 | 4.0 | 64 s | $0.0073 |
| Silk saree shop, Udumalpet | ✅ | 3 | 6/6 | 1/1 | 4.75 | 59 s | $0.0056 |

## Judge details

### Healthy millet meal boxes, Coimbatore (average 4.0)

The report provides a solid foundation but lacks some competitor pricing details for improved specificity.

| Criterion | Score | Quote from the report | Reason |
|---|---|---|---|
| specificity | 3 | “Mummy's Cloud Kitchen / From Rs 180 per meal / Own website” | Some specific pricing is provided, but many competitors lack listed prices. |
| grounding | 4 | “Food is light, refreshing, and guilt-free, suitable for cravings or mid-day snacks (Zero Cals) [4]” | Most claims are supported by citations, but some competitor details are vague. |
| actionability | 4 | “"Healthy millet meal boxes delivered fresh, Rs 150 per meal."” | The positioning and pricing are clear, but more competitor details would enhance strategy. |
| plan_realism | 5 | “- Week 1: Create a simple website and social media profiles to establish an online presence.” | The plan is concrete, budget-friendly, and builds logically week by week. |

### Pet grooming at home, Chennai (average 4.0)

The report is strong in specificity and actionability, but grounding needs improvement for better credibility.

| Criterion | Score | Quote from the report | Reason |
|---|---|---|---|
| specificity | 4 | “ThePetNest / Rs 999+ per session / Own website, Mobile app / Offers a range of grooming packages tailored to pet needs.” | Specific competitors and their pricing are mentioned, but some prices are not listed. |
| grounding | 3 | “No complaints were found in the public reviews collected for these competitors.” | The report lacks citations for customer complaints, limiting its grounding. |
| actionability | 5 | “"At-home pet grooming with clear pricing starting at Rs 899 per session."” | The market gap and pricing strategy are clearly defined and actionable. |
| plan_realism | 4 | “Week 1: Create a simple website and social media profiles to establish an online presence.” | The plan is concrete and feasible, but could include more detail on budget. |

### Silk saree shop, Udumalpet (average 4.75)

The report is thorough and actionable, with minor improvements needed in the launch plan's budget details.

| Criterion | Score | Quote from the report | Reason |
|---|---|---|---|
| specificity | 5 | “ST Silks / Rs 4,200 per soft silk saree / WhatsApp, Own website” | The report provides specific competitor names, prices, and channels. |
| grounding | 5 | “Poor finishing on saree stitching (Shubhankari Silks) [4]” | All claims are supported by citations, ensuring credibility. |
| actionability | 5 | “Premium silk sarees with exquisite finishing starting at Rs 3,800 each.” | The market gap and pricing strategy are clearly defined and actionable. |
| plan_realism | 4 | “Week 1: Establish a social media presence on Instagram and Facebook...” | The plan is concrete but could include more budget details. |

## Notes

- Sources count as reachable when they answer, or when a listing platform (e.g. Zomato) refuses or stalls automated requests; a competitor's own site that fails counts as broken. Raw statuses are in each run's `checks.json`.
- A price is confirmed when its number appears in the text fetched from one of its cited sources. Prices written as "Not listed" are not counted.
- Search responses cached during development are reused for repeated queries; research stages, checks and judging ran fresh. Judging cost $0.0009 in total.
