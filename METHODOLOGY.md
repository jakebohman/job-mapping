# How Job Maps works in plain language

This document explains, without jargon, exactly where the
numbers on the map come from and how they're calculated, so you can judge
whether the map measures something real and useful.

---

## The question the map answers

> **Relative to its size, where is a metro area hiring hard right now?**

The map asks whether a place is posting more or fewer jobs than you'd expect for
the number of people who work there. That's what lets a mid-size metro like
Des Moines or Bismarck light up as brightly as a giant like New York.

Every shaded metro has a single number: **Job postings per 1,000 workers.**
If a metro shows **20**, that means that for every 1,000 people in its
workforce, there were about 20 distinct current job postings. Higher = the
local labor market is advertising more openings relative to its size, a sign of
tighter hiring, churn, or growth. It is a **rate of advertised demand**, not a
count of jobs and not a measure of employment.

## Where the raw data comes from

Our data is gathered from three free, reliable, and publicly available APIs.

| What | Source | What we take from it |
|---|---|---|
| **The job postings** | [Adzuna job-search API](https://www.adzuna.com/) | How many postings currently exist near each metro, plus a 50-posting sample to check *where* they really are |
| **The workforce size** | [US Bureau of Labor Statistics](https://www.bls.gov/) | The official labor-force count for each metro |
| **The map shapes** | [US Census Bureau](https://www.census.gov/) | The metro and state boundaries drawn on screen |

A "metro" here is a **Metropolitan Statistical Area (MSA)**, the government's
official definition of a city plus its commuting region, defined as a set of
counties. There are 393 of them (387 outside Puerto Rico). A job posting reports its county, an MSA is a list of counties, and BLS reports by MSA, so everything
lines up on the same map.

## How the number is built (with a worked example)

For each of the 387 metros we do this:

1. **Ask Adzuna how many postings are near the metro.** We search around the
   metro's main city and get back a total *count* and a *sample* of 50 actual
   postings. → *Columbus, OH: 57,693 postings in range.*

2. **Figure out how many are actually in the metro.** Adzuna searches a *circle*
   around a city, but a metro isn't a circle; the circle spills into neighbors.
   So we look at the 50 sampled postings and see what fraction report a county
   that's really inside the metro. → *86% of Columbus's sample were in the
   Columbus metro, so we keep 86% of the count: 57,693 × 0.86 ≈ 49,600.*

3. **Remove the reposts.** Job aggregators are flooded with the same opening
   posted many times. In the sample we collapse postings that share a title and
   employer, and measure what fraction survive. → *Only 46.5% of Columbus's
   in-metro postings were distinct, so: 49,600 × 0.465 ≈ 23,100 distinct
   openings.*

4. **Divide by the workforce, scale to per-1,000.** → *Columbus has about
   1,165,000 workers, so: 23,100 ÷ 1,165,000 × 1,000 =* **19.8 postings per
   1,000 workers.**

In one line:

```
Estimated Job Openings per 1,000 workers = (raw count  ×  share truly in the metro  ×  share not a repost)  ÷  workforce  × 1,000
```

The middle two multipliers are corrections that turn a rough, inflated raw count
into an honest one. The next section explains why each matters.

## The three corrections (and why the map would lie without them)

1. **We count postings; we don't sample-and-classify them.** Adzuna's results
   are ranked by a few big advertisers, so if you take a *sample* and analyze
   it, one hospital chain can make a whole city look 90% healthcare. A *total
   count* can't be skewed that way; it's a census, not a poll. This is the
   single most important design choice. The honest caveat: while the raw count
   is a census, the two multipliers below (the in-metro share and the repost
   fraction) are *both* read off that same ranked 50-posting sample. So the count
   is immune to the ranking, but the corrections applied to it are not, and for a
   metro near the cutoff they rest on as few as five postings. This is why the
   corrected rate is a solid *relative* signal but not a precise census.

2. **The "share truly in the metro" fix (we call it f\_m).** Because Adzuna
   searches a circle, a small metro next to a big one can accidentally measure
   its neighbor. Checking the sampled postings' real counties and keeping only
   that fraction corrects the geography. Without it, Columbus **Indiana** would
   report Indianapolis's postings and look impossibly hot.

3. **The repost correction.** Aggregator feeds are heavy with the same opening
   posted many times, so we measure the distinct fraction (postings sharing a
   title and employer) and apply it. Be honest about how much this actually
   corrects: it is measured *per metro on that metro's slice of the 50-posting
   sample*, and across the map it removes only about 18% on average, far less
   than the "half are duplicates" figure often quoted for raw feeds. For a small
   metro, where only a handful of the 50 sampled postings land inside it, the
   sample is too thin for two postings to collide on title and employer, so the
   correction frequently removes **nothing at all** (a ratio of 1.0). The effect
   is bounded, though: the correction only ever ranges from removing about half to
   removing none, so the worst it can do is leave a rate about 15 to 20 percent
   high, and the **ranking is essentially unchanged** (the highest small metros
   stay highest). Read the exact value at the extreme top as modestly inflated,
   not the ordering. (It's also a *lower bound*: it can merge
   genuinely separate openings at the same employer, so where it does apply, the
   true number is a little higher.)

## When a metro is left blank (gray)

A metro is shown gray, with no number, when we can't measure it accurately. Three
reasons:

- **Too few postings actually in the metro** (fewer than ~50 effective): too
  small a signal to trust.
- **Too little of the search sample landed inside the metro** (under 10%). This
  happens to a *small metro sitting next to a much larger one*, whose search
  circle is dominated by the big neighbor. We retry these with a tighter search
  circle, which rescues most; the ones that stay gray are wedged between two
  giants (e.g. Trenton and Allentown, both in the New York-Philadelphia corridor)
  and can't be cleanly separated. Showing a number there would be guessing.
- **No official workforce figure available** for the metro.

As of the latest build **all 387 measurable metros shade** (none currently fall
below the thresholds, after the gray-recovery step re-anchors or tightens the
search circle for swamped metros). The gray rules above still apply to any future
metro that can't be measured honestly: the map declines to show a number it can't
stand behind. (Puerto Rico's 6 metros are excluded entirely; the data provider
returns unreliable locations for them.)

## What this is good for (real-world uses)

- **Spotting where hiring is unusually hot or cold** relative to size, a
  labor-market tightness signal that a raw job count hides.
- **Comparing metros fairly** regardless of population (a recruiter, job seeker,
  or economic-development office comparing Boise to Boston).
- **Tracking change over time** if rebuilt regularly: a rising rate flags a
  heating-up market before it shows up in slower official statistics.
- **Slicing hiring by sector.** The map has a dropdown to re-shade by any of
  Adzuna's ~30 categories: "IT jobs per 1,000 workers," "Travel jobs per 1,000,"
  etc. Each is the metro's total rate multiplied by that sector's share of its
  postings, so the sectors add up to the total. A **toggle** also switches the
  whole map between this per-1,000 rate and *total* postings (raw volume, ignoring
  metro size), for either the total or a single sector. A **companion view**
  ([sectors.html](site/sectors.html)) ranks where each metro over- and
  under-indexes on a sector versus the national mix.

## What it can't tell you (limits worth knowing)

- It measures **advertised demand, not employment or hires.** Lots of postings
  can mean growth *or* high turnover.
- Postings **over-represent high-churn work** (retail, driving, healthcare
  staffing) that gets re-advertised constantly.
- It's built on **one data provider (Adzuna)**; a different provider would give
  somewhat different absolute levels. Read the map for **relative** intensity
  and rank, not as a precise posting census.
- The workforce figures lag by a couple of months (normal for official data).
- A handful of places with messy source data are excluded (e.g. Puerto Rico,
  where the provider returns unreliable locations).

## How to spot-check it yourself

- **Hover any metro** on the map: it shows the rate, its rank, the raw posting
  count, and the workforce: the ingredients above, so you can see the math.
- **Sanity test:** big diverse metros should sit mid-pack (New York is 11.4, not
  the top), and no metro is graded on just one or two sampled postings (the
  cutoff needs at least five in-metro postings in the sample). Most shaded rates
  land in the 10-to-50 range, but not all: the full spread runs from about 4 to
  about 270, and roughly one metro in five sits outside 10-50. The very highest
  rates belong to *small* metros whose repost correction is the thinnest, so their
  exact value may run about 15 to 20 percent high; the rank ordering is reliable,
  the precise number at the extreme top less so.
- **The footer** on the map page states the method and the caveats in short
  form; this document is the long version.

---

*Every number on the map is reproducible from the scripts in `pipeline/` and the
free APIs listed above; see [README.md](README.md) to run it, and [CLAUDE.md](CLAUDE.md)
for the technical details and the exact rules behind each correction.*
